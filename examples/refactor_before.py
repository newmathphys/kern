# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Фикстура KERN для `--diff-equiv` (УЛУЧШЕНИЕ №3): исходник ДО рефакторинга.

Пара с `refactor_after.py` образует РАСХОДЯЩИЙСЯ рефакторинг: та же функция
`charge`, но знак операции перепутан. Цель `make diff-equiv` обязана это
поймать и вернуть `[DIVERGED]` + контрпример Z3.
"""


def charge(balance: int, amount: int) -> int:
    """Списание: уменьшает баланс."""
    return balance - amount
