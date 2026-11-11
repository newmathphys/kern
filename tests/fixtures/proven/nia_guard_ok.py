# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# Нелинейное условие (как next_prime_number): factor * factor <= number
# @kern:requires factor >= 5 and number >= 0
# @kern:invariant factor >= 5
# @kern:decreases number - factor
def count_steps(number: int, factor: int) -> int:
    cnt = 0
    while factor * factor <= number:
        factor += 6
        cnt += 1
    return cnt
