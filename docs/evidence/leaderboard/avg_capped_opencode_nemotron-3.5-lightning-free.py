# @kern:requires a >= 0 and a <= 1000 and b >= 0 and b <= 1000
# @kern:ensures result >= 0 and result <= 500


def avg_capped(a, b):
    return min((a + b) // 2, 500)