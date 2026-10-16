"""Демонстрация контрактов KERN прямо в Python-коде.

Никакого SMT-LIB2: контракт — это комментарий рядом с функцией.
Проверка: python3 tools/kern_contracts.py examples/contracts_demo.py
"""


# @kern:requires amount > 0 and balance >= amount
# @kern:ensures  result == balance - amount and result < balance
def withdraw(balance: int, amount: int) -> int:
    """КОРРЕКТНАЯ функция: контракт обязан ДОКАЗАТЬСЯ."""
    return balance - amount


# @kern:requires amount > 0 and balance >= amount
# @kern:ensures  result == balance - amount and result < balance
def withdraw_buggy(balance: int, amount: int) -> int:
    """БАГ: перепутан знак — списание УВЕЛИЧИВАЕТ баланс.

    Тот же контракт, что у `withdraw`, но тело `+` вместо `-`.
    Контракт обязан НАРУШИТЬСЯ (Z3 предъявит контрпример).
    """
    return balance + amount


# @kern:requires 0 <= k and 0 <= x
# @kern:ensures  result == 3 * x
def triple(x: int, k: int) -> int:
    """Линейное умножение на литерал — тоже в подмножестве."""
    return 3 * x


# @kern:requires n >= 0
# @kern:ensures  result >= 0
def sum_to_n(n: int) -> int:
    """ВНЕ подмножества: цикл. Должна быть честно помечена SKIP."""
    total = 0
    for i in range(n):
        total = total + i
    return total
