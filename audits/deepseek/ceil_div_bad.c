// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// CORPUS: the SAME real function WITHOUT the divisor guard — the classic twin of a
// missing precondition. Expected: F (counterexample: y == 0).
// @kern:requires x >= 0
// @kern:ensures result >= 0
int ceil_div(int x, int y) {
    return (x + y - 1) / y;
}
