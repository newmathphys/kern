# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# Регрессия #593/#596: инвариант ОБЯЗАН знать, что len(x) >= 0
# @kern:requires 0 <= lo and lo <= len(items)
# @kern:invariant 0 <= lo and lo <= len(items)
# @kern:decreases len(items) - lo
def scan(items: list[int], lo: int) -> int:
    while lo < len(items):
        lo = lo + 1
    return lo
