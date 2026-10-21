# @kern:expect-violations  — демо: advisory-нарушение не блокирует гейт (Ф6.1)
"""Классы обязательств KERN: `hard` (по умолчанию) и `advisory`.

`advisory` — это НЕ ослабление контракта: обещание остаётся записанным и
проверяется. Меняется только реакция на нарушение: вердикт `T_advisory`
(не блокирует), который НЕЛЬЗЯ складывать со счётчиком доказанного `T`.
Класс входит в отпечаток замка, поэтому переклейка `hard -> advisory`
без обновления `contracts.lock.json` ломает `make contracts-lock-check`.
"""


# @kern:ensures result == x + y
def add_hard(x: int, y: int) -> int:
    """HARD: доказано."""
    return x + y


# @kern:ensures result >= x + y  [advisory]
def add_advisory_violated(x: int, y: int) -> int:
    """ADVISORY: нарушено, но не блокирует — вердикт T_advisory."""
    return x + y - 1
