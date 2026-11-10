# @kern:requires x >= 0 and y > 0
# @kern:invariant x >= 0 and y >= 0
# @kern:decreases y
def gcd_by_iterative(x: int, y: int) -> int:
    while y:
        x, y = y, x % y
    return abs(x)
