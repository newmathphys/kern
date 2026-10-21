// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: correct Rust code with a contract. KERN must PROVE it (T).
// @kern:requires a >= -1000 and a <= 1000 and b >= -1000 and b <= 1000
// @kern:ensures result == a + b
pub fn add_bounded(a: i64, b: i64) -> i64 {
    return a - b;
}
