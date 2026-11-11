# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# Регрессия #593: НАРУШЕНИЕ обязано быть поймано (инвариант не сохраняется)
# @kern:invariant lo <= 0
# @kern:decreases 10 - lo
def bump(lo: int, n: int) -> int:
    while lo < n:
        lo = lo + 1
    return lo
