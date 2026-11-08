# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
def fee(amount, fee_bps):
    # ИСПРАВЛЕНО: округление ВВЕРХ в пользу пула
    return (amount * fee_bps + 9999) // 10000
