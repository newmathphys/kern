# TheAlgorithms/Python, maths/binary_exponentiation.py (цикл с exponent >>= 1)
# @kern:requires base >= 0
# @kern:invariant exponent >= 0
# @kern:decreases exponent
def bin_pow(base: int, exponent: int) -> int:
    res = 1
    while exponent > 0:
        if exponent & 1:
            res *= base
        base *= base
        exponent >>= 1
    return res
