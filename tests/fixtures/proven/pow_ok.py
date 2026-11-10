# Реальная форма: factor ** 2 <= n (аналог next_prime_number)
# @kern:requires factor >= 5 and n >= 0
# @kern:invariant factor >= 5
# @kern:decreases n - factor
def count_pow(n: int, factor: int) -> int:
    cnt = 0
    while factor ** 2 <= n:
        factor += 6
        cnt += 1
    return cnt
