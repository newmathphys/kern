
# @kern:expect-violations  — ДЕМО-ФИКСТУРА: часть контрактов НАМЕРЕННО нарушена,
# поэтому pre-commit её пропускает (см. changed_contract_files).
"""Крайние случаи экстрактора контрактов KERN (проверяется вручную).

Проверяются: детектор ЧИСТОТЫ, отсутствие ложных контрпримеров и обычный PASS.
"""

import random  # noqa: F401  (нужен для проверки детектора чистоты)


# @kern:requires x > 0
# @kern:ensures  result == x
def impure_random(x: int) -> int:
    """НЕЧИСТАЯ: использует генератор случайных чисел -> [IMPURE]."""
    return x + random.randint(0, 0)


# @kern:requires x > 0
# @kern:ensures  result == x
def impure_global(x: int) -> int:
    """НЕЧИСТАЯ: пишет в глобальную переменную -> [IMPURE]."""
    global _COUNTER
    _COUNTER = x
    return x


_COUNTER = 0


# @kern:requires n >= 0
# @kern:ensures  result >= n
def pure_ok(n: int) -> int:
    """ЧИСТАЯ: обычная арифметика -> обязана ДОКАЗАТЬСЯ."""
    return n + n
