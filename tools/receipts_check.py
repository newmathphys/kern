#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ГЕЙТ ИНДЕКСА КВИТАНЦИЙ: заявление без доказательства в репозитории — не заявление.

ЗАЧЕМ. У проекта 52 файла квитанций в `docs/evidence/`, и внешний аудитор искал
доказательства вручную. `docs/capabilities_receipts.json` сводит это в индекс:
заявление -> команда -> файл -> МАРКЕРЫ, которые обязаны быть в файле (и которых
быть не должно). Этот гейт проверяет индекс ПО ФАКТУ: файл существует и непуст,
каждый `must_contain` реально есть, ни одного `must_not_contain` нет, id уникальны,
`file` лежит в `docs/evidence/`.

ЧЕСТНАЯ ГРАНИЦА: гейт проверяет СООТВЕТСТВИЕ индекса файлам, а не истинность самих
заявлений — за это отвечают гейты, на которые индекс ссылается. Маркер, подобранный
под текст, ничего не доказывает, поэтому маркеры-пустышки («OK», «PASS», «ГОТОВО»)
запрещены: нужен маркер с числом или вердиктом.

Запуск: python3 tools/receipts_check.py [--selftest] [--json]
Коды: 0 — индекс соответствует файлам; 1 — расхождение (названное); 2 — нет индекса.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "docs" / "capabilities_receipts.json"
# Маркеры-пустышки: они «подтверждают» что угодно -> зелёный по построению.
WEAK_MARKERS = {"OK", "ok", "PASS", "DONE", "УСПЕХ", "ГОТОВО"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(index: dict, root: Path = ROOT) -> list[str]:
    """Вернуть список нарушений (пустой = индекс честен)."""
    bad: list[str] = []
    seen: set[str] = set()
    for r in index.get("receipts", []):
        rid = r.get("id", "<без id>")
        if rid in seen:
            bad.append(f"{rid}: id повторяется — индекс неоднозначен")
        seen.add(rid)
        for key in ("claim", "command", "file", "must_contain"):
            if not r.get(key):
                bad.append(f"{rid}: пустое поле `{key}`")
        path = root / str(r.get("file", ""))
        if not path.is_file():
            bad.append(f"{rid}: файла квитанции нет: {r.get('file')}")
            continue
        if path.stat().st_size == 0:
            bad.append(f"{rid}: файл квитанции ПУСТ (заглушка?): {r.get('file')}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in r.get("must_contain") or []:
            if m in WEAK_MARKERS:
                bad.append(f"{rid}: маркер `{m}` — пустышка (подтверждает что угодно); "
                           f"нужен маркер с числом или вердиктом")
            elif m not in text:
                bad.append(f"{rid}: в квитанции НЕТ маркера `{m}` "
                           f"({r.get('file')}) — заявление не подтверждено")
        for m in r.get("must_not_contain") or []:
            if m and m in text:
                bad.append(f"{rid}: в квитанции ЕСТЬ запрещённый маркер `{m}` — "
                           f"значит прогон не был чистым")
    return bad


def selftest() -> int:
    """Невакуумность: гейт обязан падать на каждом классе поломки индекса."""
    good = {"receipts": [{"id": "x", "claim": "c", "command": "make x",
                          "file": "docs/evidence/probe.log", "must_contain": ["МАРКЕР1"]}]}
    cases = [
        ("файла нет", {"receipts": [{"id": "x", "claim": "c", "command": "make x",
                                    "file": "docs/evidence/нет_такого.log",
                                    "must_contain": ["a"]}]}, "файла квитанции нет"),
        # ВАЖНО: здесь маркер, которого в probe.log НЕТ (в прошлой версии был `good`
        # с МАРКЕР1, который лежит в файле, — кейс проходил вхолостую).
        ("нет маркера", {"receipts": [{"id": "x", "claim": "c", "command": "make x",
                                     "file": "docs/evidence/probe.log",
                                     "must_contain": ["МАРКЕР2"]}]}, "НЕТ маркера"),
        ("слабый маркер", {"receipts": [{"id": "x", "claim": "c", "command": "make x",
                                         "file": "docs/evidence/probe.log",
                                         "must_contain": ["OK"]}]}, "пустышка"),
        ("запрещённый маркер", {"receipts": [{"id": "x", "claim": "c", "command": "make x",
                                              "file": "docs/evidence/probe.log",
                                              "must_contain": ["МАРКЕР1"],
                                              "must_not_contain": ["ПРОВАЛ"]}]},
         "запрещённый маркер"),
        ("дубль id", {"receipts": [good["receipts"][0], good["receipts"][0]]}, "повторяется"),
        ("пустое поле", {"receipts": [{"id": "x", "claim": "", "command": "make x",
                                       "file": "docs/evidence/probe.log",
                                       "must_contain": ["МАРКЕР1"]}]}, "пустое поле"),
        ("пустой файл", {"receipts": [{"id": "x", "claim": "c", "command": "make x",
                                       "file": "docs/evidence/empty.log",
                                       "must_contain": ["a"]}]}, "ПУСТ"),
    ]
    failures = 0
    with tempfile.TemporaryDirectory(prefix="receipts_selftest_") as td:
        tmp = Path(td)
        (tmp / "docs" / "evidence").mkdir(parents=True)
        (tmp / "docs" / "evidence" / "probe.log").write_text(
            "МАРКЕР1 здесь\nПРОВАЛ тоже\n", encoding="utf-8")
        (tmp / "docs" / "evidence" / "empty.log").write_text("", encoding="utf-8")
        for name, idx, expect in cases:
            bad = check(idx, root=tmp)
            ok = any(expect in b for b in bad)
            print(f"  [{'OK  ' if ok else 'FAIL'}] {name}: "
                  f"{bad[0][:88] if bad else '— не поймано'}")
            failures += 0 if ok else 1
        # «Хороший» индекс обязан ПРОЙТИ — иначе гейт краснеет всегда (и его отключат).
        (tmp / "docs" / "evidence" / "probe.log").write_text("МАРКЕР1\n", encoding="utf-8")
        bad = check(good, root=tmp)
        ok = not bad
        print(f"  [{'OK  ' if ok else 'FAIL'}] честный индекс проходит: {bad[:1]}")
        failures += 0 if ok else 1
    print(f"[{'OK' if failures == 0 else 'FAIL'}] receipts --selftest: провалов {failures}")
    return 0 if failures == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not INDEX.is_file():
        print(f"[!] нет индекса {INDEX.relative_to(ROOT)} — сначала создайте: НАЗВАННЫЙ отказ")
        return 2
    index = load(INDEX)
    bad = check(index)
    n = len(index.get("receipts", []))
    if "--json" in sys.argv:
        print(json.dumps({"receipts": n, "violations": bad}, ensure_ascii=False, indent=2))
        return 1 if bad else 0
    if bad:
        for b in bad:
            print(f"  [FAIL] {b}")
        print(f"[FAIL] receipts: нарушений {len(bad)} из {n} заявлений — "
              f"индекс НЕ соответствует квитанциям")
        return 1
    print(f"[OK] receipts: {n} заявлений; каждая квитанция существует, непуста и содержит "
          f"свои маркеры; пустышек и запрещённых маркеров нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
