#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""#633: ПРОВЕРКА БЕЗ ВЫЗОВА — ТА ЖЕ ЛОЖЬ, ЧТО И ЕЁ ОТСУТСТВИЕ.

ЗАЧЕМ. ИЗМЕРЕНО: из 151 проверочной цели Makefile (`*-check`, `*-test`,
`*-selftest`) — **115 не вызываются НИ из `ci-fast`, НИ из `tools/ci.sh`**.
Именно так `xray-check` годами «проходил»: он был в Makefile, но не в конвейере,
а его красное состояние (слепой детектор `buf[i-1]`) никто не видел (#632).

ПРАВИЛО (базовая линия, как у исключений в лицензионном гейте): список уже
осиротевших целей ЗАФИКСИРОВАН в `docs/orphan_gates.baseline.json`. Гейт падает,
если появляется НОВАЯ осиротевшая цель: значит кто-то добавил проверку и не
подключил её. Снимать цель с учёта можно только через `--update-baseline`
(осознанное действие, видно в диффе).

Использование:
    python3 tools/orphan_gates_check.py                # проверка (rc=1 при новой сироте)
    python3 tools/orphan_gates_check.py --update-baseline
    python3 tools/orphan_gates_check.py --list          # показать всех осиротевших
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "docs" / "orphan_gates.baseline.json"
CHECK_SUFFIX = ("-check", "-selftest", "selftest", "-test")


def _targets() -> set[str]:
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"^([a-z0-9][a-z0-9-]*(?:-check|-test|-selftest|selftest)):",
                          mk, re.M))


def _wired() -> str:
    ci = (ROOT / "tools" / "ci.sh").read_text(encoding="utf-8")
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    m = re.search(r"^ci-fast:.*?(?=\n\w[\w.-]*:)", mk, re.S | re.M)
    return ci + "\n" + (m.group(0) if m else "")


def orphans() -> list[str]:
    wired = _wired()
    return sorted(t for t in _targets() if t not in wired)


def main() -> int:
    cur = orphans()
    if "--list" in sys.argv:
        for t in cur:
            print(t)
        print(f"# всего осиротевших: {len(cur)}")
        return 0
    if "--update-baseline" in sys.argv:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps({"orphans": cur}, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
        print(f"[OK] базовая линия обновлена: {len(cur)} осиротевших целей")
        return 0
    if not BASELINE.is_file():
        print(f"[FAIL] нет базовой линии {BASELINE.name} — создайте: --update-baseline")
        return 1
    base = set(json.loads(BASELINE.read_text(encoding="utf-8")).get("orphans", []))
    new = sorted(set(cur) - base)
    fixed = sorted(base - set(cur))
    print(f"[i] осиротевших сейчас: {len(cur)} | в базовой линии: {len(base)}")
    if fixed:
        print(f"[i] подключены к конвейеру с прошлого раза: {len(fixed)} ({', '.join(fixed[:5])})")
    if new:
        print("[FAIL] #633: НОВЫЕ проверки НЕ ПОДКЛЮЧЕНЫ к ci-fast/ci.sh:")
        for t in new[:10]:
            print(f"    {t}")
        print("  Либо подключите цель, либо зафиксируйте осознанно: --update-baseline")
        return 1
    print("[OK] #633: новых осиротевших проверок нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
