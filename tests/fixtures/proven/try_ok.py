# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# try с тривиальным обработчиком (звукое подмножество)
# @kern:requires 0 <= i and i <= n
# @kern:invariant 0 <= i and i <= n
# @kern:decreases n - i
def try_ok(n: int, i: int) -> int:
    s = 0
    while i < n:
        try:
            s += 1
        except ValueError:
            pass
        i += 1
    return s
