# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ЭШЕЛОН 5, ПУНКТ 28: гонка двойного списания (`@kern:no_double_spend`).
# Ожидания приёмки (`make double-spend-check`):
#   REFUTED: withdraw_race (обе транзакции проверяют УСТАРЕВШИЙ снимок баланса),
#   PROVEN : withdraw_serial_safe (вторая видит ОБНОВЛЁННЫЙ баланс).


# @kern:no_double_spend
def withdraw_race(balance, a1, a2):
    if a1 > balance:
        return balance
    if a2 > balance:
        return balance - a1
    return balance - a1 - a2


# @kern:no_double_spend
def withdraw_serial_safe(balance, a1, a2):
    if a1 > balance:
        return balance
    if a2 > balance - a1:
        return balance - a1
    return balance - a1 - a2
