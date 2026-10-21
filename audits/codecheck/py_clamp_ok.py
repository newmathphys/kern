# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""CORPUS: correct clamp. KERN must PROVE (T)."""


# @kern:requires lo <= hi
# @kern:ensures result >= lo and result <= hi
def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
