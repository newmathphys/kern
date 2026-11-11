#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""#618: вердикт `kernc prove` обязан РАЗЛИЧАТЬ sat (F) и таймаут/unknown (N).

ДО-фикс: печаталось `НЕ доказано (контрпример/таймаут)` в обоих случаях, то есть
опровержение и «не решено» выглядели одинаково (класс: одна фраза на два исхода).

ДВУСТОРОННИЙ контроль (оба направления обязательны):
  R1 `sat`-формула печатает `ОПРОВЕРГНУТО` и НЕ печатает `ДОКАЗАНО`;
  R2 `unsat`-формула печатает `ДОКАЗАНО` и НЕ печатает `ОПРОВЕРГНУТО`;
  R3 старая склеенная фраза отсутствует в выводе обоих прогонов;
  R4 в исходнике есть ЯВНАЯ ветка `.Timeout`/`.Unknown` -> `НЕ РЕШЕНО`
     (статический контроль того, что исход N вообще назван).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KC = ROOT / "zig-out" / "bin" / "kernc"
SAT = ROOT / "audits" / "smt2" / "binary_search_mid_buggy.smt2"
UNSAT = ROOT / "audits" / "smt2" / "ring_slot_array_slot_isolation_good.smt2"
OLD = "контрпример/таймаут"


def run(path: Path) -> str:
    p = subprocess.run([str(KC), "prove", str(path)], capture_output=True,
                       text=True, timeout=180, cwd=str(ROOT))
    return p.stdout + p.stderr


def main() -> int:
    if not KC.is_file():
        print(f"[НЕТ] kernc отсутствует: {KC}")
        return 2
    for f in (SAT, UNSAT):
        if not f.is_file():
            print(f"[НЕТ] фикстура отсутствует: {f}")
            return 2
    bad = 0
    sat_out, unsat_out = run(SAT), run(UNSAT)

    if "ОПРОВЕРГНУТО" in sat_out and "ДОКАЗАНО" not in sat_out:
        print("[OK] R1: sat -> «ОПРОВЕРГНУТО (найден контрпример / sat, Белнап F)»")
    else:
        print("[FAIL] R1: sat-формула не названа опровергнутой"); bad += 1

    if "ДОКАЗАНО" in unsat_out and "ОПРОВЕРГНУТО" not in unsat_out:
        print("[OK] R2: unsat -> «ДОКАЗАНО (допущено)»")
    else:
        print("[FAIL] R2: unsat-формула не названа доказанной"); bad += 1

    if OLD in sat_out or OLD in unsat_out:
        print(f"[FAIL] R3: склеенная фраза «{OLD}» всё ещё печатается"); bad += 1
    else:
        print("[OK] R3: склеенной фразы нет ни на sat, ни на unsat")

    src = (ROOT / "src" / "main.zig").read_text(encoding="utf-8")
    has_n = (".Timeout =>" in src and "НЕ РЕШЕНО (таймаут решателя" in src
             and ".Unknown =>" in src and "НЕ РЕШЕНО (решатель: unknown" in src)
    if has_n:
        print("[OK] R4: исход N назван явно (`.Timeout`/`.Unknown` -> «НЕ РЕШЕНО»)")
    else:
        print("[FAIL] R4: нет явной ветки для таймаута/unknown"); bad += 1

    if bad:
        print(f"[FAIL] #618: провалов {bad}")
        return 1
    print("[OK] #618: sat и «не решено» различаются в печати (2 стороны + статика)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
