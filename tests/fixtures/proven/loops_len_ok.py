# Регрессия #593/#596: инвариант ОБЯЗАН знать, что len(x) >= 0
# @kern:requires 0 <= lo and lo <= len(items)
# @kern:invariant 0 <= lo and lo <= len(items)
# @kern:decreases len(items) - lo
def scan(items: list[int], lo: int) -> int:
    while lo < len(items):
        lo = lo + 1
    return lo
