# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# @kern:requires x >= 0 and y > 0
# @kern:invariant x >= 0 and y >= 0
# @kern:decreases y
def gcd_by_iterative(x: int, y: int) -> int:
    while y:
        x, y = y, x % y
    return abs(x)
