// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// ОГРАНИЧЕНИЕ экстрактора: «хвостовое выражение» Rust (`a.saturating_add(b)`
// без return) вне подмножества — требуется явный `return`.
/// @kern:ensures result >= 0
pub fn add_sat(a: u32, b: u32) -> u32 {
    return a.saturating_add(b);
}
