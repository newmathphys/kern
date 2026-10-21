# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""CORPUS boundary: multiplication is nonlinear. Expected verdict: N (UNKNOWN),
never F: KERN's LIA fragment cannot decide it, and "cannot decide" is not "bug"."""


# @kern:requires x >= 0 and x <= 100
# @kern:ensures result == x * x
def square(x):
    return x * x
