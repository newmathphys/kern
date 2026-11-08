# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
def fee(amount, fee_bps):
    # УЯЗВИМО: округление ВНИЗ позволяет дробить сделку и платить 0 комиссии
    return amount * fee_bps // 10000
