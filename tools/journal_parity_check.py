#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: the RU and EN defect journals must list the SAME defect numbers.

WHY THIS GATE EXISTS (defect #335).

`docs-parity` compares fact ANCHORS in RU/EN pairs; `claims-audit` scans
NUMBERS in documents. Neither looks at whether the English defect journal is
COMPLETE, so an external English-speaking auditor saw 281 records against 295
in Russian and no guard noticed. A defect that exists only in Russian is, for
that reader, a defect that was never recorded - and the journal is the artefact
the project uses as evidence of honesty.

WHAT IS ASSERTED.

  The SET of record numbers in `docs/CAPABILITY_STATUS.md` equals the set in
  `docs/CAPABILITY_STATUS.en.md`.

Both directions are errors: a number only in RU means the external reader is
missing a defect; a number only in EN means the Russian journal is incomplete.

WHAT THIS GATE DOES NOT CLAIM.

It counts NUMBERS, not words. It does not verify translation quality, wording
or completeness of a record's body - a human reviews that. It also does not
demand the records appear in numeric order (the English journal is not ordered).

Measured when the gate was written: 13 records (#294-#308) were RU-only; after
translating them both journals list 307 records.

Запуск:  python3 tools/journal_parity_check.py [--selftest]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RU = ROOT / "docs" / "CAPABILITY_STATUS.md"
EN = ROOT / "docs" / "CAPABILITY_STATUS.en.md"

# Строка записи журнала: `| **312** | ... |` — ровно в начале строки.
RECORD = re.compile(r"^\| \*\*(\d+)\*\*", re.M)


def numbers(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(RECORD.findall(path.read_text(encoding="utf-8", errors="replace")))


def check(ru: Path = RU, en: Path = EN) -> list[str]:
    """Возвращает список расхождений (пустой список = паритет)."""
    if not ru.exists() or not en.exists():
        missing = [p.name for p in (ru, en) if not p.exists()]
        return [f"нет файла журнала: {', '.join(missing)}"]
    r, e = numbers(ru), numbers(en)
    errs: list[str] = []
    only_ru = sorted(r - e, key=int)
    only_en = sorted(e - r, key=int)
    if only_ru:
        errs.append(f"записи только в RU ({len(only_ru)}): {', '.join('#' + n for n in only_ru)} — "
                    f"внешний читатель не видит этих дефектов")
    if only_en:
        errs.append(f"записи только в EN ({len(only_en)}): {', '.join('#' + n for n in only_en)} — "
                    f"русский журнал неполон")
    return errs


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    print("ПАРИТЕТ ЖУРНАЛА ДЕФЕКТОВ (RU == EN)")
    r, e = numbers(RU), numbers(EN)
    print(f"  записей: RU {len(r)} | EN {len(e)} | пересечение {len(r & e)}")
    errs = check()
    if errs:
        for x in errs:
            print(f"[FAIL] {x}")
        print("\n[FAIL] журналы разошлись: переведите недостающие записи "
              "(числа, не формулировки — качество перевода проверяет человек).")
        return 1
    print("\n[OK] журнал един: множество номеров записей в RU и EN совпадает")
    return 0


def selftest() -> int:
    """Мета-тест: гейт обязан ловить расхождение в ОБЕ стороны и не ломаться
    на упорядоченности (EN-журнал не отсортирован — это не ошибка)."""
    import tempfile
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        ru, en = Path(d) / "ru.md", Path(d) / "en.md"
        ru.write_text("| **1** | a |\n| **2** | b |\n", encoding="utf-8")
        en.write_text("| **1** | a |\n| **2** | b |\n", encoding="utf-8")
        if check(ru, en):
            print("[FAIL] selftest: одинаковые журналы признаны расходящимися")
            bad += 1
        else:
            print("[OK] selftest: совпадающие журналы проходят")

        # (1) запись только в RU — внешний читатель её не видит
        en.write_text("| **1** | a |\n", encoding="utf-8")
        if not any("только в RU" in x for x in check(ru, en)):
            print("[FAIL] selftest: запись только в RU НЕ поймана")
            bad += 1
        else:
            print("[OK] selftest: запись только в RU ловится")

        # (2) запись только в EN — русский журнал неполон
        ru.write_text("| **1** | a |\n", encoding="utf-8")
        en.write_text("| **1** | a |\n| **9** | x |\n", encoding="utf-8")
        if not any("только в EN" in x for x in check(ru, en)):
            print("[FAIL] selftest: запись только в EN НЕ поймана")
            bad += 1
        else:
            print("[OK] selftest: запись только в EN ловится")

        # (3) разный ПОРЯДОК — не ошибка (EN-журнал не отсортирован)
        ru.write_text("| **1** | a |\n| **2** | b |\n", encoding="utf-8")
        en.write_text("| **2** | b |\n| **1** | a |\n", encoding="utf-8")
        if check(ru, en):
            print("[FAIL] selftest: разный порядок записей признан расхождением")
            bad += 1
        else:
            print("[OK] selftest: порядок записей не влияет на паритет")

        # (4) отсутствующий файл — честный отказ, а не молчаливое «ок»
        if not check(Path(d) / "nope.md", en):
            print("[FAIL] selftest: отсутствующий журнал НЕ пойман")
            bad += 1
        else:
            print("[OK] selftest: отсутствующий журнал ловится")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] journal-parity selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
