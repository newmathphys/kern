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
DEFAULT_SMT = ROOT / "tests" / "fixtures" / "abs_contract.smt2"
DEFAULT_PROOF = ROOT / "tests" / "fixtures" / "abs_proof.txt"

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


def main() -> int:
    ap = argparse.ArgumentParser(description="Адверсариальный фаззер пруф-чекера")
    ap.add_argument("--smt", default=str(DEFAULT_SMT))
    ap.add_argument("--proof", default=str(DEFAULT_PROOF))
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    args = ap.parse_args()

    if not KERNC.exists():
        print(f"[!] нет {KERNC} — соберите: zig build")
        return 2
    smt_path, proof_path = Path(args.smt), Path(args.proof)
    if not smt_path.exists() or not proof_path.exists():
        print(f"[!] нужны файлы: {smt_path} и {proof_path}")
        return 2
    proof = proof_path.read_text(encoding="utf-8")

    # ПОЗИТИВНЫЙ КОНТРОЛЬ: неповреждённый вывод ОБЯЗАН подтвердиться.
    r0 = subprocess.run([str(KERNC), "check-proof", str(smt_path), str(proof_path)],
                        capture_output=True, text=True, timeout=120)
    print(f"[контроль] неповреждённый вывод: rc={r0.returncode} (ожидается 0)")
    if r0.returncode != 0:
        print("[!] ЧЕКЕР НЕ ПРИНИМАЕТ ДАЖЕ ВЕРНЫЙ ВЫВОД — фаззер неприменим")
        return 2

    tampers = make_tampers(proof, args.n)
    print(f"[i] подделок сгенерировано: {len(tampers)} (нужно {args.n})")

    accepted = []
    with tempfile.TemporaryDirectory(dir=tmp_dir()) as td:
        jobs = [(KERNC, smt_path, td, i, label, t) for i, (label, _, t) in enumerate(tampers)]
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            results = list(ex.map(check_one, jobs))

    for i, label, rc, out in sorted(results, key=lambda z: z[0]):
        ok = rc != 0
        if not ok:
            accepted.append((i, label, out))
        mark = "отвергнута OK" if ok else "ПРИНЯТА !!!"
        print(f"  [{i + 1:>2}/{len(tampers)}] {label:<34} rc={rc} -> {mark}")

    print("-" * 72)
    print(f"ПОДДЕЛОК: {len(tampers)} | отвергнуто: {len(tampers) - len(accepted)} "
          f"| ПРИНЯТО: {len(accepted)}")
    if not accepted:
        print("[OK] ЗВУЧНОСТЬ: ни одна подделка не прошла — "
              "`trusted: 0` на abs.c подтверждён адверсариально")
        return 0
    print("[!] НЕЗВУЧНО: чекер принял подделанный вывод:")
    for i, label, out in accepted:
        print(f"    #{i + 1} {label}: {out[:200]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
