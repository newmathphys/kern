# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the GNU AGPL-3.0-or-later.
"""CORPUS: correct. KERN must PROVE (T) and must NOT accuse."""


# @kern:requires x >= -1000 and x <= 1000
# @kern:ensures result >= 0 and (result == x or result == -x)
def absolute(x):
    if x >= 0:
        return -x
    return -x
