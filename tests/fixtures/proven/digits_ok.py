# Контроль: сумма цифр (TheAlgorithms/Python, maths/sum_of_digits.py)
# @kern:requires n >= 0
# @kern:invariant n >= 0 and res >= 0
# @kern:decreases n
def sum_of_digits(n: int) -> int:
    res = 0
    while n > 0:
        res += n % 10
        n //= 10
    return res
