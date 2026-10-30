// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.
//
// ШАГ 4b, НЕГАТИВНЫЙ КОНТРОЛЬ (защита от ЛОЖНОГО обвинения Int-модели):
// в ℤ условие `x > 0 && x + 1 < 0` невыполнимо, и Int-путь объявлял ветку
// МЁРТВОЙ. В C при `x = INT_MAX` (0x7fffffff) `x + 1` ПЕРЕНОСИТСЯ в отрицательное
// значение, то есть ветка ЖИВА. Перекрёстная проверка в BV32 обязана снять
// обвинение и НАЗВАТЬ это заметкой, а не молчать.
int wrap_alive(int x) {
    if (x > 0) {
        if (x + 1 < 0) return 1;
    }
    return 0;
}
