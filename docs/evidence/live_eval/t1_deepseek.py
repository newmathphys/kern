# @kern:requires a >= 0 and b >= 0 and a <= 1000 and b <= 1000
# @kern:ensures result >= 0 and result <= 1000
def saturate_add(a: int, b: int) -> int:
    return min(a + b, 1000)
