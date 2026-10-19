#!/usr/bin/env python3
# ЭКСТРЕМАЛЬНАЯ МАТРИЦА: ортогональная матрица Адамара H (элементы ±1).
#
# Задача: H[i][k] ∈ {-1, +1}; первая строка и столбец = +1;
#         сумма_k H[i][k]·H[j][k] = 0 для всех i ≠ j  (H·Hᵀ = N·I).
#
# ЧТО ДОКАЗЫВАЕТ. Для N = 2 и 4 матрица СУЩЕСТВУЕТ (SAT, модель из Z3,
# независимая проверка H·Hᵀ = N·I в Python). Для N = 3 её НЕ СУЩЕСТВУЕТ
# (UNSAT: произведение строк нечётной длины не может быть нулём) — это
# математический факт, а не «не нашли».
import subprocess
import sys
import tempfile
from pathlib import Path

KERNC = "./zig-out/bin/kernc"


def smt_for(n: int) -> str:
    lines = ["(set-logic ALL)"]
    for i in range(n):
        for j in range(n):
            lines.append(f"(declare-const h_{i}_{j} Int)")
            lines.append(f"(assert (or (= h_{i}_{j} 1) (= h_{i}_{j} (- 1))))")
    # нормализация: первая строка и первый столбец = +1
    for j in range(n):
        lines.append(f"(assert (= h_0_{j} 1))")
    for i in range(n):
        lines.append(f"(assert (= h_{i}_0 1))")
    # ортогональность строк
    for i in range(n):
        for j in range(i + 1, n):
            terms = " ".join(f"(* h_{i}_{k} h_{j}_{k})" for k in range(n))
            lines.append(f"(assert (= (+ {terms}) 0))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def run(n: int):
    text = smt_for(n)
    with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False, dir="/dev/shm") as f:
        f.write(text)
        p = f.name
    r = subprocess.run([KERNC, "prove", p], capture_output=True, text=True)
    Path(p).unlink(missing_ok=True)
    out = r.stdout + r.stderr
    return out


def parse_h(out: str, n: int) -> dict:
    """Значения переменных из строки `[КОНТРПРИМЕР] a = 1, b = -1, ...`."""
    vals = {}
    for line in out.splitlines():
        if "КОНТРПРИМЕР" not in line:
            continue
        body = line.split("КОНТРПРИМЕР", 1)[1]
        for tok in body.split(","):
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            k = k.strip().lstrip("]").strip()
            v = v.strip()
            try:
                vals[k] = int(v)
            except ValueError:
                pass
    return {k: v for k, v in vals.items() if k.startswith("h_")}


def check_orthogonal(h: dict, n: int) -> bool:
    for i in range(n):
        for j in range(n):
            s = sum(h.get(f"h_{i}_{k}", 0) * h.get(f"h_{j}_{k}", 0) for k in range(n))
            want = n if i == j else 0
            if s != want:
                return False
    return True


def main() -> int:
    if not Path(KERNC).exists():
        print(f"[!] нет {KERNC} (соберите: zig build)")
        return 2
    ok = True
    for n in (2, 4):
        out = run(n)
        h = parse_h(out, n)
        if len(h) != n * n:
            print(f"  [FAIL] N={n}: модель не получена")
            ok = False
            continue
        good = check_orthogonal(h, n)
        print(f"  [{'OK' if good else 'FAIL'}] N={n}: матрица найдена (SAT), H·Hᵀ = {n}·I проверено независимо")
        ok = ok and good
    # N=3: матрицы Адамара не существует -> UNSAT.
    out3 = run(3)
    unsat = ("КОНТРПРИМЕР" not in out3) and ("ДОКАЗАНО" in out3 or "UNSAT" in out3)
    print(f"  [{'OK' if unsat else 'FAIL'}] N=3: UNSAT — матрицы Адамара порядка 3 НЕ существует")
    ok = ok and unsat
    print("[OK] hadamard-check" if ok else "[FAIL] hadamard-check")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
