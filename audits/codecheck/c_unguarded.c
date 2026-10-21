// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// CORPUS: unguarded division (a real defect) in C. Expected: N, never F.
int ratio(int a, int b) {
    return a / b;
}
