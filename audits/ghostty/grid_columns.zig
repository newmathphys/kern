// ТЕНЬ-КОНТРАКТ на РЕАЛЬНУЮ функцию из Ghostty (GPU-терминал):
//   src/renderer/size.zig:253  GridSize.update(screen, cell)
//   тело:
//     const cell_width: f32 = @floatFromInt(cell.width);
//     const screen_width: f32 = @floatFromInt(screen.width);
//     const calc_cols: Unit = @intFromFloat(screen_width / cell_width);
//     self.columns = @max(1, calc_cols);
//
// МОДЕЛИРОВАНИЕ (честно, два шага):
//  1. `@max(1, x)` развёрнут как `if (x < 1) return 1; return x;` — это ровно его
//     семантика, но записана операторами, которые понимает экстрактор.
//  2. Деление во float (f32) заменено целочисленным `/`. Для НЕотрицательных
//     значений это одно и то же (усечение к нулю = floor), НО f32 точно
//     представляет целые лишь до 2^24 — поэтому `requires` ограничивает входы
//     этим диапазоном, и модель остаётся верной (граница оговорена, не спрятана).
//
// ЗАЧЕМ такая спецификация: код обязан ГАРАНТИРОВАТЬ, что сетка не пустая
// (columns >= 1) — иначе терминал рисует ноль колонок.

/// @kern:requires screen_width >= 0 and screen_width < 16777216 and cell_width > 0 and cell_width < 16777216
/// @kern:ensures  result >= 1
pub fn gridColumns(screen_width: i32, cell_width: i32) i32 {
    const calc = screen_width / cell_width;
    if (calc < 1) return 1;
    return calc;
}

// КОНТРОЛЬ (мутация): снят кламп @max(1, ...) — сетка может стать пустой.
/// @kern:requires screen_width >= 0 and screen_width < 16777216 and cell_width > 0 and cell_width < 16777216
/// @kern:ensures  result >= 1
pub fn gridColumnsBuggy(screen_width: i32, cell_width: i32) i32 {
    const calc = screen_width / cell_width;
    return calc;
}
