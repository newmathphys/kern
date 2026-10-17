// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: НЕЛИНЕЙНАЯ АРИФМЕТИКА (QF_NRA) И КВАНТОРЫ (E-matching).
//!
//! Два барьера, до которых обычные верификаторы не добираются:
//!
//! 1. **QF_NRA.** Реальный код физических систем, графики, ML и робототехники
//!    полон делений, корней, тригонометрии и экспонент. Решение нелинейных
//!    уравнений над ℝ алгоритмически тяжело (цилиндрическая алгебраическая
//!    декомпозиция, CAD). Z3 решает это движком NLSAT.
//!    Где ловим баги: накопление погрешности, деление на околонулевую дельту.
//!
//! 2. **Кванторы.** Контракты для коллекций пишут как `∀x. A[x] > 0`.
//!    Логика первого порядка с кванторами в общем случае НЕРАЗРЕШИМА;
//!    решатели используют эвристики E-matching (триггеры).
//!    Где ловим баги: контракты, уводящие движок в бесконечный перебор
//!    подстановок (Matching Loop DoS) — KERN ограничивает это таймаутом.
const std = @import("std");
const z3 = @import("z3_bridge.zig");

pub const NraEngine = struct {
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator) NraEngine {
        return .{ .allocator = allocator };
    }

    /// ∃-проверка: есть ли вещественные x,y, при которых формула истинна.
    pub fn check(self: *NraEngine, bridge: *z3.Z3Bridge, formula: []const u8) z3.SmtStatus {
        const q = std.fmt.allocPrint(self.allocator,
            \\(set-logic QF_NRA)
            \\(declare-const x Real)
            \\(declare-const y Real)
            \\(assert {s})
            \\(check-sat)
            \\
        , .{formula}) catch return .ToolError;
        defer self.allocator.free(q);
        return bridge.executeStatus(q);
    }

    /// ∀-проверка: ищем контрпример ¬φ.
    /// `unsat` = свойство доказано для ВСЕХ вещественных x,y.
    pub fn proveForAll(self: *NraEngine, bridge: *z3.Z3Bridge, formula: []const u8) z3.SmtStatus {
        const q = std.fmt.allocPrint(self.allocator,
            \\(set-logic QF_NRA)
            \\(declare-const x Real)
            \\(declare-const y Real)
            \\(assert (not {s}))
            \\(check-sat)
            \\
        , .{formula}) catch return .ToolError;
        defer self.allocator.free(q);
        return bridge.executeStatus(q);
    }
};

pub const QuantEngine = struct {
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator) QuantEngine {
        return .{ .allocator = allocator };
    }

    /// Квантор с ЯВНЫМ триггером (`:pattern`) — рекомендация SMT-LIB для
    /// E-matching. Триггер предотвращает неконтролируемые подстановки.
    pub fn buildForallWithTrigger(
        self: *QuantEngine,
        decls: []const u8,
        var_name: []const u8,
        sort: []const u8,
        body: []const u8,
        trigger: []const u8,
    ) ![]u8 {
        return std.fmt.allocPrint(self.allocator,
            \\(set-logic ALL)
            \\{s}
            \\(assert (forall (({s} {s})) (! {s} :pattern ({s}))))
            \\(check-sat)
            \\
        , .{ decls, var_name, sort, body, trigger });
    }

    /// Квантор БЕЗ триггера (Z3 подберёт сам) — источник Matching Loop DoS.
    pub fn buildForallNoTrigger(
        self: *QuantEngine,
        decls: []const u8,
        var_name: []const u8,
        sort: []const u8,
        body: []const u8,
    ) ![]u8 {
        return std.fmt.allocPrint(self.allocator,
            \\(set-logic ALL)
            \\{s}
            \\(assert (forall (({s} {s})) {s}))
            \\(check-sat)
            \\
        , .{ decls, var_name, sort, body });
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "NRA: x² < 0 неразрешимо (квадрат вещественного неотрицателен)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    var eng = NraEngine.init(std.testing.allocator);
    try std.testing.expectEqual(z3.SmtStatus.Unsat, eng.check(&bridge, "(< (* x x) 0)"));
}

test "NRA (∀): x² + y² ≥ 0 доказано для ВСЕХ вещественных" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    var eng = NraEngine.init(std.testing.allocator);
    try std.testing.expectEqual(z3.SmtStatus.Unsat,
        eng.proveForAll(&bridge, "(>= (+ (* x x) (* y y)) 0)"));
}

test "NRA: единичный круг — точка (0.9, 0) внутри (sat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    var eng = NraEngine.init(std.testing.allocator);
    try std.testing.expectEqual(z3.SmtStatus.Sat,
        eng.check(&bridge, "(and (= y 0) (< (* x x) 1) (> x 0.5))"));
}

test "NRA: x² + y² > 2 недоказуемо (контрпример x=y=0 есть)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    var eng = NraEngine.init(std.testing.allocator);
    try std.testing.expectEqual(z3.SmtStatus.Sat,
        eng.proveForAll(&bridge, "(> (+ (* x x) (* y y)) 2)"));
}

test "QUANT: с явным триггером — противоречивый контракт (unsat)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    // ∀x. f(x) > x  ∧  f(0) = 0  — противоречие.
    const q =
        \\(set-logic ALL)
        \\(declare-fun f (Int) Int)
        \\(assert (forall ((x Int)) (! (> (f x) x) :pattern ((f x)))))
        \\(assert (= (f 0) 0))
        \\(check-sat)
        \\
    ;
    try std.testing.expectEqual(z3.SmtStatus.Unsat, bridge.executeStatus(q));
}

test "QUANT: квантор без триггера ограничен таймаутом (Matching Loop обезврежен)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.timeout_ms = 3000; // жёсткий предел
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    var eng = QuantEngine.init(std.testing.allocator);
    const q = try eng.buildForallNoTrigger(
        "(declare-fun g (Int Int) Int)", "x", "Int",
        "(= (g x x) (+ x 1))");
    defer std.testing.allocator.free(q);
    const st = bridge.executeStatus(q);
    // Любой исход, КРОМЕ падения/зависания: таймаут-убийца гарантирует
    // завершение, а Врата при Timeout/Unknown НЕ открываются.
    try std.testing.expect(st == .Sat or st == .Unsat or st == .Unknown or st == .Timeout);
    std.debug.print("\n[QUANT] без триггера: {s} (таймаут {d} мс — Matching Loop обезврежен)\n", .{
        @tagName(st), bridge.timeout_ms,
    });
}
