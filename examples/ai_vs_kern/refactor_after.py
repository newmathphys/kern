# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""«ПОСЛЕ» рефакторинга ИИ-агентом — с регрессией на границе.

Агент «улучшил» функцию клампом `max(0, …)` и на глаз выглядит безопаснее.
Но поведение изменилось: при `amount > balance` старая версия уходила в минус
(`balance - amount`), новая возвращает 0. Это расхождение — задача `--diff-equiv`.
"""


def charge(balance: int, amount: int) -> int:
    """«Улучшение»: не даём балансу уйти в минус (поведение ИЗМЕНЕНО)."""
    if balance - amount < 0:
        return 0
    return balance - amount
