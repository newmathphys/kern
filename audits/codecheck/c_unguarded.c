// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: UNGUARDED division in C (real defect). Expected: F with a
// division-by-zero counterexample, respecting int machine bounds.
// @kern:requires a >= -1000 and a <= 1000
// @kern:ensures result == a / b
int ratio(int a, int b) {
    return a / b;
}
