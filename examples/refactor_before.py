"""Фикстура KERN для `--diff-equiv` (УЛУЧШЕНИЕ №3): исходник ДО рефакторинга.

Пара с `refactor_after.py` образует РАСХОДЯЩИЙСЯ рефакторинг: та же функция
`charge`, но знак операции перепутан. Цель `make diff-equiv` обязана это
поймать и вернуть `[DIVERGED]` + контрпример Z3.
"""


def charge(balance: int, amount: int) -> int:
    """Списание: уменьшает баланс."""
    return balance - amount
