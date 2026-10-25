#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: `@kern:lang evm` is a REAL frontend, not a dead table row (#342).

WHY THIS GATE EXISTS.

`VALUE_SEMANTICS` contained an `evm` row (`div_zero_value=True`, `signed=False`),
but `lang="evm"` was NOT set by any parse path: the language came from the file
extension only, and Python's `parse_file` pinned `_CURRENT_LANG = "python"`
outright. So the row was DEAD - real EVM code never went through it (defect #342,
recorded honestly in the journal).

WHAT IS ASSERTED (TWO-SIDED, lesson #178 - a check that cannot fail proves
nothing):

  1. WITH the directive: `examples/evm_semantics_demo.py` gets 2 PROVEN and
     NO violations. The identity `(-7) / 2 == -3` is TRUNCATION, and under
     Python semantics it would be `-4` - so a passing verdict here means the
     EVM semantics actually applied.
  2. WITHOUT the directive: the SAME code (a temporary copy with the directive
     stripped) must produce a VIOLATION of the same contract. If it did not,
     the directive would change nothing and the "success" would be vacuous.

BOUNDARY, NAMED HONESTLY. `SDIV(MIN, -1) = MIN` (wrap-around) is NOT asserted
here: in the Int model there is no type bound (mathematical integers give
`2147483648`), and the BV path runs into the proof checker's coverage - Z3
proves it, our checker cannot re-derive a QF_BV derivation (class #118). That is
a separate piece of work, visible as an honest SKIP in
`examples/evm_semantics_bv.c`, not as a silent pass.

Запуск:  python3 tools/evm_lang_check.py [--selftest]
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "evm_semantics_demo.py"
BV = ROOT / "examples" / "evm_semantics_bv.c"


def _run(path: Path) -> str:
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "kern_contracts.py"), str(path)],
                       capture_output=True, text=True, errors="replace",
                       cwd=ROOT, timeout=600)
    return p.stdout + p.stderr


def _tally(out: str) -> dict:
    """Числа из ИТОГО: доказано / нарушено / ложных тревог / SKIP."""
    m = re.search(r"ИТОГО:\s*доказано\s*(\d+).*?нарушено\s*(\d+).*?ЛОЖНЫХ ТРЕВОГ\s*(\d+)", out, re.S)
    if not m:
        return {}
    return {"proven": int(m.group(1)), "violated": int(m.group(2)),
            "false_alarms": int(m.group(3))}


def main(argv=None) -> int:
    args = sys.argv[1:] if isinstance(argv, list) else (sys.argv[1:] if argv is None else [])
    if "--selftest" in args:
        return selftest()
    print("ФРОНТЕНД `@kern:lang evm` (дефект #342)")
    if not DEMO.exists() or not BV.exists():
        print("[FAIL] нет фикстур examples/evm_semantics_demo.py / evm_semantics_bv.c")
        return 1

    # 1) С директивой: EVM-семантика (усечение) -> контракт доказан.
    with_dir = _run(DEMO)
    t1 = _tally(with_dir)
    if not t1:
        print("[FAIL] не удалось разобрать ИТОГО на фикстуре с директивой")
        return 1
    ok1 = t1["proven"] >= 2 and t1["violated"] == 0 and t1["false_alarms"] == 0
    print(f"  [{'OK' if ok1 else 'ПРОВАЛ'}] С директивой: доказано {t1['proven']}, "
          f"нарушено {t1['violated']}, ложных тревог {t1['false_alarms']}")

    # 2) БЕЗ директивы: тот же код обязан НАРУШИТЬ тот же контракт (Python floor).
    with tempfile.TemporaryDirectory() as d:
        stripped = Path(d) / "evm_without_directive.py"
        text = DEMO.read_text(encoding="utf-8")
        stripped.write_text(re.sub(r"^\s*#\s*@kern:lang\s+evm\s*$", "", text, flags=re.M),
                            encoding="utf-8")
        no_dir = _run(stripped)
    t2 = _tally(no_dir)
    ok2 = bool(t2) and t2["violated"] >= 1
    print(f"  [{'OK' if ok2 else 'ПРОВАЛ'}] Без директивы: нарушено "
          f"{t2.get('violated', '?')} (обязано быть >= 1 — иначе директива ничего не меняет)")

    # 3) BV-фикстура: честный SKIP с причиной, а не молчаливый пропуск.
    bv_out = _run(BV)
    ok3 = "[BV]" in bv_out and ("SKIP" in bv_out or "ДОКАЗАНО" in bv_out)
    print(f"  [{'OK' if ok3 else 'ПРОВАЛ'}] BV-фикстура: путь BV выбран, вердикт назван честно")

    if not (ok1 and ok2 and ok3):
        print("\n[FAIL] фронтенд `@kern:lang evm` не подтверждён двусторонне")
        return 1
    print("\n[OK] `@kern:lang evm` — рабочий фронтенд: с директивой семантика EVM "
          "(усечение) доказывается, без неё тот же код НАРУШАЕТ контракт")
    return 0


def selftest() -> int:
    """Мета-тест: гейт обязан различать «директива работает» и «её нет»."""
    import tempfile
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.py"
        p.write_text("# @kern:lang evm\nprint(1)\n", encoding="utf-8")
        stripped = re.sub(r"^\s*#\s*@kern:lang\s+evm\s*$", "",
                          p.read_text(encoding="utf-8"), flags=re.M)
        if "@kern:lang" in stripped:
            print("[FAIL] selftest: снятие директивы не сработало")
            bad += 1
        else:
            print("[OK] selftest: снятие директивы работает (контроль двусторонний)")
        if _tally("ИТОГО: доказано 2 | T_advisory 0 | нарушено 1 | ЛОЖНЫХ ТРЕВОГ 0") != \
                {"proven": 2, "violated": 1, "false_alarms": 0}:
            print("[FAIL] selftest: разбор ИТОГО неверен")
            bad += 1
        else:
            print("[OK] selftest: разбор ИТОГО верен")
        if _tally("нет итога"):
            print("[FAIL] selftest: отсутствие ИТОГО не распознано")
            bad += 1
        else:
            print("[OK] selftest: отсутствие ИТОГО распознано (честный отказ)")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] evm-lang selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
