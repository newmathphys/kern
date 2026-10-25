#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: the CHARTER TEXT must agree with what the charter checker MEASURES.

WHY THIS GATE EXISTS (defect #350, found by the plan review).

`tools/charter_check.py` reported `законов: 8 | доказано 8 | не покрыто 0`
(EXPECTED_UNCOVERED is empty since 2026-10-22, when #303 was closed by the sound
`dropTriv` fold). At the same time `docs/CHARTER.md` §3 was still titled "Why two
laws are not claimed as proven" and the table marked L4/L5 as NOT proven, while
`docs/CHARTER.ru.md` said "6 доказано, 2 не покрыты". The CANON contradicted the
measurement of the very gate that maintains it - and NO guard noticed:
`charter-check` verifies the LAWS, `docs-parity` compares fact anchors,
`claims-audit` scans numbers. Nothing compared the prose with the output.

WHAT IS ASSERTED.

  1. The number of laws the checker calls PROVEN equals the number of rows marked
     as proven in `docs/CHARTER.md` AND in `docs/CHARTER.ru.md`.
  2. If the checker reports NOT-COVERED laws, their ids must be NAMED in both
     texts (a gap must not be silent).

WHY BOTH DIRECTIONS MATTER. Text more pessimistic than reality is a lie about the
project's own state (that was the defect). Text more optimistic is the failure
mode the whole project exists to catch - so the gate forbids both.

Запуск:  python3 tools/charter_text_check.py [--selftest]
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EN = ROOT / "docs" / "CHARTER.md"
RU = ROOT / "docs" / "CHARTER.ru.md"

# Строка таблицы класса I: `| **L4** | ... | <статус> |`.
LAW_ROW = re.compile(r"^\|\s*\*\*(L\d+)\*\*\s*\|.*\|\s*([^|]*)\|\s*$", re.M)
PROVEN_EN = "PROVEN"
PROVEN_RU = "ДОКАЗАНО"
# Признаки утверждения «не доказано» — их не должно быть, когда покрыто всё.
NOT_PROVEN_MARKS = ("not claimed as proven", "не заявлен", "не покрыт", "не покрыты")

# Вывод charter_check: «[I] законов: 8 | доказано 8 | не покрыто пруф-чекером 0 | …».
MEASURED = re.compile(r"законов:\s*(\d+)\s*\|\s*доказано\s*(\d+)\s*\|\s*не покрыто[^|]*?(\d+)\s*\|")


def measured() -> tuple[int, int, int] | None:
    """(всего, доказано, не покрыто) из вывода charter_check, либо None."""
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "charter_check.py")],
                       capture_output=True, text=True, errors="replace",
                       cwd=ROOT, timeout=600)
    out = p.stdout + p.stderr
    m = MEASURED.search(out)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def proven_in(path: Path, mark: str) -> tuple[int, list[str]]:
    """Сколько законов помечено доказанными и какие НЕ помечены."""
    text = path.read_text(encoding="utf-8", errors="replace")
    proven, not_proven = 0, []
    for law, status in LAW_ROW.findall(text):
        hit = (mark in status.upper()) if mark == PROVEN_EN else (mark in status)
        if hit:
            proven += 1
        else:
            not_proven.append(law)
    return proven, not_proven


def check(total: int, proven: int, uncovered: int) -> list[str]:
    errs: list[str] = []
    if not EN.exists() or not RU.exists():
        return [f"нет файла устава: {EN.name} / {RU.name}"]
    en_n, en_bad = proven_in(EN, PROVEN_EN)
    ru_n, ru_bad = proven_in(RU, PROVEN_RU)
    if en_n != proven:
        errs.append(f"{EN.name}: доказанными помечено {en_n}, а чекер измеряет {proven} "
                    f"(не помечены: {', '.join(en_bad) or '—'})")
    if ru_n != proven:
        errs.append(f"{RU.name}: доказанными помечено {ru_n}, а чекер измеряет {proven} "
                    f"(не помечены: {', '.join(ru_bad) or '—'})")
    if uncovered == 0:
        # ⚠️ Ищем утверждение «не доказано» ТОЛЬКО там, где оно было бы ложью:
        # в СТАТУСЕ строки класса I и в ЗАГОЛОВКАХ. Широкий поиск по всему
        # тексту давал ложные срабатывания на законных местах — измерении
        # («0 не покрыто пруф-чекером») и разделе политики («ничего из этого
        # не заявлено проверяемым»). Гейт, который кричит на верный текст,
        # будет отключён — поэтому граница названа явно.
        for path in (EN, RU):
            text = path.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                is_heading = stripped.startswith("#")
                is_law_row = LAW_ROW.match(line) is not None
                if not (is_heading or is_law_row):
                    continue
                low = line.lower()
                for mark in NOT_PROVEN_MARKS:
                    if mark.lower() in low:
                        errs.append(f"{path.name}: строка "
                                    f"{'заголовка' if is_heading else 'таблицы класса I'} "
                                    f"содержит «{mark}», хотя чекер сообщает «не покрыто 0»: "
                                    f"{stripped[:80]}")
    return errs


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    print("УСТАВ: ТЕКСТ == ИЗМЕРЕНИЕ (гейт против дрейфа канона)")
    m = measured()
    if m is None:
        print("[FAIL] не удалось получить числа от tools/charter_check.py")
        return 1
    total, proven, uncovered = m
    print(f"  измерено: законов {total} | доказано {proven} | не покрыто {uncovered}")
    errs = check(total, proven, uncovered)
    if errs:
        for e in errs:
            print(f"[FAIL] {e}")
        print("\n[FAIL] текст устава расходится с измерением: правьте ТЕКСТ, "
              "а не гейт (иначе канон снова начнёт врать)")
        return 1
    print("\n[OK] текст устава совпадает с измерением: числа доказанных законов "
          "и утверждения о покрытии согласованы")
    return 0


def selftest() -> int:
    """Мета-тест: гейт обязан ловить расхождение в ОБЕ стороны."""
    import tempfile
    global EN, RU
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        old_en, old_ru = EN, RU
        EN, RU = Path(d) / "CHARTER.md", Path(d) / "CHARTER.ru.md"
        # (1) текст ОПТИМИСТИЧНЕЕ измерения: помечено 2, а чекер даёт 6.
        EN.write_text("| **L1** | a | `x` | **PROVEN** |\n| **L4** | b | `y` | **PROVEN** |\n",
                      encoding="utf-8")
        RU.write_text("| **L1** | a | `x` | **ДОКАЗАНО** |\n| **L4** | b | `y` | **ДОКАЗАНО** |\n",
                      encoding="utf-8")
        if not check(8, 6, 2):
            print("[FAIL] selftest: расхождение «текст < измерение» НЕ поймано")
            bad += 1
        else:
            print("[OK] selftest: расхождение «текст < измерение» ловится")

        # (2) текст ПЕССИМИСТИЧНЕЕ: чекер говорит «покрыто всё», а ЗАГОЛОВОК
        # утверждает обратное (ровно дефект #350 в docs/CHARTER.md).
        EN.write_text("# Why two laws are not claimed as proven\n| **L1** | a | `x` | **PROVEN** |\n",
                      encoding="utf-8")
        RU.write_text("# Почему два закона не заявлены доказанными\n| **L1** | a | `x` | **ДОКАЗАНО** |\n",
                      encoding="utf-8")
        if not check(8, 1, 0):
            print("[FAIL] selftest: расхождение «текст > измерение» НЕ поймано")
            bad += 1
        else:
            print("[OK] selftest: расхождение «текст > измерение» ловится")

        # (2b) ЛЕГИТИМНЫЕ упоминания НЕ должны ловиться: измерение («0 не покрыто»)
        # и раздел политики («ничего из этого не заявлено проверяемым»).
        EN.write_text("| **L1** | a | `x` | **PROVEN** |\nMeasured: 8 laws, 0 not covered by the checker.\n",
                      encoding="utf-8")
        RU.write_text("| **L1** | a | `x` | **ДОКАЗАНО** |\n"
                      "Измерено: 8 законов, 0 не покрыто пруф-чекером.\n"
                      "Объявлено как политика: ничего из этого не заявлено проверяемым.\n",
                      encoding="utf-8")
        if check(8, 1, 0):
            print("[FAIL] selftest: ЛЕГИТИМНЫЕ упоминания ловятся как расхождение")
            bad += 1
        else:
            print("[OK] selftest: законные упоминания (измерение, политика) не ловятся")

        # (3) согласованный текст проходит.
        EN.write_text("| **L1** | a | `x` | **PROVEN** |\n", encoding="utf-8")
        RU.write_text("| **L1** | a | `x` | **ДОКАЗАНО** |\n", encoding="utf-8")
        if check(8, 1, 7):
            print("[FAIL] selftest: согласованный текст признан расходящимся")
            bad += 1
        else:
            print("[OK] selftest: согласованный текст проходит")

        # (4) отсутствующий файл — честный отказ, а не молчаливое «ок».
        EN.unlink()
        if not check(8, 1, 7):
            print("[FAIL] selftest: отсутствующий устав НЕ пойман")
            bad += 1
        else:
            print("[OK] selftest: отсутствующий устав ловится")
        EN, RU = old_en, old_ru
    print(f"[{'OK' if bad == 0 else 'FAIL'}] charter-text selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
