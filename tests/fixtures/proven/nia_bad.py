# ОТРИЦАТЕЛЬНЫЙ контроль NIA: условие i*i <= n, шаг +2 -> (i+2)^2 <= n НЕ следует
# @kern:requires n >= 1
# @kern:invariant i * i <= n
# @kern:decreases n - i
def sqrt_bad(n: int) -> int:
    i = 0
    while i * i <= n:
        i += 2
    return i
