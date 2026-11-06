# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the GNU AGPL-3.0-or-later.
"""CORPUS: buggy. KERN must REFUTE (F) with a counterexample."""


# @kern:requires x >= -1000 and x <= 1000
# @kern:ensures result >= 0 and (result == x or result == -x)
def absolute(x):
    return x
