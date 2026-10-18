#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""ДИФФЕРЕНЦИАЛЬНЫЙ ГЕЙТ: встроенный LIA-решатель против реального Z3.

ПУНКТ 1 ПЛАНА v2.5. Встроенный решатель (`src/verifier/builtin_lia.zig`,
Фурье — Моцкин) обязан быть ЗВУЧИМ. Проверяем это не словами, а сравнением с
эталоном — Z3 — на наборе линейных систем:

  * `builtin == UNSAT` ОБЯЗАН давать `Z3 == unsat`   (0 ложных «доказано»!);
  * `builtin == SAT`   ОБЯЗАН давать `Z3 == sat` И его точка обязана
                        УДОВЛЕТВОРЯТЬ системе (проверяем в Python);
  * `builtin == UNKNOWN` — честный отказ, никаких заявлений (пропускаем).

Код возврата 0 = расхождений нет. Любое расхождение -> rc=1 с печатью системы.
"""
import os
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
Z3_CANDIDATES = [
    Path.home() / "ai_lab" / ".venv" / "bin" / "z3",
    Path("/usr/bin/z3"),
    Path("/usr/local/bin/z3"),
]

N_SYSTEMS = 100
VARS = ["a", "b", "c", "d"]

# ВОРКЕРОВ ПУЛА. Проверки НЕЗАВИСИМЫ (каждая пишет свои файлы), поэтому
# распараллеливание не меняет НИ ОДНОГО вердикта — только время.
WORKERS = int(os.environ.get("KERN_LIA_WORKERS", min(6, os.cpu_count() or 1)))


def tmp_root() -> str:
    """RAM-диск, если он есть (устраняет дисковый I/O и fsync), иначе /tmp.

    Точность от этого не зависит: те же файлы, те же команды, те же вердикты.
    """
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        d = shm / "kern-lia-diff"
        d.mkdir(exist_ok=True)
        return str(d)
    return "/tmp"


def gen(rng):
    """Случайная линейная система: список (coeffs, constant) как `sum + k <= 0`.

    РАСШИРЕНО (рубеж 5 приёмки Эшелона 1): до 4 переменных, большие
    коэффициенты, равенства (два нестрогих неравенства) и строгие неравенства
    (целочисленный сдвиг `a < b <=> a - b + 1 <= 0`).
    """
    nv = rng.choice([1, 1, 2, 2, 3, 4])
    nc = rng.randint(2, 6)
    cons = []
    for _ in range(nc):
        coeffs = [0] * nv
        for i in range(nv):
            if rng.random() < 0.65:
                coeffs[i] = rng.choice([-7, -5, -3, -2, -1, 1, 2, 3, 5, 7, 11])
        if all(c == 0 for c in coeffs):
            coeffs[0] = 1
        cons.append((coeffs, rng.randint(-25, 25)))
    # РАВЕНСТВО: `sum + k = 0` == `(sum + k <= 0) AND (-sum - k <= 0)`.
    if rng.random() < 0.35:
        coeffs = [0] * nv
        for i in range(nv):
            if rng.random() < 0.6:
                coeffs[i] = rng.choice([-3, -1, 1, 3])
        if all(c == 0 for c in coeffs):
            coeffs[0] = 2
        k = rng.randint(-8, 8)
        cons.append((list(coeffs), k))
        cons.append(([-c for c in coeffs], -k))
    # СТРОГОЕ НЕРАВЕНСТВО `a < b` над Z: `a - b + 1 <= 0`.
    if nv >= 2 and rng.random() < 0.35:
        i, j = rng.sample(range(nv), 2)
        coeffs = [0] * nv
        coeffs[i], coeffs[j] = 1, -1
        cons.append((coeffs, 1))
    return cons


def write_lia(cons, path):
    lines = []
    for coeffs, k in cons:
        toks = [f"{c}:{VARS[i]}" for i, c in enumerate(coeffs) if c != 0]
        lines.append("LE " + " ".join(toks + [str(k)]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_smt2(cons, nv, path):
    out = ["(set-logic QF_LIA)"]
    for i in range(nv):
        out.append(f"(declare-const {VARS[i]} Int)")
    for coeffs, k in cons:
        parts = [f"(* {c} {VARS[i]})" for i, c in enumerate(coeffs) if c != 0]
        lhs = parts[0] if len(parts) == 1 else "(+ " + " ".join(parts) + ")"
        out.append(f"(assert (<= {lhs} {-k}))")  # sum + k <= 0  <=>  sum <= -k
    out.append("(check-sat)")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def run_builtin(lia_path):
    r = subprocess.run([str(KERNC), "lia", str(lia_path)],
                       capture_output=True, text=True, timeout=60)
    out = (r.stdout + r.stderr).strip()
    if out.startswith("UNSAT"):
        return "unsat", {}
    if out.startswith("SAT"):
        pt = {}
        for tok in out.split()[1:]:
            if "=" in tok:
                n, v = tok.split("=", 1)
                pt[n] = int(v)
        return "sat", pt
    return "unknown", {}


def run_z3(z3, smt_path):
    r = subprocess.run([str(z3), str(smt_path)], capture_output=True,
                       text=True, timeout=60)
    out = (r.stdout + r.stderr).strip().splitlines()
    for line in out:
        if line.strip() in ("sat", "unsat", "unknown"):
            return line.strip()
    return "unknown"


def satisfies(cons, pt):
    for coeffs, k in cons:
        acc = k
        for i, c in enumerate(coeffs):
            acc += c * pt.get(VARS[i], 0)
        if acc > 0:
            return False
    return True


def check_one(args):
    """Одна независимая проверка: встроенный решатель vs Z3. Возвращает
    `(i, cons, builtin_verdict, point, z3_verdict)` — вердикты НЕ меняются от
    того, что задачи идут параллельно (каждая пишет свои файлы)."""
    i, cons, z3, td = args
    nv = max(len(c) for c, _ in cons)
    lp = Path(td) / f"s{i}.lia"
    sp = Path(td) / f"s{i}.smt2"
    write_lia(cons, lp)
    write_smt2(cons, nv, sp)
    bv, pt = run_builtin(lp)
    zv = run_z3(z3, sp)
    return (i, cons, bv, pt, zv, lp)


def main() -> int:
    if not KERNC.exists():
        print(f"[!] не найден {KERNC} (соберите: zig build)")
        return 2
    z3 = next((p for p in Z3_CANDIDATES if p.exists()), None)
    if z3 is None:
        print("[!] не найден z3 — дифференциальный гейт невозможен (это НЕ «ок»)")
        return 2

    rng = random.Random(20260218)
    systems = [gen(rng) for _ in range(N_SYSTEMS)]
    false_accept = 0   # builtin UNSAT, а Z3 sat  — КАТАСТРОФА
    false_counter = 0  # builtin SAT, а Z3 unsat — КАТАСТРОФА
    checked = 0
    skipped = 0
    with tempfile.TemporaryDirectory(dir=tmp_root()) as td:
        jobs = [(i, cons, z3, td) for i, cons in enumerate(systems)]
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(check_one, jobs))
        # ДЕТЕРМИНИРОВАННЫЙ ПОРЯДОК ВЫВОДА: сортируем по индексу системы.
        for i, cons, bv, pt, zv, lp in sorted(results, key=lambda r: r[0]):
            if bv == "unknown":
                skipped += 1
                continue
            checked += 1
            if bv == "unsat" and zv != "unsat":
                false_accept += 1
                print(f"[!] ЛОЖНОЕ «доказано» на системе {i}: Z3={zv}")
                print(lp.read_text(encoding="utf-8"))
            elif bv == "sat":
                if zv != "sat":
                    false_counter += 1
                    print(f"[!] ЛОЖНЫЙ контрпример на системе {i}: Z3={zv}")
                    print(lp.read_text(encoding="utf-8"))
                elif not satisfies(cons, pt):
                    false_counter += 1
                    print(f"[!] точка НЕ удовлетворяет системе {i}: {pt}")
                    print(lp.read_text(encoding="utf-8"))

    print(f"СИСТЕМ: {N_SYSTEMS} | воркеров: {WORKERS} | tmp: {tmp_root()}")
    print(f"сверено с Z3: {checked} | честных unknown: {skipped}")
    print(f"ЛОЖНЫХ «доказано» (builtin UNSAT vs Z3 sat):   {false_accept}")
    print(f"ЛОЖНЫХ контрпримеров (builtin SAT vs Z3 unsat): {false_counter}")
    if false_accept == 0 and false_counter == 0:
        print("[OK] 0 расхождений с Z3 — встроенный решатель звучим на этом наборе")
        return 0
    print("[!] РАСХОЖДЕНИЯ С Z3 — встроенный решатель НЕ ЗВУЧИМ")
    return 1


if __name__ == "__main__":
    sys.exit(main())
