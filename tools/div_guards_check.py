#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""KERN gate: division guards are honoured in Python (defect #327).

WHY THIS GATE EXISTS.

The divisor obligation used to be built as `requires AND (divisor == 0)` WITHOUT
path conditions, so an explicitly guarded division was still accused:

    def f(a, b):
        return 0 if b == 0 else a // b     # guard is explicit
    [FAIL] f: ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ (делитель: b)  counterexample b = 0

For C-like code this was already fixed in #318 (`_clike_conds_at`); Python was
not. Now the guard active at the divisor is stored with it and the obligation
becomes `(and <guards> (= divisor 0))`.

WHAT IS ASSERTED (on `tests/fixtures/py_div_guards.py`):

  unguarded         -> REFUTED (control: the accusation is NOT weakened)
  ternary_guard     -> PROVEN  (`0 if b == 0 else a // b`)
  if_guard          -> PROVEN  (`if b == 0: return 0` + `return a // b`)
  wrong_guard       -> REFUTED (`if a > 0` says nothing about `b` — SOUNDNESS)
  sufficient_guard  -> PROVEN  (`if b > 0` implies `b != 0`)

The `wrong_guard` case is the important one: a rule that silenced every guarded
division would be a false NEGATIVE, which is worse than the original bug.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "py_div_guards.py"

fails = 0


def bad(msg: str) -> None:
    global fails
    print(f"  [ПРОВАЛ] {msg}")
    fails += 1


def main() -> int:
    env = dict(os.environ)
    env["PATH"] = str(Path.home() / "opt/zig-x86_64-linux-0.17.0") + ":" + env.get("PATH", "")
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(FIX)],
                       capture_output=True, text=True, cwd=ROOT, env=env, timeout=300)
    out = p.stdout + p.stderr

    # 1. деление ПОД ГАРДОМ не обвиняется
    for name in ("ternary_guard", "if_guard", "sufficient_guard"):
        if f"[PASS] {name}" not in out:
            bad(f"{name}: ожидалось ДОКАЗАНО — гард есть, обвинение ложно")
        if re.search(rf"\[FAIL\] {name}: ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ", out):
            bad(f"{name}: ЛОЖНОЕ ОБВИНЕНИЕ — активный гард не учтён")

    # 2. ЗВУЧИМОСТЬ: незащищённое и НЕДОСТАТОЧНЫЙ гард обвиняются
    for name, why in (("unguarded", "гарда нет"),
                      ("wrong_guard", "гард `a > 0` ничего не говорит про `b`")):
        if not re.search(rf"\[FAIL\] {name}: ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ", out):
            bad(f"{name}: обвинение ПОТЕРЯНО ({why}) — это ложное ОТРИЦАНИЕ")

    if not re.search(r"\[КОНТРПРИМЕР\] a = 0, b = 0", out):
        bad("контрпример для незащищённого деления не предъявлен")

    # 3. сводка не должна скрывать числа
    if "ЛОЖНЫХ ТРЕВОГ 0" not in out:
        bad("сводка: ложные тревоги на корректных контрактах")

    print("  проверено 5 функций: 3 под гардом -> ДОКАЗАНО, 2 без/слабым -> ОПРОВЕРГНУТО")
    if fails:
        print(f"\nПРОВАЛОВ: {fails}")
        return 1
    print("\nГАРДЫ ДЕЛЕНИЯ: активный гард учтён; недостаточный гард обвинение НЕ снимает")
    return 0


if __name__ == "__main__":
    sys.exit(main())
