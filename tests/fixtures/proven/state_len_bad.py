# Регрессия #596: нарушение постусловия обязано быть ПОЙМАНО
# @kern:state_invariant result <= 0
def grow(value: int) -> int:
    return value + 1
