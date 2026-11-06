// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
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
