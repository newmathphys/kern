# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# TheAlgorithms/Python, maths/number_of_digits.py (while True + break)
# @kern:requires n >= 0
# @kern:invariant n >= 0 and digits >= 0
# @kern:decreases n
def number_of_digits(n: int) -> int:
    digits = 0
    while True:
        n = n // 10
        digits += 1
        if n == 0:
            break
    return digits
