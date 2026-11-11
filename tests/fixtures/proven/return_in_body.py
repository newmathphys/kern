# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# TheAlgorithms/Python, maths/two_pointer.py (ветви в теле + ранний return)
# @kern:requires 0 <= i and i <= j
# @kern:invariant 0 <= i and i <= j + 1
# @kern:decreases j - i
def two_sum(nums: list[int], target: int, i: int, j: int) -> int:
    while i < j:
        if nums[i] + nums[j] == target:
            return i
        elif nums[i] + nums[j] < target:
            i = i + 1
        else:
            j = j - 1
    return -1
