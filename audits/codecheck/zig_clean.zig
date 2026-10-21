// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: Zig is outside the contract subset. Expected verdict: N (unsupported).
// KERN must NOT emit F for a language it cannot check.
pub fn add(a: i64, b: i64) i64 {
    return a + b;
}
