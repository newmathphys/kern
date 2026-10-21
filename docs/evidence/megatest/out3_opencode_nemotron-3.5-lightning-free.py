# @kern:requires x >= -1000 and x <= 1000
# @kern:ensures result >= 0 and result <= 100
def abs_capped(x: int) -> int:
    return min(abs(x), 100)