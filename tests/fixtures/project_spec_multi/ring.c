// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
int array_write_hit(int *buf, int idx, int val) {
    buf[idx] = val;
    return buf[idx];
}
