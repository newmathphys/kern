// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: ВСТРОЕННОЕ ПОКРЫТИЕ РЕШЕНИЙ (self-instrumented branch coverage).
//!
//! ⚠️ ЧЕСТНО: Zig 0.13 НЕ поддерживает LLVM source-based coverage
//! (`zig test --coverage` отсутствует, `llvm-cov`/`kcov` в системе нет).
//! Поэтому покрытие собирается СВОИМИ счётчиками: каждая точка решения
//! (ветвь Врат, проверка целостности, отказ ФС) помечена `cov.hit(.имя)`.
//!
//! Это не заменяет LLVM-профайлер, но даёт ЧЕСТНУЮ метрику: сколько
//! инструментированных решений реально исполнено тестами.
//!
//! Отчёт печатается последним тестом (`tests/coverage_report_test.zig`).
const std = @import("std");

/// Точки решения, критичные для безопасности. Каждая — конкретная ветвь.
pub const Site = enum {
    // Врата Истины (admission_gate.zig)
    gate_ast_mismatch,
    gate_contract_mismatch,
    gate_untrusted_checker,
    gate_proved,
    gate_counterexample,
    gate_vacuous_policy_violation,
    gate_vacuous_allowed,
    gate_unknown_timeout,
    // Заголовок образа (kimg_reader.zig)
    hdr_bad_magic,
    hdr_bad_size,
    hdr_too_small,
    hdr_table_oob,
    hdr_payload_oob,
    hdr_ok,
    merkle_count_guard,
    merkle_mismatch,
    merkle_ok,
    // Дескриптор объекта (object_entry.zig)
    obj_bad_reserved,
    obj_ok,
    // Виртуальная ФС (kernfs_router.zig)
    fs_traversal_denied,
    fs_not_found,
    fs_access_denied,
    fs_hit,
    // Кэш доказательств (proof_cache.zig)
    cache_hit,
    cache_miss,
    cache_evict,
    // Мост решателя (z3_bridge.zig)
    z3_tool_error,
    z3_sat,
    z3_unsat,
    z3_unknown,
};

const N = @typeInfo(Site).@"enum".field_names.len;
pub var counters: [N]u32 = @as([N]u32, @splat(0));

/// Отметить исполнение точки решения. Inline — нулевая цена вызова.
pub inline fn hit(s: Site) void {
    counters[@intFromEnum(s)] += 1;
}

pub fn reset() void {
    counters = @as([N]u32, @splat(0));
}

/// Отчёт: сколько инструментированных решений исполнено и сколько раз.
pub fn report(writer: anytype) !void {
    var covered: usize = 0;
    inline for (@typeInfo(Site).@"enum".field_names, 0..) |_, fidx| {
        const n = counters[fidx];
        if (n > 0) covered += 1;
    }
    const total: usize = N;
    try writer.print("=== ПОКРЫТИЕ РЕШЕНИЙ (self-instrumented) ===\n", .{});
    try writer.print("  инструментированных решений: {d}\n", .{total});
    try writer.print("  исполнено тестами:            {d}\n", .{covered});
    try writer.print("  ПОКРЫТИЕ РЕШЕНИЙ:             {d:.1}%\n\n", .{
        @as(f64, @floatFromInt(covered)) / @as(f64, @floatFromInt(total)) * 100.0,
    });
    inline for (@typeInfo(Site).@"enum".field_names, 0..) |f, fidx| {
        const n = counters[fidx];
        try writer.print("  {s:<32} {d:>7} {s}\n", .{ f, n, if (n == 0) " <-- НЕ ИСПОЛНЕНО" else "" });
    }
}
