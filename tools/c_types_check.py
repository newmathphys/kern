#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""KERN gate: C machine types receive verdicts (defects #312, #321).

WHY THIS GATE EXISTS.

#312: the C parameter parser required exactly ONE word before the parameter name,
so `unsigned int c` was skipped while `size_t a` worked — even though
`TYPE_RANGE` already knew `unsigned`.

#321: after #312 was fixed, the RETURN type was still taken raw, so
`ret = "unsigned int"` was not found in `TYPE_RANGE`, the machine-overflow
obligation was **silently skipped**, and a function with a genuine wrap-around
was reported PROVEN. Same class as #180 (Rust). Ground truth:

    $ gcc -O0 ... ; a=4294967295 b=1 -> result=0  contract result>=a: VIOLATED

WHAT IS ASSERTED (all on `tests/fixtures/c_types_demo.c`):

  u32_add           -> REFUTED with an overflow counterexample for `unsigned`
  nibble            -> PROVEN (bit-vector theory, `unsigned int` accepted)
  widen             -> PROVEN (multi-word `long long` accepted, i64 range applied)
  byte_id           -> PROVEN (`unsigned char` accepted)
  unsupported_float -> SKIP WITH a reason (never a verdict)
  unsupported_char  -> SKIP WITH a reason (`char` signedness is implementation-defined)

Every integer type must get a VERDICT; nothing may be skipped silently.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "c_types_demo.c"

fails = 0


def bad(msg: str) -> None:
    global fails
    print(f"  [ПРОВАЛ] {msg}")
    fails += 1


def run() -> str:
    env = {"PATH": str(Path.home() / "opt/zig-x86_64-linux-0.17.0") + ":" + __import__("os").environ.get("PATH", "")}
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(FIX)],
                       capture_output=True, text=True, cwd=ROOT, env=env, timeout=300)
    return p.stdout + p.stderr


def main() -> int:
    out = run()

    # 1. every integer-typed function gets a verdict, not a silent skip
    for name in ("u32_add", "nibble", "widen", "byte_id"):
        if not re.search(rf"\[(PASS|FAIL)\] {name}\b", out):
            bad(f"{name}: НЕТ вердикта — тип отвергнут или пропущен молча")

    # 2. the real overflow is REFUTED with the right counterexample
    m = re.search(r"\[FAIL\] u32_add: ПЕРЕПОЛНЕНИЕ типа `unsigned`.*?"
                  r"\[КОНТРПРИМЕР\] result = 4294967296, b = 1, a = 4294967295",
                  out, re.S)
    if not m:
        bad("u32_add: переполнение `unsigned` НЕ опровергнуто с ожидаемым контрпримером "
            "(регрессия #321: обязанность переполнения молча снята)")
    elif "[PASS] u32_add" in out:
        bad("u32_add: ДОКАЗАНО — это ложное ДОКАЗАНО (в C результат заворачивается в 0)")

    # 3. the proven ones really are proven
    for name in ("nibble", "widen", "byte_id"):
        if f"[PASS] {name}" not in out:
            bad(f"{name}: ожидалось ДОКАЗАНО")

    # 4. out-of-subset types are skipped WITH a reason, never silently
    for name, needle in (("unsupported_float", "тип c 'float'"),
                         ("unsupported_char", "тип c 'char'")):
        if not re.search(rf"{name} \(стр\. \d+\): SKIP — {re.escape(needle)}", out):
            bad(f"{name}: ожидался SKIP с причиной {needle!r}")

    # 5. the summary must not hide anything
    if "вне подмножества 2" not in out:
        bad("сводка: ожидалось «вне подмножества 2» (float + char)")
    if "ЛОЖНЫХ ТРЕВОГ 0" not in out:
        bad("сводка: ложные тревоги на корректных контрактах")

    print("  проверено функций: 6 (4 целых типа -> вердикт, 2 -> SKIP с причиной)")
    if fails:
        print(f"\nПРОВАЛОВ: {fails}")
        return 1
    print("\nC-ТИПЫ: все целочисленные типы получают вердикт; переполнение `unsigned` опровергнуто")
    return 0


if __name__ == "__main__":
    sys.exit(main())
