# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# ДЕФЕКТ #342 (шаг N12): ФРОНТЕНД `@kern:lang evm` + ЯВНАЯ BV-директива.
//
// C-подобный синтаксис (`.c`) выбран НАМЕРЕННО: оборачивание `SDIV(MIN, -1)`
// проверяется в теории битовых векторов, а BV-путь работает с текстом тела
// (`raw_body`), которого у Python-парсера нет. Семантика берётся из ТАБЛИЦЫ по
// директиве `@kern:lang evm`, синтаксис — из C-парсера.
// @kern:lang evm
// @kern:bitvec32

// @kern:requires a == -2147483648 and b == -1
// @kern:ensures result == -2147483648
int evm_sdiv_min(int a, int b) {
    // Yellow Paper: SDIV(MIN, -1) = MIN — оборачивание БЕЗ паники
    // (в C это ловушка idiv; у EVM ловушки нет по определению).
    return a / b;
}

// @kern:requires a == -7 and b == 2
// @kern:ensures result == -3
int evm_sdiv_trunc(int a, int b) {
    // Усечение к нулю: (-7) / 2 == -3 в EVM (floor дал бы -4).
    return a / b;
}
