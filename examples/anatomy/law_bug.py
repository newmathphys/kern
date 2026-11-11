# На входе: 0 <= low и low <= high
# На выходе: low <= result <= high
# @kern:requires 0 <= low and low <= high
# @kern:ensures low <= result and result <= high
def midpoint(low: int, high: int) -> int:
    return (low + high) // 2
