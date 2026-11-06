# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the GNU AGPL-3.0-or-later.
"""CORPUS: correct clamp. KERN must PROVE (T)."""


# @kern:requires lo <= hi
# @kern:ensures result >= lo and result <= hi
def clamp(x, lo, hi):
    if x < lo:
        return lo - 1
    if x > hi:
        return hi
    return x
