// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: UNSAT CORE — точная локализация логической ошибки (Fault Localization).
//!
//! Вектор 8 из архитектурной матрицы. Идея: каждое условие контракта
//! размечается именем `(assert (! φ :named line_42))`. Когда Z3 находит
//! противоречие, `(get-unsat-core)` возвращает НЕРАЗРЕШИМОЕ ЯДРО —
//! подмножество условий, которое само по себе противоречиво.
//!
//! ЗАЧЕМ: ∇error для ИИ становится точечным. Вместо «ошибка» пользователь
//! получает точные имена правил (номера строк), которые надо править.
//!
//! Где ловим баги: избыточные/взаимно исключающие контракты, которые тихо
//! нейтрализуют проверки безопасности (скрытый вакуумный успех).
const std = @import("std");
const z3 = @import("z3_bridge.zig");

pub const NamedAssertion = struct {
    name: []const u8,
    formula: []const u8,
};

pub const UnsatCore = struct {
    allocator: std.mem.Allocator,
    is_conflict: bool,
    conflicting: [][]const u8,

    pub fn deinit(self: *UnsatCore) void {
        for (self.conflicting) |n| self.allocator.free(n);
        self.allocator.free(self.conflicting);
    }

    pub fn contains(self: *const UnsatCore, name: []const u8) bool {
        for (self.conflicting) |n| if (std.mem.eql(u8, n, name)) return true;
        return false;
    }
};

pub const UnsatCoreEngine = struct {
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator) UnsatCoreEngine {
        return .{ .allocator = allocator };
    }

    /// SMT-LIB2-скрипт с ИМЕНОВАННЫМИ ассертами и запросом ядра.
    /// `goal` добавляется в виде ОТРИЦАНИЯ (ищем контрпример к цели).
    pub fn buildTrackedScript(
        self: *UnsatCoreEngine,
        decls: []const u8,
        assertions: []const NamedAssertion,
        goal: []const u8,
    ) ![]u8 {
        var aw: std.Io.Writer.Allocating = .init(self.allocator);
        errdefer aw.deinit();
        const w = &aw.writer;
        try w.writeAll("(set-option :produce-unsat-cores true)\n(set-logic ALL)\n");
        try w.writeAll(decls);
        try w.writeAll("\n");
        for (assertions) |a| {
            try w.print("(assert (! {s} :named {s}))\n", .{ a.formula, a.name });
        }
        try w.print("(assert (! (not {s}) :named goal))\n", .{goal});
        try w.writeAll("(check-sat)\n(get-unsat-core)\n");
        return aw.toOwnedSlice();
    }

    /// Разбирает вывод Z3 вида `unsat\n(name1 name2 ...)\n`.
    pub fn parseCore(self: *UnsatCoreEngine, stdout: []const u8) !UnsatCore {
        var list = std.array_list.Managed([]const u8).init(self.allocator);
        errdefer {
            for (list.items) |n| self.allocator.free(n);
            list.deinit();
        }
        var is_conflict = false;
        if (std.mem.startsWith(u8, stdout, "unsat")) {
            is_conflict = true;
            if (std.mem.indexOfScalar(u8, stdout, '(')) |s| {
                if (std.mem.indexOfScalarPos(u8, stdout, s, ')')) |e| {
                    var it = std.mem.tokenizeAny(u8, stdout[s + 1 .. e], " \t\r\n");
                    while (it.next()) |tok| {
                        try list.append(try self.allocator.dupe(u8, tok));
                    }
                }
            }
        }
        return .{
            .allocator = self.allocator,
            .is_conflict = is_conflict,
            .conflicting = try list.toOwnedSlice(),
        };
    }

    /// Полный контур: построить скрипт → прогнать через Z3 → вернуть ядро.
    pub fn localize(
        self: *UnsatCoreEngine,
        bridge: *z3.Z3Bridge,
        decls: []const u8,
        assertions: []const NamedAssertion,
        goal: []const u8,
    ) !UnsatCore {
        const script = try self.buildTrackedScript(decls, assertions, goal);
        defer self.allocator.free(script);
        const cap = bridge.executeCapture(script);
        defer self.allocator.free(cap.stdout);
        return self.parseCore(cap.stdout);
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "UNSAT CORE (mock): извлечение имён ядра из вывода Z3" {
    var eng = UnsatCoreEngine.init(std.testing.allocator);
    var core = try eng.parseCore("unsat\n(line_10_non_negative line_25_post_bug)\n");
    defer core.deinit();
    try std.testing.expect(core.is_conflict);
    try std.testing.expectEqual(@as(usize, 2), core.conflicting.len);
    try std.testing.expectEqualStrings("line_10_non_negative", core.conflicting[0]);
    try std.testing.expectEqualStrings("line_25_post_bug", core.conflicting[1]);
}

test "UNSAT CORE (mock): sat не даёт ядра" {
    var eng = UnsatCoreEngine.init(std.testing.allocator);
    var core = try eng.parseCore("sat\n");
    defer core.deinit();
    try std.testing.expect(!core.is_conflict);
    try std.testing.expectEqual(@as(usize, 0), core.conflicting.len);
}

test "UNSAT CORE (скрипт): содержит :named и get-unsat-core" {
    var eng = UnsatCoreEngine.init(std.testing.allocator);
    const pres = [_]NamedAssertion{
        .{ .name = "line_10_non_negative", .formula = "(>= x 0)" },
        .{ .name = "line_12_upper_bound", .formula = "(<= x 100)" },
    };
    const script = try eng.buildTrackedScript("(declare-const x Int)", &pres, "(>= x 0)");
    defer std.testing.allocator.free(script);
    try std.testing.expect(std.mem.indexOf(u8, script, ":named line_10_non_negative") != null);
    try std.testing.expect(std.mem.indexOf(u8, script, "(get-unsat-core)") != null);
    try std.testing.expect(std.mem.indexOf(u8, script, ":named goal") != null);
}

test "UNSAT CORE (РЕАЛЬНЫЙ Z3): локализация точной конфликтующей строки" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return; // z3 нет
    var eng = UnsatCoreEngine.init(std.testing.allocator);
    const pres = [_]NamedAssertion{
        .{ .name = "line_10_non_negative", .formula = "(>= x 0)" },
        .{ .name = "line_12_upper_bound", .formula = "(<= x 100)" },
    };
    var core = try eng.localize(&bridge, "(declare-const x Int)", &pres, "(>= x 0)");
    defer core.deinit();
    // Цель следует из line_10 => ядро = {line_10, goal}. line_12 не нужен.
    try std.testing.expect(core.is_conflict);
    try std.testing.expect(core.contains("goal"));
    try std.testing.expect(core.contains("line_10_non_negative"));
    try std.testing.expect(!core.contains("line_12_upper_bound"));
}
