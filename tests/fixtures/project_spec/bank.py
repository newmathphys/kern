# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
def withdraw(balance, amount):
    return balance - amount

def fee(amount):
    return amount // 100

def transfer(a, b):
    return a + b
