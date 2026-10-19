# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 5, ПУНКТ 25: полиглот-экстрактор — TypeScript (7-й язык семейства).
# Ожидания приёмки: clampTs -> PROVEN, badTs -> REFUTED.


// @kern:requires x >= 0
// @kern:ensures result >= 0
export function clampTs(x: int32): int32 {
    if (x < 0) {
        return 0;
    }
    return x;
}


// @kern:ensures result >= 0
export function badTs(x: int32): int32 {
    return x - 1;
}


// SORBET-STYLE: диапазон выведен ИЗ ИМЕНИ ТИПА (`Percent` -> 0..100), без
// ручного `@kern:requires`. Доказано, потому что 0 <= p <= 100.
// @kern:ensures result >= 0
export function pctTs(p: Percent): int32 {
    return p;
}


// ЧЕСТНЫЙ ОТКАЗ: `number` — это float64, а НЕ целое. KERN не подставляет ему
// диапазон `int` (это была бы проверка другой функции), а сообщает причину.
// @kern:ensures result >= 0
export function numTs(x: number): number {
    return x;
}
