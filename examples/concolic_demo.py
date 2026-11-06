# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
def classify(x: int, y: int) -> int:
    if x > 5:
        if y > 3:
            return 1
        return 2
    if x < -5:
        return 3
    return 0
