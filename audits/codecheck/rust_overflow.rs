// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: i32 overflow (real defect on machine bounds). Expected: F with an
// overflow counterexample near i32::MAX - unbounded arithmetic would "prove" it.
// @kern:requires a >= 0 and b >= 0
// @kern:ensures result >= a
pub fn add32(a: i32, b: i32) -> i32 {
    return a + b;
}
