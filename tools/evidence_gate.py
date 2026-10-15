#!/usr/bin/env python3
"""Жёсткий гейт на свидетельства: ни один опубликованный лог не должен
заканчиваться ненулевым кодом возврата.

ЗАЧЕМ. Каталог `docs/evidence/` — это то, что аудитор открывает первым. Если
там лежит лог с `RC=1`, значит проект публикует провал рядом с заявлением об
успехе. Ровно так и было: 8 логов оказались снимком ПРОМЕЖУТОЧНОГО состояния
(во время пробы canfail и в грязном дереве).

ПОЧЕМУ НЕ ПРОСТО grep. Наивный `grep -rn "RC=1|FAIL|ОШИБКА"` даёт ложные
срабатывания: в `canfail.log` строки `[FAIL]` — это НАМЕРЕННЫЕ негативные пробы
(харнесс обязан покраснеть), а в логах атак слово `error` встречается как
ожидаемый вывод ядра. Поэтому гейт смотрит на ФИНАЛЬНУЮ строку `RC=<n>`
каждого лога — она пишется сборщиком последней и отражает вердикт целиком.

ИСКЛЮЧЕНИЕ. `canfail.log` — единственный лог, где ненулевые коды ВНУТРИ
являются частью доказательства. Для него проверяется, что итоговая строка
содержит «ВАКУУМНЫХ 0», то есть ни одна проверка не оказалась вакуумной.

Запуск:  python3 tools/evidence_gate.py
Код возврата: 0 — все свидетельства чистые, 1 — найдены нарушения.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "docs" / "evidence"

# Логи, внутри которых ненулевые коды — часть доказательства.
# Для них проверяется СМЫСЛОВОЙ инвариант, а не код возврата файла.
INTENTIONAL = {
    "canfail.log": (r"ВАКУУМНЫХ\s+(\d+)", 0,
                    "число вакуумных проверок должно быть 0"),
}


def main() -> int:
    if not EV.is_dir():
        print(f"[!] нет каталога {EV}")
        return 1

    logs = sorted(EV.glob("*.log"))
    if not logs:
        print("[!] в docs/evidence/ нет .log файлов")
        return 1

    problems: list[str] = []
    checked = 0
    for p in logs:
        name = p.name
        text = p.read_text(encoding="utf-8", errors="replace")
        checked += 1

        # Финальный код возврата: последняя строка вида RC=<n>
        codes = re.findall(r"^RC=(\d+)\s*$", text, re.M)
        if not codes:
            problems.append(f"{name}: НЕТ финальной строки RC=<n> "
                            f"(лог неполный или снят вручную)")
            continue
        rc = codes[-1]

        if name in INTENTIONAL:
            pat, want, why = INTENTIONAL[name]
            m = re.search(pat, text)
            if not m:
                problems.append(f"{name}: не найден инвариант ({why})")
            elif int(m.group(1)) != want:
                problems.append(f"{name}: {why} — найдено {m.group(1)}")
            continue

        if rc != "0":
            # подсказать первую явную ошибку
            hint = ""
            for line in text.splitlines():
                if re.search(r"error:|ОШИБКА|ПРОВАЛ|failure", line):
                    hint = f"  первая ошибка: {line.strip()[:90]}"
                    break
            problems.append(f"{name}: RC={rc}{chr(10)}{hint}" if hint
                            else f"{name}: RC={rc}")

    print(f"СВИДЕТЕЛЬСТВА: проверено {checked} логов в docs/evidence/")
    if problems:
        print("НАРУШЕНИЯ:")
        for pr in problems:
            print(f"  - {pr}")
        print("\nИНВАРИАНТ: каждый опубликованный лог обязан заканчиваться RC=0")
        return 1
    print("ВСЕ ЧИСТЫЕ: ни одного лога с RC!=0; canfail.log — 0 вакуумных")
    return 0


if __name__ == "__main__":
    sys.exit(main())
