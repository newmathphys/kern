"""ЛОВУШКА 2: Vacuous Precondition — ПРОТИВОРЕЧИВОЕ предусловие.

`x > 10 and x < 5` невыполнимо, поэтому постусловие истинно ТРИВИАЛЬНО (пустой
домен). Это не доказательство корректности, а его имитация. Обязан быть
маркер `[VACUOUS]`, а НЕ `PROVEN`.
"""

# @kern:requires x > 10 and x < 5
# @kern:ensures result == x * 2
def vac(x: int) -> int:
    return x * 2
