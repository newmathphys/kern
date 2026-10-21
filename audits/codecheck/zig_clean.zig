// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: correct Zig code with a contract. KERN must PROVE it (T).
// @kern:requires a >= -100 and a <= 100 and b >= -100 and b <= 100
// @kern:ensures result == a + b
pub fn add(a: i64, b: i64) i64 {
    return a + b;
}
