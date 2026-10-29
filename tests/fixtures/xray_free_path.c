// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// КОРПУС (шаг 4 плана, класс #178/#183): СВОБОДНАЯ КОНСТАНТА В ПУТИ.
// `LIMIT_UNDEFINED` парсеру неизвестна, поэтому в путь попадает СВОБОДНОЕ имя.
// Если решателю позволить выбрать её значение, он возьмёт ±MAX и «найдёт»
// переполнение в `n + n`, которого при реальном LIMIT = 1024 НЕТ.
// Ожидание: НИ ОДНОЙ находки + ОТКАЗ с названной причиной (флаг free_syms_in_path).
int scale_with_limit(int n) {
    if (n < LIMIT_UNDEFINED) {
        return n + n;
    }
    return 0;
}
