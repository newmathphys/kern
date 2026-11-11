# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
def gcd(a: int, b: int) -> int:
    while b != 0:
        r = a % b
        a = b
        b = r
    return abs(a)
