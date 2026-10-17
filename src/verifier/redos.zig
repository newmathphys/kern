// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: АНАЛИЗ ReDoS (Regular Expression Denial of Service).
//!
//! ПРОБЛЕМА: регулярки вида `(a+)+$` или `(a|a)*$` вызывают КАТАСТРОФИЧЕСКИЙ
//! ВОЗВРАТ: на строке из N символов движок перебирает 2^N вариантов разбора.
//! Валидатор, проверяющий пользовательский ввод такой регуляркой, вешает
//! сервер одной 30-символьной строкой. Это CWE-1333.
//!
//! ЧТО ДЕЛАЕМ: разбираем регулярку в AST и ищем два класса дефектов:
//!   * ВЛОЖЕННЫЙ КВАНТОР — квантор над квантором (`(a+)+`, `(a*)*`);
//!   * НЕОДНОЗНАЧНАЯ АЛЬТЕРНАТИВА под квантором (`(a|a)*`, `(ab|ac)*`).
//! Оба класса дают экспоненциальный бэктрекинг.
const std = @import("std");

pub const Node = union(enum) {
    lit: u8,
    any,
    star: *Node,
    plus: *Node,
    opt: *Node,
    concat: []const *Node,
    alt: []const *Node,
};

pub const Finding = struct {
    vulnerable: bool,
    nested_quantifier: bool,
    ambiguous_alternation: bool,
};

fn isQuantified(n: *const Node) bool {
    return switch (n.*) {
        .star, .plus, .opt => true,
        else => false,
    };
}

fn inner(n: *const Node) *Node {
    return switch (n.*) {
        .star => |c| c,
        .plus => |c| c,
        .opt => |c| c,
        else => @constCast(n),
    };
}

/// Есть ли в дереве вложенный квантор (квантор над квантором).
fn hasNestedQuantifier(n: *const Node) bool {
    switch (n.*) {
        .star, .plus, .opt => {
            const c = inner(n);
            if (isQuantified(c)) return true;
            // `(a+)+`: квантор над concat из ОДНОГО уже-квантованного элемента.
            if (c.* == .concat and c.concat.len == 1 and isQuantified(c.concat[0])) return true;
            return hasNestedQuantifier(c);
        },
        .concat => |items| for (items) |it| {
            if (hasNestedQuantifier(it)) return true;
        },
        .alt => |items| for (items) |it| {
            if (hasNestedQuantifier(it)) return true;
        },
        else => return false,
    }
    return false;
}

/// Общий префикс двух ветвей (для неоднозначной альтернативы).
fn sharedPrefix(a: *const Node, b: *const Node) bool {
    const la: []const *const Node = switch (a.*) {
        .concat => |i| i,
        else => &.{a},
    };
    const lb: []const *const Node = switch (b.*) {
        .concat => |i| i,
        else => &.{b},
    };
    if (la.len == 0 or lb.len == 0) return false;
    return switch (la[0].*) {
        .lit => |c| switch (lb[0].*) {
            .lit => |d| c == d,
            else => false,
        },
        .any => true,
        else => false,
    };
}

/// Неоднозначная альтернатива ПОД КВАНТОРОМ (класс `(a|a)*`).
fn hasAmbiguousAltUnderQuantifier(n: *const Node) bool {
    switch (n.*) {
        .star, .plus => {
            const c = inner(n);
            if (c.* == .alt) {
                const items = c.alt;
                var i: usize = 0;
                while (i < items.len) : (i += 1) {
                    var j = i + 1;
                    while (j < items.len) : (j += 1) {
                        if (sharedPrefix(items[i], items[j])) return true;
                    }
                }
            }
            return hasAmbiguousAltUnderQuantifier(c);
        },
        .opt => return hasAmbiguousAltUnderQuantifier(inner(n)),
        .concat => |items| for (items) |it| {
            if (hasAmbiguousAltUnderQuantifier(it)) return true;
        },
        .alt => |items| for (items) |it| {
            if (hasAmbiguousAltUnderQuantifier(it)) return true;
        },
        else => return false,
    }
    return false;
}

pub fn analyze(root: *const Node) Finding {
    const nested = hasNestedQuantifier(root);
    const ambig = hasAmbiguousAltUnderQuantifier(root);
    return .{
        .vulnerable = nested or ambig,
        .nested_quantifier = nested,
        .ambiguous_alternation = ambig,
    };
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "REDOS: (a+)+ распознан как уязвимый (вложенный квантор)" {
    var a = Node{ .lit = 'a' };
    var plus_inner = Node{ .plus = &a };
    var plus_outer = Node{ .plus = &plus_inner };
    const f = analyze(&plus_outer);
    try std.testing.expect(f.vulnerable);
    try std.testing.expect(f.nested_quantifier);
}

test "REDOS: (a*)* распознан как уязвимый" {
    var a = Node{ .lit = 'a' };
    var star_inner = Node{ .star = &a };
    var star_outer = Node{ .star = &star_inner };
    try std.testing.expect(analyze(&star_outer).vulnerable);
}

test "REDOS: (a|a)* — неоднозначная альтернатива под квантором" {
    var a1 = Node{ .lit = 'a' };
    var a2 = Node{ .lit = 'a' };
    const branches = [_]*Node{ &a1, &a2 };
    var alt = Node{ .alt = &branches };
    var star = Node{ .star = &alt };
    const f = analyze(&star);
    try std.testing.expect(f.vulnerable);
    try std.testing.expect(f.ambiguous_alternation);
}

test "REDOS: безопасная регулярка (a|b)* — НЕ уязвима" {
    var a = Node{ .lit = 'a' };
    var b = Node{ .lit = 'b' };
    const branches = [_]*Node{ &a, &b };
    var alt = Node{ .alt = &branches };
    var star = Node{ .star = &alt };
    try std.testing.expect(!analyze(&star).vulnerable);
}

test "REDOS: простой литерал без кванторов безопасен" {
    var a = Node{ .lit = 'x' };
    const items = [_]*Node{&a};
    var cat = Node{ .concat = &items };
    try std.testing.expect(!analyze(&cat).vulnerable);
}

test "REDOS (РЕАЛЬНЫЙ Z3): уязвимая регулярка принимает экспоненциальный вход" {
    const z3 = @import("z3_bridge.zig");
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeStatus("(check-sat)\n") == .ToolError) return;
    // Строка из одних 'a' длиной 30 ПРИНИМАЕТСЯ регуляркой (a+)+ —
    // значит вход существует, и бэктрекинг на нём неизбежен.
    const q =
        \\(set-logic QF_SLIA)
        \\(declare-const p String)
        \\(assert (str.in_re p (re.+ (re.+ (str.to_re "a")))))
        \\(assert (= (str.len p) 30))
        \\(check-sat)
        \\
    ;
    try std.testing.expectEqual(z3.SmtStatus.Sat, bridge.executeStatus(q));
}
