// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ОТЧЁТ ПОКРЫТИЯ РЕШЕНИЙ (печатается ПОСЛЕДНИМ тестом ядра).
//!
//! ⚠️ Zig 0.13 не умеет LLVM source-based coverage. Покрытие собирается
//! своими счётчиками `cov.hit(.имя)` в критичных точках решения
//! (Врата, заголовок .kimg, Merkle, ФС, кэш, мост решателя).
//!
//! Этот тест обязан идти ПОСЛЕДНИМ в `src/test_root.zig` — иначе счётчики
//! ещё не набраны. Он печатает, сколько инструментированных решений
//! реально исполнено, и ПАДАЕТ, если покрытие ниже порога (95 %).
const std = @import("std");
const cov = @import("../cov.zig");

/// Порог покрытия решений (DO-178C DAL A ориентируется на 100 %; для
/// инструментированного подмножества фиксируем 95 % как gate).
const THRESHOLD_PCT: f64 = 95.0;

test "ПОКРЫТИЕ: отчёт по инструментированным решениям" {
    const N = @typeInfo(cov.Site).Enum.fields.len;
    var covered: usize = 0;
    inline for (@typeInfo(cov.Site).Enum.fields) |f| {
        if (cov.counters[f.value] > 0) covered += 1;
    }
    const pct = @as(f64, @floatFromInt(covered)) / @as(f64, @floatFromInt(N)) * 100.0;

    try cov.report(std.io.getStdErr().writer());
    std.debug.print("\n  ПОРОГ: {d:.0}%  ФАКТ: {d:.1}%  -> {s}\n\n", .{
        THRESHOLD_PCT, pct, if (pct >= THRESHOLD_PCT) "PASS" else "FAIL",
    });

    try std.testing.expect(pct >= THRESHOLD_PCT);
}
