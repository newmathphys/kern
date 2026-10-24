#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: EVM semantics identities get a TRUSTED proof (defect #344).

WHY THIS GATE EXISTS.

`docs/evidence/step8_evm/smt/*.smt2` states three Yellow Paper identities:

  * `DIV(a, 0) = 0`          (division by zero is defined as zero in EVM)
  * `SDIV(MIN, -1) = MIN`    (two's-complement wrap-around)
  * `SDIV(-7, 2) = -3`       (truncation toward zero, NOT floor)

Z3 proves all three, but KERN's own proof checker used to REJECT the derivations
with `premises_unbound` (defects #341/#344): Z3 substitutes the BODY of a
`define-fun` in its output, while our contract keeps the CALL, so the premise
never bound to the contract. Two causes, both fixed:

  1. `define-fun` was not read from the SMT header (Z3 emits no `intro-def`
     for it) and argument substitution did not exist;
  2. constant arithmetic (`(= (div 7 2) 3)`) was not evaluated, so one step
     stayed trusted.

WHAT IS ASSERTED (per file): the CLI prints `[PROOF VERIFIED]` AND
`trusted: 0` AND `holes: 0`. Anything else - including a solver that says
"proved" while the checker refuses - is a FAILURE of this gate.

WHY THAT MATTERS: `trusted: 0` is the difference between "the solver says so"
and "our checker re-derived it". Accepting the step on trust would turn
`holes: 0` into fiction (defect #81).

Запуск:  python3 tools/evm_proof_check.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
SMT_DIR = ROOT / "docs" / "evidence" / "step8_evm" / "smt"

# Имя файла -> человекочитаемое тождество (для отчёта).
IDENTITIES = {
    "evm_div_by_zero_is_zero.smt2": "EVM DIV(a, 0) = 0",
    "evm_sdiv_min_by_minus_one_is_min.smt2": "EVM SDIV(MIN, -1) = MIN",
    "evm_sdiv_truncates_toward_zero.smt2": "EVM SDIV(-7, 2) = -3 (trunc, not floor)",
}


def run_case(path: Path) -> tuple[bool, str]:
    p = subprocess.run([str(KERNC), "prove", str(path)],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    out = p.stdout + p.stderr
    if "[PROOF VERIFIED]" not in out:
        return False, "нет [PROOF VERIFIED] — пруф-чекер НЕ подтвердил вывод"
    m = re.search(r"trusted:\s*(\d+)\s*\|\s*holes:\s*(\d+)", out)
    if not m:
        return False, "нет строки trusted/holes в выводе"
    trusted, holes = int(m.group(1)), int(m.group(2))
    if trusted != 0 or holes != 0:
        return False, f"trusted={trusted}, holes={holes} — шаги приняты на веру"
    return True, f"trusted=0, holes=0 ({m.group(0)})"


def main() -> int:
    if not KERNC.exists():
        print(f"[!] нет {KERNC.relative_to(ROOT)} — соберите: zig build")
        return 1
    bad = 0
    print("EVM-ТОЖДЕСТВА: ДОВЕРЕННОЕ ДОКАЗАТЕЛЬСТВО (дефект #344)")
    for name, human in IDENTITIES.items():
        path = SMT_DIR / name
        if not path.exists():
            print(f"  [ПРОВАЛ] {name}: файла нет")
            bad += 1
            continue
        try:
            ok, why = run_case(path)
        except subprocess.TimeoutExpired:
            ok, why = False, "таймаут"
        print(f"  [{'OK' if ok else 'ПРОВАЛ'}] {human} — {why}")
        if not ok:
            bad += 1
    if bad:
        print(f"\n[FAIL] тождеств без доверенного доказательства: {bad}")
        return 1
    print("\n[OK] все три тождества доказаны БЕЗ доверенных шагов и без дыр")
    return 0


if __name__ == "__main__":
    sys.exit(main())
