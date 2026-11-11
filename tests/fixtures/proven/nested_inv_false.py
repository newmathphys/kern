# ДВУХУРОВНЕВАЯ ИНДУКЦИЯ (3/4): ЛОЖНЫЙ внутренний инвариант -> FAIL на init
# @kern:requires start >= 2 and end >= start
# @kern:invariant count >= 0
# @kern:decreases end - start
def two_level_false_inv(sieve: list, start: int, end: int) -> int:
    count = 0
    while start <= end:
        # @kern:invariant count >= 5
        for i in range(start, end + 1):
            count = count + 1
        start += 1
    return count
