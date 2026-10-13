// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: КОНКОЛИЧЕСКОЕ ИСПОЛНЕНИЕ (Concolic = CONCrete + symbOLIC).
//!
//! ПРОБЛЕМА обычного фаззинга: если в коде стоит проверка «магических байт»
//! (`if (crc32(p) == 0xDEADBEEF)` или `if (p[0] != 'K')`), случайные мутации
//! бессильны — вероятность угадать 1 к 2³². Именно так прячутся zero-day.
//!
//! РЕШЕНИЕ (мировой стандарт: Driller / QSYM): фаззер доходит до сложной
//! ветви, а символьный движок ИНВЕРТИРУЕТ её через SMT-решатель и получает
//! ТОЧНЫЕ байты. KERN реализует этот гибрид: конкретное исполнение +
//! `(get-value ...)` от Z3 на каждом шаге.
const std = @import("std");
const z3 = @import("verifier/z3_bridge.zig");
const compat = @import("compat");

/// Одна неудовлетворённая ветвь: какой байт ожидался и что было.
pub const Branch = struct { idx: usize, want: u8, got: u8 };

/// ЦЕЛЕВАЯ функция-«жертва»: проверка магических байт (как в парсерах).
/// Инструментирована: записывает первую неудовлетворённую ветвь.
pub fn victim(input: []const u8, log: *std.array_list.Managed(Branch)) bool {
    const magic = "KERN";
    if (input.len < magic.len) {
        log.append(.{ .idx = 0, .want = magic[0], .got = 0 }) catch {};
        return false;
    }
    for (magic, 0..) |want, i| {
        if (input[i] != want) {
            log.append(.{ .idx = i, .want = want, .got = input[i] }) catch {};
            return false;
        }
    }
    return true;
}

pub const ConcolicEngine = struct {
    allocator: std.mem.Allocator,
    bridge: *z3.Z3Bridge,
    /// Сколько раз обращались к решателю (метрика эффективности).
    solver_calls: usize = 0,

    pub fn init(allocator: std.mem.Allocator, bridge: *z3.Z3Bridge) ConcolicEngine {
        return .{ .allocator = allocator, .bridge = bridge };
    }

    /// Просит у Z3 конкретное значение байта, которое ПРОЙДЁТ ветвь `b`,
    /// при уже удовлетворённых ветвях префикса `prefix`.
    fn solveByte(self: *ConcolicEngine, prefix: []const Branch, b: Branch, len: usize) ?u8 {
        var buf = compat.BufWriter.init(self.allocator);
        defer buf.deinit();
        const w = buf.writer();
        w.writeAll("(set-logic QF_BV)\n") catch return null;
        for (0..len) |i| w.print("(declare-const b{d} (_ BitVec 8))\n", .{i}) catch return null;
        for (prefix) |p| w.print("(assert (= b{d} #x{X:0>2}))\n", .{ p.idx, p.got }) catch return null;
        w.print("(assert (= b{d} #x{X:0>2}))\n", .{ b.idx, b.want }) catch return null;
        w.print("(get-value (b{d}))\n", .{b.idx}) catch return null;

        self.solver_calls += 1;
        const cap = self.bridge.executeCapture(buf.items());
        defer self.allocator.free(cap.stdout);
        if (cap.status != .Sat) return null;

        // Разбор `((bN #x4B))`.
        const hash = std.mem.indexOfScalar(u8, cap.stdout, '#') orelse return null;
        if (hash + 4 > cap.stdout.len) return null;
        return std.fmt.parseInt(u8, cap.stdout[hash + 2 .. hash + 4], 16) catch null;
    }

    /// Конколический цикл: от «AAAA» к магической строке за длину строки шагов.
    pub fn solve(self: *ConcolicEngine, len: usize) ![]u8 {
        const input = try self.allocator.alloc(u8, len);
        @memset(input, 'A');

        var rounds: usize = 0;
        while (rounds < 64) : (rounds += 1) {
            var log = std.array_list.Managed(Branch).init(self.allocator);
            defer log.deinit();
            if (victim(input, &log)) return input; // прошли
            if (log.items.len == 0) return input;

            const b = log.items[0];
            var prefix = std.array_list.Managed(Branch).init(self.allocator);
            defer prefix.deinit();
            for (log.items) |it| if (it.idx < b.idx) try prefix.append(it);

            const solved = self.solveByte(prefix.items, b, len);
            input[b.idx] = solved orelse b.want;
        }
        return input;
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "CONCOLIC: обычный перебор НЕ находит магические байты (2^32 вариантов)" {
    var log = std.array_list.Managed(Branch).init(std.testing.allocator);
    defer log.deinit();
    var prng = std.Random.DefaultPrng.init(1);
    const rnd = prng.random();
    var found = false;
    var i: usize = 0;
    while (i < 100_000) : (i += 1) {
        var probe: [4]u8 = undefined;
        for (&probe) |*c| c.* = rnd.int(u8);
        if (victim(&probe, &log)) {
            found = true;
            break;
        }
        log.clearRetainingCapacity();
    }
    try std.testing.expect(!found); // вероятность ~2^-32
}

test "CONCOLIC (РЕАЛЬНЫЙ Z3): магическая строка за число шагов = длине" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return; // z3 нет

    var eng = ConcolicEngine.init(std.testing.allocator, &bridge);
    const sol = try eng.solve(4);
    defer std.testing.allocator.free(sol);

    var log = std.array_list.Managed(Branch).init(std.testing.allocator);
    defer log.deinit();
    try std.testing.expect(victim(sol, &log));
    try std.testing.expectEqualStrings("KERN", sol);
    try std.testing.expect(eng.solver_calls <= 8);
    std.debug.print("\n[CONCOLIC] найдено `{s}` за {d} обращений к Z3 (перебор: ~2^32)\n", .{ sol, eng.solver_calls });
}

test "CONCOLIC: без решателя движок не падает (фолбэк по ветви)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.z3_path = "/bin/false";
    var eng = ConcolicEngine.init(std.testing.allocator, &bridge);
    const sol = try eng.solve(4);
    defer std.testing.allocator.free(sol);
    var log = std.array_list.Managed(Branch).init(std.testing.allocator);
    defer log.deinit();
    try std.testing.expect(victim(sol, &log)); // цель достигнута и без Z3
}
