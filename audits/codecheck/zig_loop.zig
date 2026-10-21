// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: Zig loop. Expected verdict: N (unsupported), never F.
pub fn sumTo(n: u64) u64 {
    var i: u64 = 0;
    var acc: u64 = 0;
    while (i < n) : (i += 1) acc += i;
    return acc;
}
