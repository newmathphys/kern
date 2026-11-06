// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
/// @kern:ensures result >= 0
pub fn addSat(a: u32, b: u32) u32 {
    return a +| b;
}
