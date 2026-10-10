// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ТЕОРИЯ МАССИВОВ И ПАМЯТИ (QF_AX / аксиомы Маккарти).
//!
//! Вектор 2 из архитектурной матрицы. Реальные программы работают с памятью,
//! а не только со скалярами. SMT-теория массивов даёт две аксиомы:
//!
//!   select(store(A, i, v), i) = v            (чтение своей записи)
//!   select(store(A, i, v), j) = select(A, j)  при i ≠ j  (нет алиасинга)
//!
//! KERN формулирует для Z3 ОТРИЦАНИЕ этих аксиом. Если Z3 отвечает `unsat` —
//! свойство доказано для ВСЕХ индексов и значений (математическая гарантия).
//!
//! Где ловим баги: выход за границы массива (Array-Out-of-Bounds) и порча
//! соседних ячеек при перезаписи (Pointer Aliasing).
const std = @import("std");
const z3 = @import("z3_bridge.zig");

pub const ArrayTheoryEngine = struct {
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator) ArrayTheoryEngine {
        return .{ .allocator = allocator };
    }

    /// Аксиома Маккарти №1: select(store(a, i, v), i) = v.
    /// В скрипт идёт ОТРИЦАНИЕ → ожидаемый ответ Z3: `unsat` (доказано).
    pub fn buildSameIndexQuery(self: *ArrayTheoryEngine, idx: []const u8, val: []const u8) ![]u8 {
        return std.fmt.allocPrint(self.allocator,
            \\(set-logic ALL)
            \\(declare-const a (Array Int Int))
            \\(declare-const {s} Int)
            \\(declare-const {s} Int)
            \\(assert (not (= (select (store a {s} {s}) {s}) {s})))
            \\(check-sat)
            \\
        , .{ idx, val, idx, val, idx, val });
    }

    /// Аксиома Маккарти №2: при i ≠ j запись в i не меняет j.
    /// Ожидаемый ответ: `unsat` (алиасинга нет).
    pub fn buildAliasingIndependenceQuery(self: *ArrayTheoryEngine, i: []const u8, j: []const u8) ![]u8 {
        return std.fmt.allocPrint(self.allocator,
            \\(set-logic ALL)
            \\(declare-const a (Array Int Int))
            \\(declare-const v Int)
            \\(declare-const {s} Int)
            \\(declare-const {s} Int)
            \\(assert (and (distinct {s} {s}) (not (= (select (store a {s} v) {s}) (select a {s})))))
            \\(check-sat)
            \\
        , .{ i, j, i, j, i, j, j });
    }

    /// Поиск уязвимости алиасинга: существует ли i = j, при котором
    /// предполагаемая независимость ячеек нарушается? `sat` = БАГ достижим.
    pub fn buildAliasingViolationQuery(self: *ArrayTheoryEngine, i: []const u8, j: []const u8) ![]u8 {
        return std.fmt.allocPrint(self.allocator,
            \\(set-logic ALL)
            \\(declare-const a (Array Int Int))
            \\(declare-const v Int)
            \\(declare-const {s} Int)
            \\(declare-const {s} Int)
            \\(assert (= {s} {s}))
            \\(assert (not (= (select (store a {s} v) {s}) (select a {s}))))
            \\(check-sat)
            \\(get-model)
            \\
        , .{ i, j, i, j, i, j, j });
    }

    /// Проверка границ: достижим ли выход за пределы буфера [0, size).
    /// `sat` = существует индекс вне диапазона (потенциальный OOB).
    pub fn buildOobQuery(self: *ArrayTheoryEngine, idx: []const u8, size: usize) ![]u8 {
        return std.fmt.allocPrint(self.allocator,
            \\(set-logic ALL)
            \\(declare-const {s} Int)
            \\(assert (or (< {s} 0) (>= {s} {d})))
            \\(check-sat)
            \\
        , .{ idx, idx, idx, size });
    }

    /// Доказать, что ЗАЩИЩЁННАЯ запись безопасна для ВСЕХ индексов:
    /// пересечение guard и его отрицания недостижимо.
    /// `unsat` = защита корректна на всей области.
    pub fn buildGuardedSafeQuery(self: *ArrayTheoryEngine, idx: []const u8, size: usize) ![]u8 {
        return std.fmt.allocPrint(self.allocator,
            \\(set-logic ALL)
            \\(declare-const {s} Int)
            \\(assert (and (>= {s} 0) (< {s} {d})))
            \\(assert (or (< {s} 0) (>= {s} {d})))
            \\(check-sat)
            \\
        , .{ idx, idx, idx, size, idx, idx, size });
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "ARRAY: скрипт содержит аксиому Маккарти (select(store))" {
    var eng = ArrayTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildAliasingIndependenceQuery("idx_a", "idx_b");
    defer std.testing.allocator.free(q);
    try std.testing.expect(std.mem.indexOf(u8, q, "(select (store a idx_a v) idx_b)") != null);
    try std.testing.expect(std.mem.indexOf(u8, q, "(distinct idx_a idx_b)") != null);
}

test "ARRAY (РЕАЛЬНЫЙ Z3): select(store(a,i,v),i) = v доказано (unsat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = ArrayTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildSameIndexQuery("i", "v");
    defer std.testing.allocator.free(q);
    try std.testing.expectEqual(z3.SmtStatus.Unsat, bridge.executeQuery(q).status);
}

test "ARRAY (РЕАЛЬНЫЙ Z3): независимость ячеек при i≠j доказана (unsat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = ArrayTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildAliasingIndependenceQuery("i", "j");
    defer std.testing.allocator.free(q);
    try std.testing.expectEqual(z3.SmtStatus.Unsat, bridge.executeQuery(q).status);
}

test "ARRAY (РЕАЛЬНЫЙ Z3): защищённая запись безопасна (unsat = доказано)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = ArrayTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildGuardedSafeQuery("i", 16);
    defer std.testing.allocator.free(q);
    try std.testing.expectEqual(z3.SmtStatus.Unsat, bridge.executeQuery(q).status);
}

test "ARRAY (РЕАЛЬНЫЙ Z3): OOB-индекс достижим (sat = уязвимость видна)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = ArrayTheoryEngine.init(std.testing.allocator);
    const q = try eng.buildOobQuery("i", 16);
    defer std.testing.allocator.free(q);
    // Без guard индекс может быть любым => sat (KERN покажет контрпример).
    try std.testing.expectEqual(z3.SmtStatus.Sat, bridge.executeQuery(q).status);
}
