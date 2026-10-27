// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.

//! KERN: ФАЙЛОВЫЙ ВХОД ДЛЯ НАТИВНЫХ ТЕОРИЙ (`kernc theory <file>`).
//!
//! ЗАЧЕМ. Нативные Zig-движки `src/verifier/*.zig` существовали, но `kernc
//! audit` гонял их только на ЗАХАРДКОЖЕННЫХ строках ВНУТРИ исходника. То есть
//! возможности ядра нельзя было применить к внешнему входу вообще. Здесь
//! каждая теория принимает ПРОИЗВОЛЬНЫЙ вход из файла.
//!
//! ФОРМАТ (строка = одна проверка; `#` — комментарий):
//!   arrays oob <idx> <size>          выход за границы ДОСТИЖИМ?
//!   arrays guarded <idx> <size>      защита корректна на ВСЕЙ области?
//!   arrays same_index <idx> <val>    аксиома Маккарти №1 (select∘store)?
//!   absint join|widen|narrow <a_lo> <a_hi> <b_lo> <b_hi>
//!   dtmc stochastic <n> <n*n значений>
//!   dtmc reach <n> <target> <n*n значений>
//!
//! ЧЕСТНАЯ ГРАНИЦА: это ЯВНЫЙ формат (не «любой текст»). Разбираются ровно
//! перечисленные команды; всё прочее — `SKIP` С ПРИЧИНОЙ.
const std = @import("std");
const z3 = @import("z3_bridge.zig");
const array_theory = @import("array_theory.zig");
const absint = @import("abstract_interp.zig");
const dtmc_mod = @import("dtmc.zig");

pub const Status = enum { proven, refuted, skip, value };

pub const Outcome = struct {
    name: []const u8,
    status: Status,
    reason: []const u8 = "",
};

pub const Report = struct {
    outcomes: std.ArrayListUnmanaged(Outcome) = .empty,
    proven: usize = 0,
    refuted: usize = 0,
    skipped: usize = 0,
    values: usize = 0,

    pub fn deinit(self: *Report, alloc: std.mem.Allocator) void {
        self.outcomes.deinit(alloc);
    }
};

fn toks(line: []const u8, buf: *[16][]const u8) []const []const u8 {
    var n: usize = 0;
    var it = std.mem.tokenizeAny(u8, line, " \t");
    while (it.next()) |t| {
        if (n >= buf.len) break;
        buf[n] = t;
        n += 1;
    }
    return buf[0..n];
}

fn intervalSmt(arena: std.mem.Allocator, iv: absint.Interval) ![]const u8 {
    if (iv.isEmpty()) return "пусто";
    return std.fmt.allocPrint(arena, "[{d}, {d}]", .{ iv.lo, iv.hi });
}

/// Выполнить файл спецификаций. Возвращает ИЗМЕРЕНИЯ, ничего не додумывая.
pub fn run(alloc: std.mem.Allocator, bridge: *z3.Z3Bridge, text: []const u8) !Report {
    var rep = Report{};
    var arena_state = std.heap.ArenaAllocator.init(alloc);
    defer arena_state.deinit();
    const arena = arena_state.allocator();

    var it = std.mem.splitScalar(u8, text, '\n');
    var lineno: usize = 0;
    while (it.next()) |raw| {
        lineno += 1;
        const line = std.mem.trim(u8, raw, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;
        var buf: [16][]const u8 = undefined;
        const t = toks(line, &buf);
        if (t.len < 2) {
            try rep.outcomes.append(alloc, .{ .name = try std.fmt.allocPrint(arena, "строка {d}", .{lineno}), .status = .skip, .reason = "нужно минимум 2 токена" });
            rep.skipped += 1;
            continue;
        }
        const spec = try std.fmt.allocPrint(arena, "строка {d}: {s} {s}", .{ lineno, t[0], t[1] });
        try dispatch(alloc, arena, bridge, &rep, t, spec);
    }
    return rep;
}

fn verdictFromZ3(st: z3.SmtStatus) ?bool {
    return switch (st) {
        .Unsat => true,
        .Sat => false,
        else => null,
    };
}

fn dispatch(alloc: std.mem.Allocator, arena: std.mem.Allocator, bridge: *z3.Z3Bridge, rep: *Report, t: []const []const u8, spec: []const u8) !void {
    if (std.mem.eql(u8, t[0], "arrays")) {
        if (t.len < 4) {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "arrays: нужны <вид> <аргументы>" });
            rep.skipped += 1;
            return;
        }
        var eng = array_theory.ArrayTheoryEngine.init(arena);
        var script: []u8 = undefined;
        var expectation: []const u8 = undefined;
        if (std.mem.eql(u8, t[1], "oob")) {
            const size = std.fmt.parseInt(usize, t[3], 10) catch {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "arrays oob: размер не число" });
                rep.skipped += 1;
                return;
            };
            script = try eng.buildOobQuery(t[2], size);
            expectation = "sat = выход за границы ДОСТИЖИМ (риск), unsat = недостижим";
        } else if (std.mem.eql(u8, t[1], "guarded")) {
            const size = std.fmt.parseInt(usize, t[3], 10) catch {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "arrays guarded: размер не число" });
                rep.skipped += 1;
                return;
            };
            script = try eng.buildGuardedSafeQuery(t[2], size);
            expectation = "unsat = защита корректна на ВСЕЙ области";
        } else if (std.mem.eql(u8, t[1], "same_index")) {
            script = try eng.buildSameIndexQuery(t[2], t[3]);
            expectation = "unsat = аксиома Маккарти №1 держится";
        } else {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "arrays: неизвестный вид" });
            rep.skipped += 1;
            return;
        }
        const ok = verdictFromZ3(bridge.executeStatus(script));
        if (ok == null) {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "решатель не ответил (таймаут/ошибка)" });
            rep.skipped += 1;
            return;
        }
        if (ok.?) {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .proven, .reason = expectation });
            rep.proven += 1;
        } else {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .refuted, .reason = expectation });
            rep.refuted += 1;
        }
        return;
    }

    if (std.mem.eql(u8, t[0], "absint")) {
        if (t.len < 6) {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "absint: нужны <оп> a_lo a_hi b_lo b_hi" });
            rep.skipped += 1;
            return;
        }
        const alo = std.fmt.parseInt(i64, t[2], 10) catch return skipNum(alloc, rep, spec, "a_lo");
        const ahi = std.fmt.parseInt(i64, t[3], 10) catch return skipNum(alloc, rep, spec, "a_hi");
        const blo = std.fmt.parseInt(i64, t[4], 10) catch return skipNum(alloc, rep, spec, "b_lo");
        const bhi = std.fmt.parseInt(i64, t[5], 10) catch return skipNum(alloc, rep, spec, "b_hi");
        const a = absint.Interval{ .lo = alo, .hi = ahi };
        const b = absint.Interval{ .lo = blo, .hi = bhi };
        const r = if (std.mem.eql(u8, t[1], "join")) absint.Interval.join(a, b) else if (std.mem.eql(u8, t[1], "widen")) absint.Interval.widen(a, b) else if (std.mem.eql(u8, t[1], "narrow")) absint.Interval.narrow(a, b) else {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "absint: неизвестная операция" });
            rep.skipped += 1;
            return;
        };
        try rep.outcomes.append(alloc, .{ .name = spec, .status = .value, .reason = try intervalSmt(arena, r) });
        rep.values += 1;
        return;
    }

    if (std.mem.eql(u8, t[0], "dtmc")) {
        if (t.len < 4) {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "dtmc: нужны <вид> <n> ..." });
            rep.skipped += 1;
            return;
        }
        const n = std.fmt.parseInt(usize, t[2], 10) catch return skipNum(alloc, rep, spec, "n");
        if (n == 0 or n > 64) {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "dtmc: n вне 1..64" });
            rep.skipped += 1;
            return;
        }
        var d = try dtmc_mod.Dtmc.init(arena, n);
        defer d.deinit();
        if (std.mem.eql(u8, t[1], "stochastic")) {
            if (t.len < 3 + n * n) {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "dtmc stochastic: мало значений матрицы" });
                rep.skipped += 1;
                return;
            }
            var k: usize = 3;
            var i: usize = 0;
            while (i < n) : (i += 1) {
                var j: usize = 0;
                while (j < n) : (j += 1) {
                    const p = std.fmt.parseFloat(f64, t[k]) catch return skipNum(alloc, rep, spec, "вероятность");
                    k += 1;
                    d.set(i, j, p);
                }
            }
            const st = d.isStochastic();
            try rep.outcomes.append(alloc, .{ .name = spec, .status = if (st) .proven else .refuted, .reason = if (st) "матрица стохастическая (каждая строка суммируется в 1)" else "строка НЕ суммируется в 1" });
            if (st) rep.proven += 1 else rep.refuted += 1;
            return;
        }
        if (std.mem.eql(u8, t[1], "reach")) {
            if (t.len < 4 + n * n) {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "dtmc reach: мало значений матрицы" });
                rep.skipped += 1;
                return;
            }
            var k: usize = 4;
            var i: usize = 0;
            while (i < n) : (i += 1) {
                var j: usize = 0;
                while (j < n) : (j += 1) {
                    const p = std.fmt.parseFloat(f64, t[k]) catch return skipNum(alloc, rep, spec, "вероятность");
                    k += 1;
                    d.set(i, j, p);
                }
            }
            const tgt = std.fmt.parseInt(usize, t[3], 10) catch return skipNum(alloc, rep, spec, "целевое состояние");
            if (tgt >= n) {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "dtmc reach: цель вне диапазона" });
                rep.skipped += 1;
                return;
            }
            const targ = try arena.alloc(bool, n);
            for (targ, 0..) |*b, idx| b.* = (idx == tgt);
            const x = try d.reachProbability(targ, 2000);
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .value, .reason = try std.fmt.allocPrint(arena, "P(достичь {d} из 0) = {d:.6}", .{ tgt, x[0] }) });
            rep.values += 1;
            return;
        }
        try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "dtmc: неизвестный вид" });
        rep.skipped += 1;
        return;
    }

    try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "неизвестная теория (arrays/absint/dtmc)" });
    rep.skipped += 1;
}

fn skipNum(alloc: std.mem.Allocator, rep: *Report, spec: []const u8, what: []const u8) !void {
    try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = try std.fmt.allocPrint(alloc, "не число: {s}", .{what}) });
    rep.skipped += 1;
}

test "theory_cli: токенизация строки спецификации" {
    var buf: [16][]const u8 = undefined;
    const t = toks("arrays  oob   idx   10", &buf);
    try std.testing.expectEqual(@as(usize, 4), t.len);
    try std.testing.expectEqualStrings("arrays", t[0]);
    try std.testing.expectEqualStrings("oob", t[1]);
    try std.testing.expectEqualStrings("10", t[3]);
}

test "theory_cli: интервал печатается, пустой распознаётся" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    try std.testing.expectEqualStrings("[0, 9]", try intervalSmt(a, absint.Interval{ .lo = 0, .hi = 9 }));
    try std.testing.expectEqualStrings("пусто", try intervalSmt(a, absint.Interval{ .lo = 5, .hi = 1 }));
    const empty_iv = absint.Interval{ .lo = 5, .hi = 1 };
    try std.testing.expect(empty_iv.isEmpty());
}
