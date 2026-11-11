// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
/* Контроль #616: метка ставится там, где вызов ЛИТЕРАЛЬНЫЙ, но нарушение
   через него ДОСТИЖИМО (b = 0 — литерал вызова). Публичная функция — без метки. */
static int div_helper(int a, int b) {
    return a / b;
}

int use_div(int v) {
    return div_helper(v, 0);
}

int public_sub(int k) {
    return k - 1;
}
