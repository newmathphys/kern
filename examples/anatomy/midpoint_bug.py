# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ПРАВИЛО (KERN.md):
#   на входе  0 <= low <= high <= 2000000000
#   на выходе low <= result <= high
# @kern:requires 0 <= low and low <= high and high <= 2000000000
# @kern:ensures low <= result and result <= high
def midpoint(low: int, high: int) -> int:
    return (low + high) // 2
