#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Страж лицензионной согласованности (Дефект #222).

ЗАЧЕМ: внешние сканеры (m8ven.ai, GitHub licensee, mcp-каталоги) сверяют
поле `license` в манифестах с реальным файлом `LICENSE`. Расхождение —
это либо штраф в рейтинге, либо ложное обещание пользователю (дефект #222:
в дереве репозитория `LICENSE` был помечен как `MIT`).

ЧТО ПРОВЕРЯЕТСЯ:
  1) `LICENSE` действительно содержит «PolyForm Noncommercial»;
  2) `server.json`, `.well-known/mcp.json`, `CITATION.cff` объявляют
     идентификатор `PolyForm-Noncommercial-1.0.0`;
  3) в `README.md` / `README.ru.md` строка про `LICENSE` НЕ обещает MIT;
  4) в JSON-манифестах нет посторонних лицензий (MIT/Apache).

Выход: 0 — согласовано; 1 — расхождение (печатается, что именно).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_ID = "PolyForm-Noncommercial-1.0.0"
EXPECTED_WORDS = "PolyForm Noncommercial"
JSON_MANIFESTS = ("server.json", ".well-known/mcp.json")
TEXT_MANIFESTS = ("CITATION.cff",)
READMES = ("README.md", "README.ru.md")


def main() -> int:
    bad: list[str] = []

    lic = ROOT / "LICENSE"
    if not lic.is_file():
        print("[FAIL] LICENSE отсутствует")
        return 1
    if EXPECTED_WORDS not in lic.read_text(encoding="utf-8", errors="replace"):
        bad.append(f"LICENSE не содержит «{EXPECTED_WORDS}»")

    for name in JSON_MANIFESTS:
        p = ROOT / name
        if not p.is_file():
            bad.append(f"{name}: файла нет")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            bad.append(f"{name}: невалидный JSON ({exc})")
            continue
        got = data.get("license")
        if got != EXPECTED_ID:
            bad.append(f"{name}: license={got!r}, ожидалось {EXPECTED_ID!r}")

    for name in TEXT_MANIFESTS:
        p = ROOT / name
        if not p.is_file():
            bad.append(f"{name}: файла нет")
            continue
        if EXPECTED_ID not in p.read_text(encoding="utf-8", errors="replace"):
            bad.append(f"{name}: нет идентификатора {EXPECTED_ID}")

    # Ловушка #222: «LICENSE ... MIT» в дереве репозитория (LIMITATIONS не в счёт).
    for name in READMES:
        p = ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "LICENSE" in line and re.search(r"\bMIT\b", line) and "LIMITATION" not in line.upper():
                bad.append(f"{name}: строка обещает MIT у LICENSE -> {line.strip()[:60]}")

    if bad:
        for msg in bad:
            print(f"  [FAIL] {msg}")
        print("[FAIL] лицензия несогласована (см. выше)")
        return 1
    print(f"[OK] лицензия согласована: LICENSE + манифесты = {EXPECTED_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
