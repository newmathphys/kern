# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# @kern:expect-violations — ДЕМО-ФИКСТУРА: дыры НАМЕРЕННЫЕ (стенд `make ai-demo`).
"""Модуль, «сгенерированный ИИ-агентом» по заданию: перевод с комиссией.

Агент отчитался «готово, тесты зелёные» (см. `test_ai_generated.py`).
Внутри — две классические дыры генерации:

  1) на отрицательной сумме баланс не уменьшается, а РАСТЁТ
     (`-(-50) = +50`, плюс комиссия со знаком минус);
  2) контракт, который агент написал сам, слабее его же обещания:
     `requires balance >= 0` вместо `balance >= amount`.
"""


# @kern:requires balance >= 0
# @kern:ensures  result >= 0 and result < balance
def transfer_with_fee(balance: int, amount: int) -> int:
    """Перевод с комиссией 1% (как «написал ИИ»)."""
    return balance - amount - amount // 100


# @kern:requires balance >= 0
# @kern:ensures  result < balance
def transfer_no_fee(balance: int, amount: int) -> int:
    """ДЫРА: нет проверки знака — отрицательная сумма УВЕЛИЧИВАЕТ баланс."""
    return balance - amount
