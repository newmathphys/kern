# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ДВУХУРОВНЕВАЯ ИНДУКЦИЯ (1/4): внешний инвариант СЛЕДУЕТ из внутреннего -> PROVEN
# @kern:requires start >= 2 and end >= start
# @kern:invariant count >= 0
# @kern:decreases end - start
def two_level_ok(sieve: list, start: int, end: int) -> int:
    count = 0
    while start <= end:
        # @kern:invariant count >= 0
        for i in range(start, end + 1):
            count = count + 1
        start += 1
    return count
