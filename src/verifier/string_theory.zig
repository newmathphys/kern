// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ТЕОРИЯ СТРОК (QF_S / QF_SLIA) — символьный анализ инъекций.
//!
//! Вектор 3 из архитектурной матрицы. Строковые уязвимости (Path Traversal,
//! SQL-инъекции, XSS, нуль-байтовые инъекции) — одна из самых сложных тем SMT.
//! KERN транслирует проверку санитайзера в строковые ограничения SMT-LIB.
//!
//! Соглашение: KERN строит ОТРИЦАНИЕ безопасности. Ответ Z3:
//!   * `sat`   — существует вход, ПРОХОДЯЩИЙ санитайзер, но опасный
//!               → УЯЗВИМОСТЬ ДОКАЗАНА (контрпример — конкретная строка);
//!   * `unsat` — безопасность доказана для ВСЕХ строк (математическая гарантия).
//!
//! Где ловим баги: санитайзеры, которые вырезают `/`, но забывают `..`;
//! нуль-байтовые обрывы строки; регулярки с катастрофическим возвратом.
const std = @import("std");
const z3 = @import("z3_bridge.zig");
const compat = @import("compat");

pub const StringTheoryEngine = struct {
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator) StringTheoryEngine {
        return .{ .allocator = allocator };
    }

    /// Общая форма: переменная `p : String` + список ограничений.
    fn wrap(self: *StringTheoryEngine, constraints: []const []const u8, model: bool) ![]u8 {
        var buf = compat.BufWriter.init(self.allocator);
        errdefer buf.deinit();
        const w = buf.writer();
        try w.writeAll("(set-logic QF_SLIA)\n(declare-const p String)\n");
        for (constraints) |c| try w.print("(assert {s})\n", .{c});
        try w.writeAll("(check-sat)\n");
        if (model) try w.writeAll("(get-model)\n");
        return buf.toOwnedSlice();
    }

    /// Достижима ли строка, содержащая `needle` (напр. ".." для Traversal)?
    pub fn buildContainsQuery(self: *StringTheoryEngine, needle: []const u8) ![]u8 {
        const c = try std.fmt.allocPrint(self.allocator, "(str.contains p \"{s}\")", .{needle});
        defer self.allocator.free(c);
        const list = [_][]const u8{c};
        return self.wrap(&list, true);
    }

    /// Разрыв санитайзера: опасная подстрока `danger` проходит, хотя `removed`
    /// вырезается. `sat` = санитайзер неполон → УЯЗВИМОСТЬ.
    pub fn buildSanitizerGapQuery(self: *StringTheoryEngine, danger: []const u8, removed: []const u8) ![]u8 {
        const c1 = try std.fmt.allocPrint(self.allocator, "(str.contains p \"{s}\")", .{danger});
        defer self.allocator.free(c1);
        const c2 = try std.fmt.allocPrint(self.allocator, "(not (str.contains p \"{s}\"))", .{removed});
        defer self.allocator.free(c2);
        const list = [_][]const u8{ c1, c2 };
        return self.wrap(&list, true);
    }

    /// Нуль-байтовая инъекция: может ли вход содержать символ 0x00?
    /// `sat` = да (потенциальный обрыв строки в C-API).
    pub fn buildZeroByteQuery(self: *StringTheoryEngine) ![]u8 {
        const list = [_][]const u8{"(str.contains p (str.from_code 0))"};
        return self.wrap(&list, true);
    }

    /// Соответствие регулярному выражению + содержит подстроку.
    /// Пример: p ∈ a* ∧ p содержит "b" → `unsat` (regex корректен).
    pub fn buildRegexContainsQuery(self: *StringTheoryEngine, regex: []const u8, needle: []const u8) ![]u8 {
        const c1 = try std.fmt.allocPrint(self.allocator, "(str.in_re p {s})", .{regex});
        defer self.allocator.free(c1);
        const c2 = try std.fmt.allocPrint(self.allocator, "(str.contains p \"{s}\")", .{needle});
        defer self.allocator.free(c2);
        const list = [_][]const u8{ c1, c2 };
        return self.wrap(&list, false);
    }

    /// Начинается ли строка с префикса (напр. "/etc/" — выход за корень).
    pub fn buildPrefixQuery(self: *StringTheoryEngine, prefix: []const u8) ![]u8 {
        const c = try std.fmt.allocPrint(self.allocator, "(str.prefixof \"{s}\" p)", .{prefix});
        defer self.allocator.free(c);
        const list = [_][]const u8{c};
        return self.wrap(&list, true);
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "STRINGS: скрипт содержит строковые ограничения SMT-LIB" {
    var eng = StringTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildSanitizerGapQuery("..", "/");
    defer std.testing.allocator.free(q);
    try std.testing.expect(std.mem.indexOf(u8, q, "(set-logic QF_SLIA)") != null);
    try std.testing.expect(std.mem.indexOf(u8, q, "(str.contains p \"..\")") != null);
    try std.testing.expect(std.mem.indexOf(u8, q, "(not (str.contains p \"/\"))") != null);
}

test "STRINGS (РЕАЛЬНЫЙ Z3): строка с '..' существует (sat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = StringTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildContainsQuery("..");
    defer std.testing.allocator.free(q);
    try std.testing.expectEqual(z3.SmtStatus.Sat, bridge.executeQuery(q).status);
}

test "STRINGS (РЕАЛЬНЫЙ Z3): УЯЗВИМОСТЬ — '..' проходит при вырезании '/' (sat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = StringTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildSanitizerGapQuery("..", "/");
    defer std.testing.allocator.free(q);
    // Санитайзер, вырезающий только '/', НЕ защищает от '..' → sat (баг найден).
    try std.testing.expectEqual(z3.SmtStatus.Sat, bridge.executeQuery(q).status);
}

test "STRINGS (РЕАЛЬНЫЙ Z3): нуль-байтовая инъекция достижима (sat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = StringTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildZeroByteQuery();
    defer std.testing.allocator.free(q);
    try std.testing.expectEqual(z3.SmtStatus.Sat, bridge.executeQuery(q).status);
}

test "STRINGS (РЕАЛЬНЫЙ Z3): regex a* корректно исключает 'b' (unsat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = StringTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildRegexContainsQuery("(re.* (str.to_re \"a\"))", "b");
    defer std.testing.allocator.free(q);
    try std.testing.expectEqual(z3.SmtStatus.Unsat, bridge.executeQuery(q).status);
}
