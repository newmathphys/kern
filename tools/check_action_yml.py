#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`check_action_yml` — БЫСТРЫЙ КОНТРАКТ `action.yml` (без PyYAML и без сети).

ЗАЧЕМ. Гейт `ecosystem-check` импортировал PyYAML внутри heredoc и в окружении
без библиотеки объявлял `action.yml` невалидным — ОТСУТСТВИЕ БИБЛИОТЕКИ
выдавалось за дефект файла (дефект #249).

ЧТО ПРОВЕРЯЕТСЯ. Ровно те утверждения, что и раньше (тег версии, сверка
SHA-256 скачанного артефакта, объявленные входы/выходы), НО обновлённые под
ШАГ 2: Action работает на релизном архиве `kerna-dist`, а обещание
`sarif-file` в режиме `--xray` СНЯТО, потому что измерено: апплаенс принимает
`--sarif` и НЕ создаёт файл (класс #497/#370). Тяжёлое доказательство поведением
(сухой прогон шагов) — в `tools/action_check.py` (`make action-check`); здесь
только дешёвая статика, чтобы `ecosystem-check` оставался быстрым.

Один источник правил: обе проверки используют `action_check.static_contract`,
поэтому «две правды» о контракте не разъезжаются.

Запуск:  python3 tools/check_action_yml.py [путь]
Код возврата: 0 — корректно, 1 — нарушение, 2 — файла нет.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import action_check as ac  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "action.yml"


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT
    if not path.exists():
        print(f"[!] нет {path}")
        return 2
    try:
        doc = ac.parse_action(path.read_text(encoding="utf-8"))
    except ac.YamlError as e:
        print(f"[!] {path.name} не разобран: {e}")
        return 1

    bad = ac.static_contract(doc)
    ver = str(((doc.get("inputs") or {}).get("version") or {}).get("default", ""))
    if not ac.VER_RE.match(ver):
        bad.append(f"inputs.version.default = {ver!r} (ожидался тег vX.Y.Z)")

    for problem in bad:
        print(f"[!] {problem}")
    if bad:
        return 1
    print(f"  [OK] action.yml: version={ver}, composite, sha256-сверка архива, "
          f"выходы {sorted((doc.get('outputs') or {}))}, без ложного SARIF")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
