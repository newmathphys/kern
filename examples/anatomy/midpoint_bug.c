// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
/* ПРАВИЛО (KERN.md):  0 <= low <= high <= 2000000000  ->  low <= result <= high */
int midpoint(int low, int high) {
    return (low + high) / 2;
}
