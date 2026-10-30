// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.
//
// ШАГ 4b, ПОЗИТИВНЫЙ КОНТРОЛЬ: битовая мёртвая ветка. В Int-модели не видна
// ВООБЩЕ (битовых операторов там нет) — ловится ТОЛЬКО в QF_BV32:
// младшие два бита нулевые => `(x & 3) != 0` недостижимо.
int bit_dead(int x) {
    if ((x & 1) == 0) {
        if ((x & 2) == 0) {
            if ((x & 3) != 0) return 1;
        }
    }
    return 0;
}
