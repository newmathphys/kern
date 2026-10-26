"""ЛОВУШКА 1: Contract Tampering (паттерн DeepSeek/GLM).

Файл ЗАПЕЧАТЫВАЕТСЯ как есть (`--lock`). Затем гейт подменяет `requires` на
более узкое (`x > 0` -> `x > 5`), НЕ трогая `ensures` — ровно то, что делали
модели вживую: сужение области определения делает постусловие тривиальным.
`--verify-lock` обязан выдать `[SECURITY] контракт ИЗМЕНЁН`.
"""

# @kern:requires x > 0
# @kern:ensures result == x * 2
def twice(x: int) -> int:
    return x * 2
