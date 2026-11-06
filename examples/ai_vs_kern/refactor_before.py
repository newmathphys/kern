# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""«ДО» рефакторинга ИИ-агентом: списание без клампа."""


def charge(balance: int, amount: int) -> int:
    """Списывает сумму; при amount > balance баланс уходит в минус."""
    return balance - amount
