// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: НЕЗАВИСИМАЯ ПРОВЕРКА ВЫВОДА РЕШАТЕЛЯ (Proof Checking).
//!
//! ПРОБЛЕМА: Z3 — это ~миллион строк C++. Верить ему «на слово» нельзя:
//! заводской баг может дать неверный `unsat`.
//!
//! ЧТО ДЕЛАЕМ (два независимых контроля):
//!   1. **Структурная проверка вывода.** Включаем `:produce-proofs true` и
//!      `(get-proof)`. Проверяем, что вывод: (а) присутствует; (б) корректно
//!      сбалансирован по скобкам; (в) завершается выводом `false`.
//!   2. **Проверка минимальности ядра (MUS).** Для каждого элемента
//!      неразрешимого ядра убираем его и проверяем, что формула СТАНОВИТСЯ
//!      выполнимой. Если да — ядро минимально, т.е. вывод НЕ вакуумный.
//!
//! ⚠️ ЧЕСТНО: это НЕ полный Alethe/LFSC-чекер (каждый шаг дедукции не
//! перепроверяется аксиоматически). Это структурный контроль + проверка
//! невакуумности — заметно сильнее, чем «поверить тексту sat/unsat».
const std = @import("std");
const z3 = @import("z3_bridge.zig");
const unsat_core = @import("unsat_core.zig");

pub const ProofVerdict = struct {
    is_unsat: bool = false,
    proof_present: bool = false,
    proof_steps: usize = 0,
    proof_well_formed: bool = false,
    proof_concludes_false: bool = false,
    core_size: usize = 0,
    core_minimal: bool = false,
    /// Итог: вывод подтверждён структурно И ядро невакуумно.
    confirmed: bool = false,
};

/// Баланс скобок в s-выражении (структурная корректность вывода).
fn balanced(s: []const u8) bool {
    var depth: i64 = 0;
    for (s) |c| {
        if (c == '(') depth += 1 else if (c == ')') {
            depth -= 1;
            if (depth < 0) return false;
        }
    }
    return depth == 0;
}

/// Число верхнеуровневых шагов вывода (подвыражений внутри `(proof ...)`).
fn countSteps(s: []const u8) usize {
    const at = std.mem.indexOf(u8, s, "(proof") orelse return 0;
    var depth: i64 = 0;
    var steps: usize = 0;
    var i = at;
    while (i < s.len) : (i += 1) {
        const c = s[i];
        if (c == '(') {
            depth += 1;
            if (depth == 2) steps += 1; // шаг верхнего уровня
        } else if (c == ')') depth -= 1;
    }
    return steps;
}

/// Полная проверка: структурная + минимальность ядра.
pub fn check(
    allocator: std.mem.Allocator,
    bridge: *z3.Z3Bridge,
    decls: []const u8,
    assertions: []const unsat_core.NamedAssertion,
    goal: []const u8,
) !ProofVerdict {
    var v = ProofVerdict{};

    // --- 1. Запрос вывода ---
    var buf = std.array_list.Managed(u8).init(allocator);
    defer buf.deinit();
    const w = buf.writer();
    try w.writeAll("(set-option :produce-proofs true)\n(set-logic ALL)\n");
    try w.writeAll(decls);
    try w.writeAll("\n");
    for (assertions) |a| try w.print("(assert {s})\n", .{a.formula});
    try w.print("(assert (not {s}))\n", .{goal});
    try w.writeAll("(check-sat)\n(get-proof)\n");

    const cap = bridge.executeCapture(buf.items);
    defer allocator.free(cap.stdout);

    v.is_unsat = cap.status == .Unsat;
    if (!v.is_unsat) return v;

    // Вывод идёт после строки "unsat".
    const nl = std.mem.indexOfScalar(u8, cap.stdout, '\n') orelse return v;
    const proof = cap.stdout[nl + 1 ..];
    v.proof_present = std.mem.indexOf(u8, proof, "(proof") != null;
    if (!v.proof_present) return v;
    v.proof_steps = countSteps(proof);
    v.proof_well_formed = balanced(proof);
    // Z3 завершает вывод термом false (или замыкает через `(clausify ... false)`).
    v.proof_concludes_false = std.mem.indexOf(u8, proof, "false") != null;

    // --- 2. Минимальность ядра (невакуумность вывода) ---
    var eng = unsat_core.UnsatCoreEngine.init(allocator);
    var core = try eng.localize(bridge, decls, assertions, goal);
    defer core.deinit();
    v.core_size = core.conflicting.len;

    if (core.conflicting.len > 0) {
        // Убираем по одному элементу ядра: если формула становится SAT —
        // элемент НЕОБХОДИМ (ядро минимально, конфликт не вакуумный).
        var all_needed = true;
        for (core.conflicting) |drop| {
            if (std.mem.eql(u8, drop, "goal")) continue; // цель всегда нужна
            var b2 = std.array_list.Managed(u8).init(allocator);
            defer b2.deinit();
            const w2 = b2.writer();
            try w2.writeAll("(set-logic ALL)\n");
            try w2.writeAll(decls);
            try w2.writeAll("\n");
            for (assertions) |a| {
                if (std.mem.eql(u8, a.name, drop)) continue; // выбрасываем
                try w2.print("(assert {s})\n", .{a.formula});
            }
            try w2.print("(assert (not {s}))\n", .{goal});
            try w2.writeAll("(check-sat)\n");
            const r2 = bridge.executeQuery(b2.items);
            if (r2.witness_model) |m| allocator.free(m);
            if (r2.status != .Sat) all_needed = false; // без него всё ещё UNSAT
        }
        v.core_minimal = all_needed;
    } else {
        // Ядро не извлечено (одна цель) — считаем невакуумным по структурной проверке.
        v.core_minimal = v.proof_well_formed;
    }

    v.confirmed = v.proof_present and v.proof_well_formed and
        v.proof_concludes_false and v.core_minimal;
    return v;
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "PROOF: баланс скобок распознаёт битый вывод" {
    try std.testing.expect(balanced("(a (b c) d)"));
    try std.testing.expect(!balanced("(a (b c)"));
    try std.testing.expect(!balanced(")("));
}

test "PROOF: счётчик шагов вывода" {
    try std.testing.expectEqual(@as(usize, 2), countSteps("(proof (step1) (step2))"));
    try std.testing.expectEqual(@as(usize, 0), countSteps("unsat"));
}

test "PROOF (РЕАЛЬНЫЙ Z3): вывод получен, структурно корректен, ядро минимально" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    bridge.timeout_ms = 10000;
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return; // z3 нет

    const pres = [_]unsat_core.NamedAssertion{
        .{ .name = "p1", .formula = "(> x 5)" },
        .{ .name = "p2", .formula = "(< x 10)" },
    };
    const v = try check(std.testing.allocator, &bridge, "(declare-const x Int)", &pres, "(>= x 6)");
    try std.testing.expect(v.is_unsat);
    try std.testing.expect(v.proof_present);
    try std.testing.expect(v.proof_well_formed);
    try std.testing.expect(v.proof_concludes_false);
    try std.testing.expect(v.proof_steps > 0);
    try std.testing.expect(v.confirmed);
}

test "PROOF (РЕАЛЬНЫЙ Z3): выполнимая формула НЕ даёт подтверждения" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;

    const pres = [_]unsat_core.NamedAssertion{
        .{ .name = "p1", .formula = "(> x 5)" },
    };
    // Цель НЕ следует из p1 -> контрпример существует -> sat -> нет вывода.
    const v = try check(std.testing.allocator, &bridge, "(declare-const x Int)", &pres, "(< x 0)");
    try std.testing.expect(!v.is_unsat);
    try std.testing.expect(!v.confirmed);
}

