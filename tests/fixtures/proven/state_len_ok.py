# Регрессия #596/#597: постусловие с len(x) обязано ДОКАЗЫВАТЬСЯ
# @kern:state_invariant 0 <= result and result <= len(items)
def clamp_index(items: list[int], value: int) -> int:
    if value < 0:
        return 0
    if value > len(items):
        return len(items)
    return value
