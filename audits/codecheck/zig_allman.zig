// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: Allman style (`{` on the NEXT line) with a contract. KERN must PROVE it
// (T). Regression guard for defect #325: with `{` required on the header line,
// this function was SILENTLY not recognised ("no functions with @kern:") and the
// verdict was a total of 0 - the same code with `{` on the same line was checked.
// @kern:requires a >= -100 and a <= 100 and b >= -100 and b <= 100
// @kern:ensures result == a + b
pub fn addAllman(a: i64, b: i64) i64
{
    return a + b;
}
