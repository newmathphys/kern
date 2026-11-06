# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ПУНКТ 38: чит (sys.exit внутри кода) -> R = -2.0
import sys


# @kern:requires x >= 0
# @kern:ensures result >= 0
def hack(x):
    if x > 100:
        sys.exit(0)
    return x
