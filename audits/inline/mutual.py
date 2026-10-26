"""ШАГ 1, ТЕСТ 5 (ВЗАИМНАЯ РЕКУРСИЯ) — ПРАВИЛО 2, вторая половина.

`even` зовёт `odd`, `odd` зовёт `even`. Стек обязан остановить это.
ОБЯЗАНО: НЕ падать и НЕ объявлять нарушение.
"""


def even(n: int) -> int:
    if n == 0:
        return 1
    return odd(n - 1)


def odd(n: int) -> int:
    if n == 0:
        return 0
    return even(n - 1)


# @kern:requires n >= 0
# @kern:ensures result >= 0
def caller(n: int) -> int:
    return even(n)
