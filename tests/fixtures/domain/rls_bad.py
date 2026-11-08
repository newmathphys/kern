# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
def can_read(tenant, role):
    # УЯЗВИМО: приоритет AND выше OR — админ ЛЮБОГО тенанта проходит
    return tenant == 1 and role == 0 or role == 1
