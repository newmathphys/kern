// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: НЕВМЕШАТЕЛЬСТВО (Non-Interference) / ГИПЕРСВОЙСТВА.
//!
//! Обычные свойства безопасности (Safety) проверяют ОДИН запуск программы:
//! «программа не падает». Свойства ГИПЕРБЕЗОПАСНОСТИ (Hyperproperties)
//! сравнивают ДВА запуска с разными секретами:
//!   «если секреты S₁ ≠ S₂, наблюдаемое поведение (ветвления, адреса
//!    памяти, время) ОБЯЗАНО совпадать».
//! Это формальная модель невмешательства — защита от Spectre / Cache-Timing.
//!
//! Здесь — статический taint-анализ по IR: три класса утечек:
//!   * BRANCH        — ветвление по секрету (Spectre v1);
//!   * MEMORY_INDEX  — адрес памяти зависит от секрета (cache timing);
//!   * VARIABLE_TIME — операция переменной длительности над секретом.
const std = @import("std");
const compat = @import("compat");

pub const Var = u32;

pub const Instr = union(enum) {
    secret: Var,
    public: Var,
    assign: struct { dst: Var, src: Var },
    branch_on: Var,
    mem_index: Var,
    variable_time: Var,
    /// Выбор без ветвления (constant-time cmov) — утечки НЕ создаёт.
    select_ct: struct { dst: Var, a: Var, b: Var },
};

pub const Leak = enum { none, branch, memory_index, variable_time };

pub const Finding = struct {
    leak: Leak,
    at: usize,
};

/// Статический анализ: возвращает список найденных утечек.
pub fn analyze(allocator: std.mem.Allocator, program: []const Instr) ![]Finding {
    var tainted = std.AutoHashMap(Var, void).init(allocator);
    defer tainted.deinit();
    var out = std.array_list.Managed(Finding).init(allocator);
    errdefer out.deinit();

    for (program, 0..) |instr, i| {
        switch (instr) {
            .secret => |v| try tainted.put(v, {}),
            .public => |v| _ = tainted.remove(v),
            .assign => |a| if (tainted.contains(a.src)) {
                try tainted.put(a.dst, {});
            },
            .select_ct => |s| {
                // cmov: taint переносится в результат, но ветвления нет.
                if (tainted.contains(s.a) or tainted.contains(s.b)) try tainted.put(s.dst, {});
            },
            .branch_on => |v| if (tainted.contains(v)) {
                try out.append(.{ .leak = .branch, .at = i });
            },
            .mem_index => |v| if (tainted.contains(v)) {
                try out.append(.{ .leak = .memory_index, .at = i });
            },
            .variable_time => |v| if (tainted.contains(v)) {
                try out.append(.{ .leak = .variable_time, .at = i });
            },
        }
    }
    return out.toOwnedSlice();
}

/// Constant-time сравнение байтовых строк: время НЕ зависит от данных.
pub fn constantTimeEqual(a: []const u8, b: []const u8) bool {
    if (a.len != b.len) return false; // длина публична
    var acc: u8 = 0;
    for (a, b) |x, y| acc |= x ^ y; // без ветвлений и раннего выхода
    return acc == 0;
}

/// НЕбезопасное сравнение (ранний выход) — для контраста в тестах.
pub fn earlyExitEqual(a: []const u8, b: []const u8) bool {
    if (a.len != b.len) return false;
    for (a, b) |x, y| if (x != y) return false;
    return true;
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "NONINTERFERENCE: ветвление по секрету = УТЕЧКА (Spectre-класс)" {
    const prog = [_]Instr{
        .{ .secret = 1 },
        .{ .branch_on = 1 },
    };
    const f = try analyze(std.testing.allocator, &prog);
    defer std.testing.allocator.free(f);
    try std.testing.expectEqual(@as(usize, 1), f.len);
    try std.testing.expectEqual(Leak.branch, f[0].leak);
}

test "NONINTERFERENCE: индекс массива по секрету = УТЕЧКА (cache-timing)" {
    const prog = [_]Instr{
        .{ .secret = 7 },
        .{ .mem_index = 7 },
    };
    const f = try analyze(std.testing.allocator, &prog);
    defer std.testing.allocator.free(f);
    try std.testing.expectEqual(@as(usize, 1), f.len);
    try std.testing.expectEqual(Leak.memory_index, f[0].leak);
}

test "NONINTERFERENCE: constant-time select НЕ даёт утечки ветвления" {
    const prog = [_]Instr{
        .{ .secret = 1 },
        .{ .select_ct = .{ .dst = 2, .a = 1, .b = 3 } },
        .{ .public = 2 },
    };
    const f = try analyze(std.testing.allocator, &prog);
    defer std.testing.allocator.free(f);
    try std.testing.expectEqual(@as(usize, 0), f.len);
}

test "NONINTERFERENCE: taint распространяется через присваивания" {
    const prog = [_]Instr{
        .{ .secret = 1 },
        .{ .assign = .{ .dst = 2, .src = 1 } },
        .{ .assign = .{ .dst = 3, .src = 2 } },
        .{ .branch_on = 3 },
    };
    const f = try analyze(std.testing.allocator, &prog);
    defer std.testing.allocator.free(f);
    try std.testing.expectEqual(@as(usize, 1), f.len);
    try std.testing.expectEqual(Leak.branch, f[0].leak);
}

test "NONINTERFERENCE: constant-time сравнение эквивалентно обычному" {
    try std.testing.expect(constantTimeEqual("secret", "secret"));
    try std.testing.expect(!constantTimeEqual("secret", "secrXt"));
    try std.testing.expect(!constantTimeEqual("short", "longer!"));
    try std.testing.expect(earlyExitEqual("secret", "secret"));
    try std.testing.expect(!earlyExitEqual("secret", "secrXt"));
}

/// Минимальное время выполнения `f` за `n` прогонов.
/// МИНИМУМ устойчив к шуму планировщика (в отличие от суммы/среднего):
/// редкие «выбросы» не влияют, а реальная разница длины пути — влияет.
fn minNanos(comptime f: fn () void, n: usize) u64 {
    var best: u64 = std.math.maxInt(u64);
    var i: usize = 0;
    while (i < n) : (i += 1) {
        var t = compat.Timer.start();
        f();
        const d = t.read();
        if (d < best) best = d;
    }
    return best;
}

fn ctHitEarly() void {
    std.mem.doNotOptimizeAway(constantTimeEqual("0123456789abcdef", "0123456789abcdeX"));
}
fn ctHitLate() void {
    std.mem.doNotOptimizeAway(constantTimeEqual("0123456789abcdef", "X123456789abcdef"));
}
fn eeHitEarly() void {
    std.mem.doNotOptimizeAway(earlyExitEqual("0123456789abcdef", "X123456789abcdef"));
}
fn eeHitLate() void {
    std.mem.doNotOptimizeAway(earlyExitEqual("0123456789abcdef", "0123456789abcdeX"));
}

test "NONINTERFERENCE: constant-time НЕ зависит от позиции отличия (ранний выход — ЗАВИСИТ)" {
    // Минимум из N: устойчив к шуму планировщика (сумма/среднее — нет).
    const ct_e = minNanos(ctHitEarly, 8_000);
    const ct_l = minNanos(ctHitLate, 8_000);
    const ee_e = minNanos(eeHitEarly, 8_000);
    const ee_l = minNanos(eeHitLate, 8_000);

    const ct_ratio = @as(f64, @floatFromInt(@max(ct_e, ct_l))) /
        @as(f64, @floatFromInt(@max(@min(ct_e, ct_l), 1)));
    const ee_ratio = @as(f64, @floatFromInt(@max(ee_e, ee_l))) /
        @as(f64, @floatFromInt(@max(@min(ee_e, ee_l), 1)));

    std.debug.print("\n[NONINTERFERENCE] отношение времён (позиция отличия 1 vs 16):\n" ++
        "  constant-time: {d:.2}x  (должно ~1)\n" ++
        "  ранний выход : {d:.2}x  (зависит от позиции)\n", .{ ct_ratio, ee_ratio });

    // Constant-time: отношение времён близко к 1 (порог 3x с запасом на шум).
    try std.testing.expect(ct_ratio < 3.0);
}

test "NONINTERFERENCE: earlyExitEqual различает длины (мутант false->true)" {
    // УБИВАЕТ МУТАНТ noninterference.zig:83 [false->true]:
    // при разных длинах функция обязана вернуть false; мутант вернёт true.
    // Проверено применением мутации (тест падает).
    try std.testing.expect(!earlyExitEqual("abc", "abcd"));
    try std.testing.expect(!earlyExitEqual("", "x"));
    try std.testing.expect(earlyExitEqual("abc", "abc")); // позитивный контроль
}

test "NONINTERFERENCE: cmov переносит taint от ОДНОГО операнда (мутант or->and)" {
    // УБИВАЕТ МУТАНТ noninterference.zig:57 [or->and]:
    // секретен ТОЛЬКО s.a; при `or` taint переходит на dst, при `and` — нет,
    // и ветвление по dst перестаёт считаться утечкой.
    const prog = [_]Instr{
        .{ .secret = 1 },
        .{ .public = 3 },
        .{ .select_ct = .{ .dst = 2, .a = 1, .b = 3 } },
        .{ .branch_on = 2 },
    };
    const f = try analyze(std.testing.allocator, &prog);
    defer std.testing.allocator.free(f);
    try std.testing.expect(f.len >= 1);
    try std.testing.expectEqual(Leak.branch, f[0].leak);
}
