// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: UNGUARDED division (real defect). KERN must REFUTE it (F) with a
// division-by-zero counterexample - not shrug it off as "unsupported".
// @kern:requires a >= -1000 and a <= 1000
// @kern:ensures result == a / b
pub fn ratio(a: i64, b: i64) i64 {
    return a / b;
}
