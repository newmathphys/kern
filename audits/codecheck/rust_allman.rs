// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: Allman style (`{` on the NEXT line) with a REAL i32 overflow.
// Expected: F with an overflow counterexample near i32::MAX. Regression guard
// for defect #325 - a defect written in Allman style must be FOUND, not skipped.
// @kern:requires a >= 0 and b >= 0
// @kern:ensures result >= a
pub fn add32Allman(a: i32, b: i32) -> i32
{
    return a + b;
}
