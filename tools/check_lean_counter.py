#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Страж счётчика теорем Lean 4 (Дефект #223).

ЗАЧЕМ: витрина (`docs/index.html`, `README.md`, `README.ru.md`) обещает число
теорем Lean 4. Число это РАСТЁТ при каждой новой лемме, а витрина обновляется
руками — и отстаёт. Обнаружено на практике: сайт полгода показывал
«120 Lean 4 theorems» при фактических 137 (дефект #223).

ЧТО ПРОВЕРЯЕТСЯ: каждое число, стоящее непосредственно перед «Lean»/«theorems»/
«теорем» в этих трёх файлах, обязано равняться фактическому числу
`theorem`-строк в `formal/*.lean`.

Выход: 0 — согласовано; 1 — расхождение.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (файл, регулярное выражение с группой 1 = число)
TARGETS = (
    ("docs/index.html", r"(\d+)\s+Lean"),
    ("README.md", r"(\d+)\s+theorems"),
    ("README.ru.md", r"(\d+)\s+теорем"),
)

# Исключения (иначе — ложные тревоги, а не сигнал):
#   «Lean 4 theorems» — это ВЕРСИЯ Lean, а не счётчик;
#   строка со ссылкой на конкретный `.lean`-файл — это счётчик ЭТОГО файла
#   (например, «KernSemanticGap.lean: 8 теорем»), а не итог.
SKIP_BEFORE = "Lean"   # «Lean 4 theorems» — версия, а не счётчик
SKIP_LINE_MARK = ".lean"


def main() -> int:
    formal = sorted((ROOT / "formal").glob("*.lean"))
    actual = sum(
        1
        for f in formal
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith("theorem ")
    )
    if actual == 0:
        print("[FAIL] в formal/*.lean не найдено ни одной теоремы")
        return 1

    bad: list[str] = []
    checked = 0
    for name, pattern in TARGETS:
        p = ROOT / name
        if not p.is_file():
            bad.append(f"{name}: файла нет")
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if SKIP_LINE_MARK in line:
                continue          # счётчик конкретного файла, не итог
            for m in re.finditer(pattern, line):
                before = line[max(0, m.start() - 12):m.start()].rstrip()
                if before.endswith(SKIP_BEFORE):
                    continue      # «Lean 4 theorems» = версия
                checked += 1
                got = int(m.group(1))
                if got != actual:
                    bad.append(f"{name}: «{m.group(0).strip()}» — факт {actual}")

    if bad:
        for msg in bad:
            print(f"  [FAIL] {msg}")
        print("[FAIL] счётчик теорем Lean 4 на витрине отстал от formal/*.lean")
        return 1
    print(f"[OK] теорем Lean 4: {actual} — витрина совпадает ({checked} вхождений)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
