# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ЭКСПЕРИМЕНТ #4: эксплойт округления ВНИЗ в комиссии (класс ERC-4626 / Code4rena).

ЗАКОН задаётся аннотацией, а не руками: `@kern:no_arbitrage` означает
    fee(a1) + fee(a2) >= fee(a1 + a2)   для всех a1 > 0, a2 > 0
(дробление платежа не может быть выгоднее целого). Комиссия 0.30%.
"""


# ОКРУГЛЕНИЕ ВНИЗ: 400 -> 1, а 200+200 -> 0. Бесплатный вывод.
# @kern:no_arbitrage
def fee_down(amount):
    return (amount * 30) // 10000


# ОКРУГЛЕНИЕ ВВЕРХ: дробление больше не выгодно.
# @kern:no_arbitrage
def fee_up(amount):
    return (amount * 30 + 9999) // 10000
