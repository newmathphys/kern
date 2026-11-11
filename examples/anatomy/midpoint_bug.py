# ПРАВИЛО (KERN.md):
#   на входе  0 <= low <= high <= 2000000000
#   на выходе low <= result <= high
# @kern:requires 0 <= low and low <= high and high <= 2000000000
# @kern:ensures low <= result and result <= high
def midpoint(low: int, high: int) -> int:
    return (low + high) // 2
