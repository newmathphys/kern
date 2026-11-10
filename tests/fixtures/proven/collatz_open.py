# ПРОВЕРКА ЗВУЧНОСТИ: остановка Коллатца — ОТКРЫТАЯ ПРОБЛЕМА.
# Если KERN заявит PROVEN по `decreases n` — это ЛОЖНОЕ ДОКАЗАТЕЛЬСТВО.
# @kern:requires n >= 1
# @kern:invariant n >= 1
# @kern:decreases n
def collatz_len(n: int) -> int:
    steps = 0
    while n != 1:
        if n % 2 == 0:
            n = n // 2
        else:
            n = 3 * n + 1
        steps = steps + 1
    return steps
