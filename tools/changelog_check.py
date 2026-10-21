#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: версия в коде обязана иметь раздел в CHANGELOG (шаг 0K.8).

ЗАЧЕМ. `src/main.zig` — источник версии для `kernc --version`, README,
`server.json` и релизного workflow. CHANGELOG жил отдельно и отставал:
в нём не было записи `2.5.2`, хотя релиз опубликован. Гейт связывает одно
с другим: подняли версию — обязаны описать, что изменилось.

Запуск: python3 tools/changelog_check.py [--path CHANGELOG.md]
Код возврата: 0 — раздел есть; 1 — нет; 2 — не найден источник версии.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "main.zig"
CHANGELOG = ROOT / "CHANGELOG.md"


def current_version() -> str:
    m = re.search(r'KERN_VERSION\s*=\s*"v?([0-9]+\.[0-9]+\.[0-9]+)"',
                  SRC.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Версия из src/main.zig есть в CHANGELOG")
    ap.add_argument("--path", type=Path, default=CHANGELOG)
    args = ap.parse_args()

    ver = current_version()
    if not ver:
        print(f"[FAIL] не нашёл KERN_VERSION в {SRC}")
        return 2
    if not args.path.exists():
        print(f"[FAIL] нет {args.path}")
        return 1

    text = args.path.read_text(encoding="utf-8", errors="replace")
    has = re.search(rf"^##\s*\[{re.escape(ver)}\]", text, re.M) is not None
    if not has:
        print(f"[FAIL] в {args.path.name} нет раздела «## [{ver}]» — "
              f"релиз {ver} не описан")
        return 1
    print(f"[OK] {args.path.name}: раздел [{ver}] на месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())
