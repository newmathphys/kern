# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# try с НЕТРИВИАЛЬНЫМ обработчиком -> должен быть именованный отказ
# @kern:invariant 0 <= i
def try_bad(n: int, i: int) -> int:
    s = 0
    while i < n:
        try:
            s += 1
        except ValueError:
            s += 2
            i += 5
        i += 1
    return s
