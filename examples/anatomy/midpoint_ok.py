# @kern:requires 0 <= low and low <= high and high <= 2000000000
# @kern:ensures low <= result and result <= high
def midpoint(low: int, high: int) -> int:
    return low + (high - low) // 2
