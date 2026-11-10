# Вложенный цикл МЕНЯЕТ переменную инварианта (cnt) -> обязан быть SKIP
# @kern:requires start >= 2 and end >= start
# @kern:invariant cnt >= 0 and start >= 2
# @kern:decreases end - start
def nested_bad(sieve: list, start: int, end: int) -> int:
    cnt = 0
    while start <= end:
        for i in range(start, end + 1):
            cnt += 1
        start += 1
    return cnt
