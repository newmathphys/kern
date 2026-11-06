// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
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
