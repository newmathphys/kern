# Вложенный цикл, который НЕ трогает переменные контракта (sieve, i) -> доказуем
# @kern:requires start >= 2 and end >= start
# @kern:invariant start >= 2
# @kern:decreases end - start
def sieve_outer(sieve: list, start: int, end: int) -> int:
    cnt = 0
    while start <= end:
        for i in range(start * start, end + 1, start):
            sieve[i] = False
        start += 1
        cnt += 1
    return cnt
