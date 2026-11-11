# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
def clamp(x: int) -> int:
    if x < 0:
        return 0
    if x > 10:
        return 10
    return x
