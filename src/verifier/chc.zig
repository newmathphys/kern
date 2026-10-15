// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: ИНВАРИАНТЫ ЦИКЛОВ ЧЕРЕЗ CHC / HORN CLAUSES (вектор 1).
//!
//! Барьер символьной верификации — произвольные циклы `while` и рекурсия.
//! Разворачивать цикл бесконечно нельзя. Вместо этого KERN кодирует цикл
//! системой Constrained Horn Clauses и отдаёт её Z3 (движок SPACER), который
//! СИНТЕЗИРУЕТ индуктивный инвариант.
//!
//! Соглашение о вердикте (стандарт CHC-COMP):
//!   * `sat`   — существует индуктивный инвариант, доказывающий post
//!               → свойство ДОКАЗАНО для всех запусков (в т.ч. бесконечных);
//!   * `unsat` — инварианта не существует → bad-состояние ДОСТИЖИМО (БАГ);
//!   * `unknown`/`Timeout` — решатель не справился (KERN не открывает Врата).
//!
//! Где ловим баги: циклы со сложными счётчиками, где обычное разворачивание
//! по таймауту «сдаётся», а CHC доказывает (или опровергает) за миллисекунды.
const std = @import("std");
const z3 = @import("z3_bridge.zig");

pub const ChcEngine = struct {
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator) ChcEngine {
        return .{ .allocator = allocator };
    }

    /// Кодирование цикла `while (guard) { x = step; }` с постусловием `post`.
    ///
    ///   inv(init)                       — вход в цикл
    ///   inv(x) ∧ guard(x) → inv(step(x)) — индуктивность
    ///   inv(x) ∧ ¬guard(x) → post(x)     — постусловие на выходе
    ///
    /// Переменная цикла — `x` (Int).
    pub fn buildHornQuery(
        self: *ChcEngine,
        init_cond: []const u8,
        guard: []const u8,
        step: []const u8,
        post: []const u8,
    ) ![]u8 {
        return std.fmt.allocPrint(self.allocator,
            \\(set-logic HORN)
            \\(declare-fun inv (Int) Bool)
            \\(assert (forall ((x Int)) (=> {s} (inv x))))
            \\(assert (forall ((x Int)) (=> (and (inv x) {s}) (inv {s}))))
            \\(assert (forall ((x Int)) (=> (and (inv x) (not {s})) {s})))
            \\(check-sat)
            \\
        , .{ init_cond, guard, step, guard, post });
    }

    /// Синтез инварианта и вердикт по свойству.
    pub fn proveLoopSafety(
        self: *ChcEngine,
        bridge: *z3.Z3Bridge,
        init_cond: []const u8,
        guard: []const u8,
        step: []const u8,
        post: []const u8,
    ) z3.SmtStatus {
        const q = self.buildHornQuery(init_cond, guard, step, post) catch return .ToolError;
        defer self.allocator.free(q);
        return bridge.executeQuery(q).status;
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "CHC: скрипт содержит индуктивную схему (inv, forall, HORN)" {
    var eng = ChcEngine.init(std.testing.allocator);
    const q = try eng.buildHornQuery("(= x 0)", "(< x 10)", "(+ x 1)", "(>= x 10)");
    defer std.testing.allocator.free(q);
    try std.testing.expect(std.mem.indexOf(u8, q, "(set-logic HORN)") != null);
    try std.testing.expect(std.mem.indexOf(u8, q, "(declare-fun inv (Int) Bool)") != null);
    try std.testing.expect(std.mem.indexOf(u8, q, "forall") != null);
}

test "CHC (РЕАЛЬНЫЙ Z3): цикл x:=0; while(x<10) x++; даёт x>=10 — ДОКАЗАНО (sat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.timeout_ms = 10000;
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = ChcEngine.init(std.testing.allocator);
    const st = eng.proveLoopSafety(&bridge, "(= x 0)", "(< x 10)", "(+ x 1)", "(>= x 10)");
    try std.testing.expectEqual(z3.SmtStatus.Sat, st);
}

test "CHC (РЕАЛЬНЫЙ Z3): ложное постусловие x<5 — инварианта НЕТ (unsat = БАГ)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.timeout_ms = 10000;
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = ChcEngine.init(std.testing.allocator);
    const st = eng.proveLoopSafety(&bridge, "(= x 0)", "(< x 10)", "(+ x 1)", "(< x 5)");
    try std.testing.expectEqual(z3.SmtStatus.Unsat, st);
}

test "CHC (РЕАЛЬНЫЙ Z3): инвариант чётности x:=0; while(x<10) x+=2 — чётность ДОКАЗАНА" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.timeout_ms = 10000;
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;
    var eng = ChcEngine.init(std.testing.allocator);
    // post: (= (mod x 2) 0) — чётность сохраняется на выходе
    const st = eng.proveLoopSafety(&bridge, "(= x 0)", "(< x 10)", "(+ x 2)", "(= (mod x 2) 0)");
    try std.testing.expectEqual(z3.SmtStatus.Sat, st);
}
