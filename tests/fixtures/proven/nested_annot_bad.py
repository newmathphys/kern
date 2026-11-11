# ДВУХУРОВНЕВАЯ ИНДУКЦИЯ (2/4): внешний инвариант НЕ следует из внутреннего -> FAIL
# требует count <= 5, а внутренний гарантирует только count >= 0
# @kern:requires start >= 2 and end >= start
# @kern:invariant count >= 0 and count <= 5
# @kern:decreases end - start
def two_level_bad(sieve: list, start: int, end: int) -> int:
    count = 0
    while start <= end:
        # @kern:invariant count >= 0
        for i in range(start, end + 1):
            count = count + 1
        start += 1
    return count
