// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ЗОНД ДЛЯ БИНАРНОГО АНАЛИЗА (проверка на уровне АССЕМБЛЕРА).
//!
//! Экспортирует критические функции с C-именами, чтобы `tools/binlevel_verify.sh`
//! мог найти их в сгенерированном ассемблере и проверить БИНАРНЫЕ свойства:
//!   * constant-time сравнение НЕ содержит условных переходов в цикле
//!     (иначе компилятор вернул ранний выход и вернул timing-утечку!);
//!   * функция-«жертва» конколики содержит ожидаемые проверки.
const std = @import("std");
const compat = @import("compat");
const nonint = @import("verifier/noninterference.zig");

/// Constant-time сравнение n байт. Инвариант: НИ ОДНОГО условного перехода
/// внутри цикла — время не должно зависеть от данных.
pub export fn kern_ct_equal(a: [*]const u8, b: [*]const u8, n: usize) callconv(.C) bool {
    return nonint.constantTimeEqual(a[0..n], b[0..n]);
}

/// Контрольный пример: ранний выход (для контраста в анализе ассемблера).
pub export fn kern_early_exit_equal(a: [*]const u8, b: [*]const u8, n: usize) callconv(.C) bool {
    return nonint.earlyExitEqual(a[0..n], b[0..n]);
}

pub fn main(init: std.process.Init) void {
    // Zig 0.17: файловый I/O требует setIo() до первого вызова.
    compat.setIo(init.io);
    _ = init;}
