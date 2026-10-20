# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
"""«ДО» рефакторинга ИИ-агентом: списание без клампа."""


def charge(balance: int, amount: int) -> int:
    """Списывает сумму; при amount > balance баланс уходит в минус."""
    return balance - amount
