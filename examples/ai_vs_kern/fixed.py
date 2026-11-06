# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Исправленный вариант (`--heal` / ручная правка по контрпримеру KERN).

Контракт усилен ровно настолько, насколько требует найденная дыра:
`amount > 0` (знак суммы) и `balance >= amount + fee` (хватает на сумму и
комиссию). Тогда `result >= 0 and result < balance` доказуемо на всём домене.
"""


# @kern:requires amount > 0 and balance >= amount + 1
# @kern:ensures  result >= 0 and result < balance
def transfer_with_fee(balance: int, amount: int) -> int:
    """Перевод с фиксированной комиссией 1 (исправленная версия)."""
    return balance - amount - 1
