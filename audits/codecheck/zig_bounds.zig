// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: guarded index. Expected verdict: N (unsupported), never F.
pub fn firstOrZero(xs: []const u8) u8 {
    if (xs.len == 0) return 0;
    return xs[0];
}
