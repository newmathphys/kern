# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# НАСТОЯЩАЯ QF_NIA-задача: инвариант с произведением (sqrt-барьер)
# @kern:requires n >= 1
# @kern:invariant i * i <= n and i >= 0
# @kern:decreases n - i * i
def sqrt_steps(n: int) -> int:
    i = 0
    while (i + 1) * (i + 1) <= n:
        i += 1
    return i
