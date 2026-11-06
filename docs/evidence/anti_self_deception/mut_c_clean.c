// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the GNU AGPL-3.0-or-later.
// CORPUS: correct C code with a contract. KERN must PROVE it (T).
// @kern:requires a >= -1000 and a <= 1000 and b >= -1000 and b <= 1000
// @kern:ensures result == a + b
int add_bounded(int a, int b) {
    return a - b;
}
