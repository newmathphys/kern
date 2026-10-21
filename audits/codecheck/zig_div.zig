// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: unguarded division (a real defect), but Zig is outside KERN's
// contract subset. Expected verdict: N, never F — KERN must not pretend.
pub fn ratio(a: i64, b: i64) i64 {
    return a / b;
}
