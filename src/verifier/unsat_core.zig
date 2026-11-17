// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md

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
    /// SMT-LIB2-скрипт БЕЗ ЦЕЛИ: ищем несовместность САМОГО набора ассертов
    /// (файл-документ, а не «следует ли goal из посылок»).
    ///
    /// ЗАЧЕМ ОТДЕЛЬНО ОТ `buildTrackedScript`: там цель добавлялась отрицанием,
    /// и для файла-документа это дало бы ложную картину (`goal = false` ничего
    /// не ограничивает). Здесь все ассерты равноправны, ядро — их подмножество.
    pub fn buildTrackedScriptNoGoal(
        self: *UnsatCoreEngine,
        decls: []const u8,
        assertions: []const NamedAssertion,
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
        try w.writeAll("(check-sat)\n(get-unsat-core)\n");
        return aw.toOwnedSlice();
    }

    /// Скрипт БЕЗ трекинга: только `(check-sat)` по подмножеству.
    /// Нужен для ПРОВЕРКИ НЕПРИВОДИМОСТИ: снятие любого элемента ядра
    /// обязано делать набор выполнимым (SAT).
    pub fn buildPlainScript(
        self: *UnsatCoreEngine,
        decls: []const u8,
        assertions: []const NamedAssertion,
    ) ![]u8 {
        var aw: std.Io.Writer.Allocating = .init(self.allocator);
        errdefer aw.deinit();
        const w = &aw.writer;
        try w.writeAll("(set-logic ALL)\n");
        try w.writeAll(decls);
        try w.writeAll("\n");
        for (assertions) |a| try w.print("(assert {s})\n", .{a.formula});
        try w.writeAll("(check-sat)\n");
        return aw.toOwnedSlice();
    }

    /// Выполним ли набор. `error.SolverUnknown` — НЕ «sat» и НЕ «unsat»:
    /// неизвестность нельзя выдавать за доказательство (урок #178/#183).
    pub fn isSatisfiable(
        self: *UnsatCoreEngine,
        bridge: *z3.Z3Bridge,
        decls: []const u8,
        assertions: []const NamedAssertion,
    ) !bool {
        const script = try self.buildPlainScript(decls, assertions);
        defer self.allocator.free(script);
        const cap = bridge.executeCapture(script);
        defer self.allocator.free(cap.stdout);
        const t = std.mem.trim(u8, cap.stdout, " \t\r\n");
        if (std.mem.startsWith(u8, t, "unsat")) return false;
        if (std.mem.startsWith(u8, t, "sat")) return true;
        return error.SolverUnknown;
    }

    /// Ядро несовместности ФАЙЛА: трекинг всех ассертов -> `get-unsat-core`.
    pub fn localizeAll(
        self: *UnsatCoreEngine,
        bridge: *z3.Z3Bridge,
        decls: []const u8,
        assertions: []const NamedAssertion,
    ) !UnsatCore {
        const script = try self.buildTrackedScriptNoGoal(decls, assertions);
        defer self.allocator.free(script);
        const cap = bridge.executeCapture(script);
        defer self.allocator.free(cap.stdout);
        return self.parseCore(cap.stdout);
    }

    /// ЖАДНОЕ СОКРАЩЕНИЕ до НЕПРИВОДИМОГО ядра: элемент, без которого набор
    /// остаётся несовместным, в ядро не входит. Результат — новый `UnsatCore`;
    /// `initial` НЕ освобождается (владелец — вызывающий).
    pub fn reduce(
        self: *UnsatCoreEngine,
        bridge: *z3.Z3Bridge,
        decls: []const u8,
        assertions: []const NamedAssertion,
        initial: UnsatCore,
    ) !UnsatCore {
        var keep = std.array_list.Managed(usize).init(self.allocator);
        defer keep.deinit();
        if (initial.is_conflict) {
            for (assertions, 0..) |a, i| {
                if (initial.contains(a.name)) try keep.append(i);
            }
        }
        if (keep.items.len == 0) {
            var empty = std.array_list.Managed([]const u8).init(self.allocator);
            return .{ .allocator = self.allocator, .is_conflict = initial.is_conflict,
                     .conflicting = try empty.toOwnedSlice() };
        }
        var idx: usize = 0;
        while (idx < keep.items.len) {
            var trial = std.array_list.Managed(NamedAssertion).init(self.allocator);
            defer trial.deinit();
            for (keep.items, 0..) |ai, k| if (k != idx) try trial.append(assertions[ai]);
            const sat = self.isSatisfiable(bridge, decls, trial.items) catch true;
            if (!sat) {
                _ = keep.orderedRemove(idx);
            } else {
                idx += 1;
            }
        }
        var out = std.array_list.Managed([]const u8).init(self.allocator);
        errdefer {
            for (out.items) |n| self.allocator.free(n);
            out.deinit();
        }
        for (keep.items) |ai| try out.append(try self.allocator.dupe(u8, assertions[ai].name));
        return .{ .allocator = self.allocator, .is_conflict = true,
                 .conflicting = try out.toOwnedSlice() };
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
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return; // z3 нет
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

test "UNSAT CORE (файл): скрипт БЕЗ цели — все ассерты трекаются, goal отсутствует" {
    var eng = UnsatCoreEngine.init(std.testing.allocator);
    const pres = [_]NamedAssertion{
        .{ .name = "a1", .formula = "(>= min_fee 10)" },
        .{ .name = "a2", .formula = "(<= max_fee 5)" },
    };
    const script = try eng.buildTrackedScriptNoGoal("(declare-const min_fee Int)", &pres);
    defer std.testing.allocator.free(script);
    try std.testing.expect(std.mem.indexOf(u8, script, ":named a1") != null);
    try std.testing.expect(std.mem.indexOf(u8, script, ":named a2") != null);
    try std.testing.expect(std.mem.indexOf(u8, script, ":named goal") == null);
    try std.testing.expect(std.mem.indexOf(u8, script, "(get-unsat-core)") != null);
}

test "UNSAT CORE (РЕАЛЬНЫЙ Z3, файл): ядро без шумового пункта + неприводимость" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return; // z3 нет — честный пропуск
    var eng = UnsatCoreEngine.init(std.testing.allocator);
    const pres = [_]NamedAssertion{
        .{ .name = "a1", .formula = "(>= x 0)" },
        .{ .name = "a2", .formula = "(<= x -1)" },
        .{ .name = "noise", .formula = "(>= y 0)" },
    };
    const decls = "(declare-const x Int)\n(declare-const y Int)";
    var initial = try eng.localizeAll(&bridge, decls, &pres);
    defer initial.deinit();
    try std.testing.expect(initial.is_conflict);
    try std.testing.expect(!initial.contains("noise")); // шум невиновен
    var core = try eng.reduce(&bridge, decls, &pres, initial);
    defer core.deinit();
    try std.testing.expect(core.contains("a1"));
    try std.testing.expect(core.contains("a2"));
    try std.testing.expect(!core.contains("noise"));
    // НЕПРИВОДИМОСТЬ: снятие ЛЮБОГО элемента ядра делает набор выполнимым.
    for (pres, 0..) |a, i| {
        if (!core.contains(a.name)) continue;
        var trial = std.array_list.Managed(NamedAssertion).init(std.testing.allocator);
        defer trial.deinit();
        var drop_i = std.array_list.Managed(usize).init(std.testing.allocator);
        defer drop_i.deinit();
        try drop_i.append(i);
        for (pres, 0..) |b, j| if (j != drop_i.items[0]) try trial.append(b);
        try std.testing.expect(try eng.isSatisfiable(&bridge, decls, trial.items));
    }
}

test "UNSAT CORE (файл): совместный набор даёт SAT и пустое ядро" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    var eng = UnsatCoreEngine.init(std.testing.allocator);
    const pres = [_]NamedAssertion{
        .{ .name = "a1", .formula = "(>= x 0)" },
        .{ .name = "a2", .formula = "(<= x 100)" },
    };
    const decls = "(declare-const x Int)";
    try std.testing.expect(try eng.isSatisfiable(&bridge, decls, &pres));
    var core = try eng.localizeAll(&bridge, decls, &pres);
    defer core.deinit();
    try std.testing.expect(!core.is_conflict);
    try std.testing.expectEqual(@as(usize, 0), core.conflicting.len);
}
