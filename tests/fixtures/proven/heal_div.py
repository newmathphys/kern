# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# Двусторонний контроль --heal: путь деления на ноль ЕСТЬ -> патч с raise
# @kern:requires volume != 0
def rate(moles: int, volume: int) -> int:
    return moles // volume
