#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""ИСПЫТАНИЕ А: АДВЕРСАРИАЛЬНЫЙ ФАЗЗЕР ПРУФ-ЧЕКЕРА (Proof-DAG Tamper Fuzzer).

ЗАЧЕМ. Мы довели `musl src/stdlib/abs.c` до `[PROOF VERIFIED] trusted: 0 |
holes: 0` (51 шаг). Это ЧИСЛО само по себе ничего не доказывает: нужно показать,
что вывод НЕЛЬЗЯ незаметно подделать. Фаззер берёт РЕАЛЬНЫЙ вывод Z3 и вносит в
него точечные искажения — по одному на прогон — и требует, чтобы чекер на КАЖДОЙ
подделке отказал.

ЗАКОН ЗВУЧНОСТИ (критерий приёмки): для всех N подделок rc != 0 (то есть НЕ
`checksPass() and proof_concludes_false and trusted == 0`). Если хоть одна
подделка проходит — чекер не звучим, и `trusted: 0` на `abs.c` был случайностью.

КАТЕГОРИИ ИСКАЖЕНИЙ (по классам правил вывода):
  * оператор сравнения: `(<= ` -> `(< `, `(>= ` -> `(> `  (строгость);
  * арифметика терма:   `(+ ` -> `(- `, `(* ` -> `(+ `, `(- 1)` -> `(- 2)`;
  * булева связка:      `(or ` -> `(and `;
  * ссылка на шаг:      `@xN` -> `@x(N+1)` (подмена посылки);
  * имя:                `z3name!1` -> `z3name!9` (неизвестный символ);
  * константа:          хвост `0))` -> `1))`.

Запуск:  python3 tools/proof_tamper_check.py [--smt FILE] [--proof FILE] [--n 30]
Выход:   rc=0 — все подделки отвергнуты; rc=1 — есть принятая подделка.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
FIX = ROOT / "tests" / "fixtures"
DEFAULT_SMT = FIX / "abs_contract.smt2"
DEFAULT_PROOF = FIX / "abs_proof.txt"

# ТРИ НЕЗАВИСИМЫЕ ТЕОРИИ (Эшелон 4 закрепил `trusted: 0` на каждой из них):
#   * QF_LIA  — `musl abs.c`, 51 шаг (Фаркаш, расщепление клауз);
#   * QF_S    — санитайзер путей, 39 шагов (строковые предикаты, seq.unit/str.++);
#   * IEEE-754-модель — `float NaN`, 56 шагов (булевы переменные + линейная модель).
# Адверсариальная проверка ОБЯЗАНА покрывать все три: звучность, доказанная на
# одной теории, ничего не говорит о другой.
TARGETS = [
    ("abs.c (QF_LIA)", FIX / "abs_contract.smt2", FIX / "abs_proof.txt", 30),
    ("QF_S (sanitizer)", FIX / "qfs_sanitizer.smt2", FIX / "qfs_proof.txt", 5),
    ("IEEE-754 (NaN)", FIX / "ieee754_nan.smt2", FIX / "ieee754_proof.txt", 5),
]

# (regex, замена, метка). Каждое искажение применяется к ОДНОМУ вхождению —
# так получается N РАЗНЫХ подделок, а не одна и та же.
MUTATIONS = [
    (r"\(<= ", "(< ", "<= -> <"),
    (r"\(>= ", "(> ", ">= -> >"),
    (r"\(\+ ", "(- ", "+ -> -"),
    (r"\(\* ", "(+ ", "* -> +"),
    (r"\(- 1\)", "(- 2)", "(- 1) -> (- 2)"),
    (r"\(or ", "(and ", "or -> and"),
    (r"z3name!1", "z3name!9", "имя -> неизвестное"),
    (r"0\)\)", "1))", "константа 0 -> 1"),
    (r"@x(\d+)", "@x9", "@xN -> @x9 (подмена посылки)"),
]


def tmp_dir() -> str:
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        d = shm / "kern-tamper"
        d.mkdir(exist_ok=True)
        return str(d)
    return "/tmp"


def make_tampers(proof: str, n: int):
    """Сгенерировать до `n` РАЗНЫХ подделок реального вывода."""
    out = []
    seen = set()
    for pat, rep, label in MUTATIONS:
        idx = 0
        while len(out) < n:
            m = None
            for k, mm in enumerate(re.finditer(pat, proof)):
                if k == idx:
                    m = mm
                    break
            if m is None:
                break
            tampered = proof[:m.start()] + rep + proof[m.end():]
            idx += 1
            if tampered == proof or tampered in seen:
                continue
            seen.add(tampered)
            out.append((label, idx, tampered))
        if len(out) >= n:
            break
    return out[:n]


def check_one(args):
    kernc, smt_path, td, i, label, tampered = args
    pf = Path(td) / f"proof_{i}.txt"
    pf.write_text(tampered, encoding="utf-8")
    r = subprocess.run([str(kernc), "check-proof", str(smt_path), str(pf)],
                       capture_output=True, text=True, timeout=120)
    return i, label, r.returncode, (r.stdout + r.stderr).strip()


def run_target(kernc, name, smt_path, proof_path, n, jobs):
    """Проверить ОДНУ теорию: (имя, сколько подделок, список принятых).

    ВОЗВРАТ (n_tampers, accepted): если подделок сгенерировано МЕНЬШЕ, чем
    запрошено, — это НЕ «успех»: цель обязана краснеть (иначе фаззер молча
    теряет покрытие, что и есть вакуумный кейс).
    """
    if not smt_path.exists() or not proof_path.exists():
        print(f"  [!] {name}: нет файлов {smt_path.name} / {proof_path.name}")
        return (0, [("нет фикстур", "файл отсутствует")])
    proof = proof_path.read_text(encoding="utf-8")

    r0 = subprocess.run([str(kernc), "check-proof", str(smt_path), str(proof_path)],
                        capture_output=True, text=True, timeout=120)
    print(f"  [контроль] {name}: неповреждённый вывод rc={r0.returncode} (ожидается 0)")
    if r0.returncode != 0:
        print("  [!] ЧЕКЕР НЕ ПРИНИМАЕТ ДАЖЕ ВЕРНЫЙ ВЫВОД — фаззер неприменим")
        return (0, [("контроль не прошёл", (r0.stdout + r0.stderr)[:200])])

    tampers = make_tampers(proof, n)
    print(f"  [i] {name}: подделок {len(tampers)} (нужно {n})")
    if len(tampers) < n:
        return (len(tampers), [("подделок меньше запрошенного", f"{len(tampers)} < {n}")])

    accepted = []
    with tempfile.TemporaryDirectory(dir=tmp_dir()) as td:
        jobs_l = [(kernc, smt_path, td, i, label, t)
                  for i, (label, _, t) in enumerate(tampers)]
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(check_one, jobs_l))

    for i, label, rc, out in sorted(results, key=lambda z: z[0]):
        ok = rc != 0
        if not ok:
            accepted.append((f"{name} #{i + 1} {label}", out))
        print(f"    [{i + 1:>2}/{len(tampers)}] {label:<34} rc={rc} -> "
              f"{'отвергнута OK' if ok else 'ПРИНЯТА !!!'}")
    return (len(tampers), accepted)


def main() -> int:
    ap = argparse.ArgumentParser(description="Адверсариальный фаззер пруф-чекера")
    ap.add_argument("--smt", default=None, help="одна фикстура (одиночный режим)")
    ap.add_argument("--proof", default=None, help="один вывод (одиночный режим)")
    ap.add_argument("--n", type=int, default=None,
                    help="подделок на цель (по умолчанию: 30/5/5 по трём теориям)")
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    args = ap.parse_args()

    if not KERNC.exists():
        print(f"[!] нет {KERNC} — соберите: zig build")
        return 2

    if args.smt or args.proof:
        n = args.n if args.n is not None else 30
        targets = [("одиночная цель", Path(args.smt or DEFAULT_SMT),
                    Path(args.proof or DEFAULT_PROOF), n)]
    else:
        targets = [(nm, s, p, (args.n if args.n is not None else k))
                   for nm, s, p, k in TARGETS]

    print(f"[i] теорий: {len(targets)} | подделок всего: "
          f"{sum(t[3] for t in targets)}")
    total, accepted_all = 0, []
    for nm, smt_p, proof_p, n in targets:
        print(f"--- {nm} ---")
        cnt, acc = run_target(KERNC, nm, smt_p, proof_p, n, args.jobs)
        total += cnt
        accepted_all.extend(acc)

    print("=" * 72)
    print(f"ПОДДЕЛОК ВСЕГО: {total} | ПРИНЯТО: {len(accepted_all)}")
    if not accepted_all:
        print("[OK] ЗВУЧНОСТЬ: ни одна подделка не прошла на всех теориях — "
              "`trusted: 0` подтверждён адверсариально")
        return 0
    print("[!] НЕЗВУЧНО: чекер принял подделанный вывод:")
    for label, out in accepted_all[:10]:
        print(f"    {label}: {str(out)[:200]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

