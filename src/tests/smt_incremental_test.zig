// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ИНКРЕМЕНТАЛЬНЫЙ SMT (push/pop) — изоляция контекста решателя.
//!
//! Зачем: при верификации ПАЧКИ мутантов формулы отличаются на 5–10 %.
//! Пересоздавать контекст Z3 с нуля расточительно. Команды `(push 1)` /
//! `(pop 1)` позволяют загрузить базовую спецификацию ОДИН раз, а затем
//! накладывать дельты, откатывая состояние назад.
//!
//! Что проверяем (главное — КОРРЕКТНОСТЬ):
//!   * контекст предыдущего мутанта НЕ протекает в следующий;
//!   * после `(pop 1)` ограничения действительно сняты;
//!   * ложных `proved` (unsat) из-за загрязнения контекста НЕТ;
//!   * один процесс с N запросами быстрее, чем N отдельных процессов.
const std = @import("std");
const z3 = @import("../verifier/z3_bridge.zig");

/// Разбирает ВСЕ строки статуса из вывода решателя (sat/unsat/unknown).
fn parseAll(allocator: std.mem.Allocator, out: []const u8) ![]z3.SmtStatus {
    var list = std.ArrayList(z3.SmtStatus).init(allocator);
    errdefer list.deinit();
    var it = std.mem.tokenizeAny(u8, out, " \t\r\n()");
    while (it.next()) |tok| {
        if (std.mem.eql(u8, tok, "sat")) try list.append(.Sat) else if (std.mem.eql(u8, tok, "unsat")) try list.append(.Unsat) else if (std.mem.eql(u8, tok, "unknown")) try list.append(.Unknown);
    }
    return list.toOwnedSlice();
}

test "SMT push/pop: контекст ИЗОЛИРОВАН (нет протечки между мутантами)" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return; // z3 нет

    const script =
        \\(set-logic ALL)
        \\(declare-const x Int)
        \\(push 1)
        \\(assert (> x 5))
        \\(check-sat)
        \\(pop 1)
        \\(push 1)
        \\(assert (< x 0))
        \\(check-sat)
        \\(pop 1)
        \\(push 1)
        \\(assert (and (> x 5) (< x 0)))
        \\(check-sat)
        \\(pop 1)
        \\(check-sat)
        \\
    ;
    const cap = bridge.executeCapture(script);
    defer std.testing.allocator.free(cap.stdout);
    const st = try parseAll(std.testing.allocator, cap.stdout);
    defer std.testing.allocator.free(st);

    try std.testing.expectEqual(@as(usize, 4), st.len);
    try std.testing.expectEqual(z3.SmtStatus.Sat, st[0]); // x>5 выполнимо
    try std.testing.expectEqual(z3.SmtStatus.Sat, st[1]); // контекст ЧИСТ: x>5 снято
    try std.testing.expectEqual(z3.SmtStatus.Unsat, st[2]); // локальное противоречие
    try std.testing.expectEqual(z3.SmtStatus.Sat, st[3]); // после pop ограничений нет
}

test "SMT push/pop: пачка из 50 «мутантов» — нет ложных proved" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;

    var buf = std.ArrayList(u8).init(std.testing.allocator);
    defer buf.deinit();
    const w = buf.writer();
    try w.writeAll("(set-logic ALL)\n(declare-const x Int)\n(assert (>= x 0))\n"); // база
    var i: usize = 0;
    while (i < 50) : (i += 1) {
        // Чётные мутанты совместимы с базой (sat), нечётные противоречат (unsat).
        try w.print("(push 1)\n(assert {s})\n(check-sat)\n(pop 1)\n", .{
            if (i % 2 == 0) "(<= x 10)" else "(< x 0)",
        });
    }
    const cap = bridge.executeCapture(buf.items);
    defer std.testing.allocator.free(cap.stdout);
    const st = try parseAll(std.testing.allocator, cap.stdout);
    defer std.testing.allocator.free(st);

    try std.testing.expectEqual(@as(usize, 50), st.len);
    for (st, 0..) |s, k| {
        const expect: z3.SmtStatus = if (k % 2 == 0) .Sat else .Unsat;
        try std.testing.expectEqual(expect, s);
    }
}

test "SMT push/pop: 30 запросов в ОДНОМ процессе быстрее 30 отдельных" {
    var bridge = z3.Z3Bridge.init(std.testing.allocator);
    if (bridge.executeQuery("(check-sat)\n").status == .ToolError) return;

    // (а) 30 отдельных процессов
    var t_sep = try std.time.Timer.start();
    var k: usize = 0;
    while (k < 30) : (k += 1) {
        const r = bridge.executeQuery("(set-logic ALL)\n(declare-const x Int)\n(assert (> x 0))\n(check-sat)\n");
        if (r.witness_model) |m| std.testing.allocator.free(m);
    }
    const sep_ms = t_sep.read() / std.time.ns_per_ms;

    // (б) один процесс, 30 запросов через push/pop
    var buf = std.ArrayList(u8).init(std.testing.allocator);
    defer buf.deinit();
    const w = buf.writer();
    try w.writeAll("(set-logic ALL)\n(declare-const x Int)\n");
    k = 0;
    while (k < 30) : (k += 1) {
        try w.writeAll("(push 1)\n(assert (> x 0))\n(check-sat)\n(pop 1)\n");
    }
    var t_inc = try std.time.Timer.start();
    const cap = bridge.executeCapture(buf.items);
    defer std.testing.allocator.free(cap.stdout);
    const inc_ms = t_inc.read() / std.time.ns_per_ms;

    std.debug.print("\n[ИНКРЕМЕНТ] 30 отдельных процессов: {d} мс; один процесс: {d} мс\n", .{ sep_ms, inc_ms });
    // Один процесс не должен быть МЕДЛЕННЕЕ (обычно заметно быстрее).
    try std.testing.expect(inc_ms <= sep_ms);
}
