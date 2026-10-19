# Классический баг Джошуа Блоха (2006): переполнение в бинарном поиске.
# mid = (low + high) // 2 переполняет i32 при low + high >= 2**31.
# @kern:int32
# @kern:requires low >= 0 and high >= 0 and low <= 2147483647 and high <= 2147483647
# @kern:ensures 0 <= result and result <= 2147483647
def mid_buggy(low: int, high: int) -> int:
    return (low + high) // 2

# @kern:int32
# @kern:requires low >= 0 and high >= 0 and low <= high and high <= 2147483647
# @kern:ensures 0 <= result and result <= 2147483647
def mid_safe(low: int, high: int) -> int:
    return low + (high - low) // 2
