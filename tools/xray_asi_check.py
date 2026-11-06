#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ДЕФЕКТ #467 / ASI: `if` БЕЗ скобок не должен «проглатывать» остаток тела.

ЗАЧЕМ. `_clike_block_end` для `if` без фигурных скобок откатывался к «до
следующей `;`». В исходнике в стиле ASI (TypeScript/JS/Go БЕЗ точек с запятой)
следующей `;` нет — блок «проглатывал» всё до конца тела, и условие вложенного
`if` протекало как ФАКТ на последующие операторы. Два взаимоисключающих
протечки давали противоречие -> UNSAT -> ЛОЖНЫЙ «[DEAD BRANCH]». Найдено охотой
на чужом коде: `deepseek-ai/dsh-superagent-prototype` (`src/policy.ts`,
`settingsPolicy`) — достижимая ветвь `!trigger.human` была объявлена мёртвой.

ЧТО ПРОВЕРЯЕТСЯ (четыре фикстуры, оба направления обязательны):
  * `xray_asi_braceless_if.ts` — РЕАЛЬНЫЙ TS-модуль (ASI, без `;`): 0 находок;
  * `xray_asi_ts.ts` — минимальный TS-репродуктор: 0 находок;
  * `xray_asi_dead.ts` — ТОТ ЖЕ язык (TS), но НАСТОЯЩАЯ мёртвая ветвь: >= 1;
  * `xray_asi_positive_control.c` — C-контроль: >= 1.

НЕВАКУУМНОСТЬ. «0 находок» само по себе ничего не доказывает: полностью
пропущенный файл тоже даёт 0. Поэтому для нулевых фикстур гейт ТРЕБУЕТ, чтобы
`--xray` их действительно разобрал (`checked >= 1`, `skipped == 0`). Контроль в
ТОМ ЖЕ языке (TS), а не только в C, нужен потому, что правка живёт в
TS-ветке `_clike_block_end` — контроль на другом языке её бы не накрыл.

Запуск: python3 tools/xray_asi_check.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
KERN = ROOT / "tools" / "kern_contracts.py"

# (файл, подпись) — обязаны дать 0 находок И быть РЕАЛЬНО разобраны.
ZERO = [
    (FIX / "xray_asi_braceless_if.ts", "реальный TS (ASI, без `;`)"),
    (FIX / "xray_asi_ts.ts", "минимальный TS-репродуктор"),
]
# (файл, подпись) — настоящая мёртвая ветвь, детектор ОБЯЗАН её найти.
MUST_FIND = [
    (FIX / "xray_asi_dead.ts", "TS-контроль (тот же язык)"),
    (FIX / "xray_asi_positive_control.c", "C-контроль"),
]

# Сводка `--xray`: `checked A / B functions (trivial T), skipped S with ...`
SUMMARY = re.compile(r"checked (\d+) / (\d+) functions \(trivial (\d+)\), "
                     r"skipped (\d+) with")


def xray(path: Path) -> tuple[int, int, int]:
    """Прогон `kernc --xray`: (мёртвых ветвей, разобрано функций, пропущено)."""
    r = subprocess.run([sys.executable, str(KERN), "--xray", str(path)],
                       capture_output=True, text=True, timeout=300)
    out = (r.stdout or "") + (r.stderr or "")
    dead = len(re.findall(r"\[DEAD BRANCH\]", out))
    m = SUMMARY.search(out)
    if not m:
        # Нет сводки -> файл не разобран вовсе. Это НЕ «0 находок».
        return dead, -1, -1
    return dead, int(m.group(1)), int(m.group(4))


def main() -> int:
    print("=" * 68)
    print("KERN: регрессия #467/ASI — `if` без скобок не «проглатывает» тело")
    print("=" * 68)
    ok = True
    for path, label in ZERO:
        dead, checked, skipped = xray(path)
        print(f"  {label}: разобрано {checked}, пропущено {skipped}, "
              f"мёртвых ветвей {dead}  (нужно: >=1 разобрано, 0 пропущено, 0 находок)")
        if checked < 1 or skipped != 0:
            ok = False
            print("    [!] ВАКУУМ: файл НЕ разобран — «0 находок» ничего не значит")
        elif dead != 0:
            ok = False
            print("    [!] ЛОЖНОЕ ОБВИНЕНИЕ: вложенное условие протекло как факт")
    for path, label in MUST_FIND:
        dead, checked, skipped = xray(path)
        print(f"  {label}: разобрано {checked}, пропущено {skipped}, "
              f"мёртвых ветвей {dead}  (нужно: >= 1)")
        if dead < 1:
            ok = False
            print("    [!] детектор ослеп: реальная мёртвая ветвь НЕ найдена")
    if not ok:
        print("\n[FAIL] регрессия #467/ASI не пройдена")
        return 1
    print("\n[OK] ложного DEAD BRANCH нет (2 ASI-фикстуры, обе разобраны), "
          "реальные ветви ловятся (TS + C)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

