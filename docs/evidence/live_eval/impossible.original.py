# @kern:requires x >= 0 and x <= 5
# @kern:ensures result == x + 1 and result >= 10
def impossible(x: int) -> int:
    return x + 1
