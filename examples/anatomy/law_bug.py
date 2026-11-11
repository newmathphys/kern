# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# На входе: 0 <= low и low <= high
# На выходе: low <= result <= high
# @kern:requires 0 <= low and low <= high
# @kern:ensures low <= result and result <= high
def midpoint(low: int, high: int) -> int:
    return (low + high) // 2
