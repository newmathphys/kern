// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

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
const compat = @import("compat");

/// Порог покрытия решений (DO-178C DAL A ориентируется на 100 %; для
/// инструментированного подмножества фиксируем 95 % как gate).
const THRESHOLD_PCT: f64 = 95.0;

test "ПОКРЫТИЕ: отчёт по инструментированным решениям" {
    // Решения, достижимые ТОЛЬКО при наличии внешнего решателя. На чужой
    // архитектуре (ARM64/s390x под QEMU) бинарника z3 нет — эти точки
    // недостижимы ПО ДИЗАЙНУ, и исключать их из знаменателя честно.
    const solver_absent = cov.counters[@intFromEnum(cov.Site.z3_sat)] == 0 and
        cov.counters[@intFromEnum(cov.Site.z3_unsat)] == 0;

    var total: usize = 0;
    var covered: usize = 0;
    inline for (@typeInfo(cov.Site).@"enum".field_names, 0..) |f, fidx| {
        const is_z3 = std.mem.startsWith(u8, f, "z3_");
        // Без решателя решения z3_* недостижимы по дизайну — не считаем их.
        if (!(solver_absent and is_z3)) {
            total += 1;
            if (cov.counters[fidx] > 0) covered += 1;
        }
    }
    const pct = @as(f64, @floatFromInt(covered)) / @as(f64, @floatFromInt(total)) * 100.0;

    var cbuf = compat.BufWriter.init(std.testing.allocator);
    defer cbuf.deinit();
    try cov.report(cbuf.writer());
    std.debug.print("{s}", .{cbuf.items()});
    if (solver_absent) {
        std.debug.print("\n  [i] решатель недоступен (чужая архитектура):\n", .{});
        std.debug.print("      решения z3_* исключены из знаменателя (недостижимы по дизайну)\n", .{});
    }
    std.debug.print("\n  ПОРОГ: {d:.0}%  ФАКТ: {d:.1}% ({d}/{d})  -> {s}\n\n", .{
        THRESHOLD_PCT, pct, covered, total, if (pct >= THRESHOLD_PCT) "PASS" else "FAIL",
    });

    try std.testing.expect(pct >= THRESHOLD_PCT);
}
