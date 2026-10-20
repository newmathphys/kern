# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
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
