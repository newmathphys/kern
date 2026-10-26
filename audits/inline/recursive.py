"""ШАГ 1, ТЕСТ 4 (ПРЯМАЯ РЕКУРСИЯ) — ПРАВИЛО 2.

`fact` вызывает себя. Стек вызовов обязан остановить развёртку и откатиться к
`_havoc`. ОБЯЗАНО: НЕ падать и НЕ объявлять нарушение.
"""


def fact(n: int) -> int:
    if n <= 1:
        return 1
    return n * fact(n - 1)


# @kern:requires n >= 0
# @kern:ensures result >= 1
def caller(n: int) -> int:
    return fact(n)
