# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# Регрессия #596: нарушение постусловия обязано быть ПОЙМАНО
# @kern:state_invariant result <= 0
def grow(value: int) -> int:
    return value + 1
