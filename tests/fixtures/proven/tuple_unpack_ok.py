# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ВАШ проект: ~/ai_lab/rii/knowledge/methods.py (копия, оригинал не тронут)
from collections.abc import Callable

# @kern:requires n >= 1
# @kern:invariant 0 <= low and low <= high + 1 and high <= n - 1
# @kern:decreases high - low
def line_repair_search(n: int, faulty: Callable[[int], bool]) -> int:
    """Находит первую точку, где faulty(i) истинно (монотонность)."""
    low, high = 0, n - 1
    result = -1
    while low <= high:
        mid = (low + high) // 2
        if faulty(mid):
            result = mid
            high = mid - 1
        else:
            low = mid + 1
    return result
