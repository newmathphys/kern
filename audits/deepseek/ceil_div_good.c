// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// CORPUS: REAL function from DeepSeek/DeepEP-Ascend (4dfccac4), expressible in C.
// Source semantics: `deep_ep/utils/math.py:22` — `def ceil_div(x, y): return (x + y - 1) // y`.
// PROVEN in the field pilot: e=1, 70 proof steps, holes 0 (contract `result >= 0`).
// Expected: T (contract proven).
// @kern:requires x >= 0 and y > 0
// @kern:ensures result >= 0
int ceil_div(int x, int y) {
    return (x + y - 1) / y;
}
