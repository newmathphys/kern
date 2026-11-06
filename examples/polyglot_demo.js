// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// ЭШЕЛОН 5, ПУНКТ 25: JavaScript. Тип параметра не указан — берётся МОДЕЛЬ
// `int` (i32); это ЯВНОЕ допущение (в JS числа — float64), см. METRICS §100.8.
// Ожидания приёмки: clampJs -> PROVEN, badJs -> REFUTED.

// @kern:requires x >= 0
// @kern:ensures result >= 0
function clampJs(x) {
    if (x < 0) {
        return 0;
    }
    return x;
}

// @kern:ensures result >= 0
function badJs(x) {
    return x * 2;
}
