# ДВУХУРОВНЕВАЯ ИНДУКЦИЯ (4/4): вложенный while БЕЗ decreases -> FAIL
# @kern:requires start >= 2 and end >= start and j >= 0
# @kern:invariant count >= 0
# @kern:decreases end - start
def two_level_nodecr(start: int, end: int, j: int) -> int:
    count = 0
    while start <= end:
        # @kern:invariant j >= 0
        while j > 0:
            j = j - 1
        count = count + 1
        start += 1
    return count
