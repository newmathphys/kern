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
//!   redos <regex>                    катастрофический бэктрекинг (CWE-1333)?
//!
//! ШАГ D: `redos` разбирает НАСТОЯЩУЮ регулярку (подмножество: литералы, `.`,
//! `|`, `(`, `)`, `*`, `+`, `?`) и запускает нативный анализ `redos.zig`.
//! Оракул реальности — секундомер: та же строка прогоняется в живом Python,
//! и время обязано быть экспоненциальным, если анализ сказал «уязвимо».
//! Регулярка не должна содержать ПРОБЕЛОВ (токены разделяются пробелами).
//!
//! ЧЕСТНАЯ ГРАНИЦА: это ЯВНЫЙ формат (не «любой текст»). Разбираются ровно
//! перечисленные команды; всё прочее — `SKIP` С ПРИЧИНОЙ.
const std = @import("std");
const z3 = @import("z3_bridge.zig");
const array_theory = @import("array_theory.zig");
const absint = @import("abstract_interp.zig");
const dtmc_mod = @import("dtmc.zig");
const redos_mod = @import("redos.zig");
const chc = @import("chc.zig");

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
    // ШАГ D: ReDoS на НАСТОЯЩЕЙ регулярке. Оракул реальности — секундомер
    // (внешний скрипт `tools/oracle_redos_check.py`), здесь — только вердикт
    // нативного анализа `redos.zig` по разобранному AST.
    if (std.mem.eql(u8, t[0], "redos")) {
        if (t.len < 2) {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "redos: нужен <regex> (без пробелов)" });
            rep.skipped += 1;
            return;
        }
        var rp = ReParser{ .s = t[1], .i = 0, .arena = arena };
        const root = try rp.parseAlt();
        // ДЕФЕКТ #385: синтаксис вне подмножества парсера → вердикта НЕТ.
        // Иначе получилось бы «ДОКАЗАНО» о ДРУГОЙ регулярке (fail-open).
        if (rp.unsupported) |ch| {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = try std.fmt.allocPrint(arena, "redos: синтаксис вне подмножества парсера (символ '{c}') — вердикта НЕТ", .{ch}) });
            rep.skipped += 1;
            return;
        }
        const f = redos_mod.analyze(root);
        if (f.vulnerable) {
            const why = if (f.nested_quantifier and f.ambiguous_alternation)
                "вложенный квантор И неоднозначная альтернатива"
            else if (f.nested_quantifier) "вложенный квантор"
            else "неоднозначная альтернатива под квантором";
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .refuted, .reason = try std.fmt.allocPrint(arena, "КАТАСТРОФИЧЕСКИЙ БЭКТРЕКИНГ возможен (CWE-1333): {s}", .{why}) });
            rep.refuted += 1;
        } else {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .proven, .reason = "вложенных кванторов и неоднозначных альтернатив нет" });
            rep.proven += 1;
        }
        return;
    }
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
        // ШАГ D: инвариант ЛИНЕЙНОГО ЦИКЛА. Физический оракул
        // (`tools/oracle_absint_check.py`) прогоняет РЕАЛЬНЫЙ цикл и проверяет,
        // что абстрактный инвариант СОДЕРЖИТ все наблюдённые значения.
        if (t.len >= 2 and std.mem.eql(u8, t[1], "loop")) {
            if (t.len < 5) {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "absint loop: нужны <init> <step> <bound>" });
                rep.skipped += 1;
                return;
            }
            const init = std.fmt.parseInt(i64, t[2], 10) catch return skipNum(alloc, rep, spec, "init");
            const step = std.fmt.parseInt(i64, t[3], 10) catch return skipNum(alloc, rep, spec, "step");
            const bound = std.fmt.parseInt(i64, t[4], 10) catch return skipNum(alloc, rep, spec, "bound");
            const r = absint.analyzeLinearLoop(init, step, bound);
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .value, .reason = try std.fmt.allocPrint(arena, "инвариант={s} выход={s} итераций={d} widening={s}", .{ try intervalSmt(arena, r.invariant), try intervalSmt(arena, r.exit_state), r.iterations, if (r.widened) "да" else "нет" }) });
            rep.values += 1;
            return;
        }
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

    // ШАГ D: CHC/Horn — ИНВАРИАНТ ЦИКЛА. Физический оракул
    // (`tools/oracle_chc_check.py`) прогоняет РЕАЛЬНЫЙ цикл и требует, чтобы
    // вердикт ядра согласовался с фактическим значением на выходе: `sat`
    // (инвариант есть) обязан сопровождаться ВЫПОЛНЕНИЕМ постусловия,
    // `unsat` (инварианта нет) — его НАРУШЕНИЕМ.
    if (std.mem.eql(u8, t[0], "chc")) {
        if (t.len < 5) {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "chc: нужны <init> <step> <bound> <свойство>" });
            rep.skipped += 1;
            return;
        }
        const init = std.fmt.parseInt(i64, t[1], 10) catch return skipNum(alloc, rep, spec, "init");
        const step = std.fmt.parseInt(i64, t[2], 10) catch return skipNum(alloc, rep, spec, "step");
        const bound = std.fmt.parseInt(i64, t[3], 10) catch return skipNum(alloc, rep, spec, "bound");
        // Постусловие — ИМЕНОВАННОЕ свойство: SMT-выражение с пробелами
        // разорвало бы токенизацию спецификации.
        const post: []const u8 = if (std.mem.eql(u8, t[4], "ge_bound"))
            try std.fmt.allocPrint(arena, "(>= x {d})", .{bound})
        else if (std.mem.eql(u8, t[4], "lt_bound"))
            try std.fmt.allocPrint(arena, "(< x {d})", .{bound})
        else if (std.mem.eql(u8, t[4], "parity_even"))
            "(= (mod x 2) 0)"
        else if (std.mem.eql(u8, t[4], "le_init"))
            try std.fmt.allocPrint(arena, "(<= x {d})", .{init})
        else {
            try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "chc: неизвестное свойство (ge_bound|lt_bound|parity_even|le_init)" });
            rep.skipped += 1;
            return;
        };
        const init_cond = try std.fmt.allocPrint(arena, "(= x {d})", .{init});
        const guard = try std.fmt.allocPrint(arena, "(< x {d})", .{bound});
        const step_expr = try std.fmt.allocPrint(arena, "(+ x {d})", .{step});
        var eng = chc.ChcEngine.init(arena);
        const st = eng.proveLoopSafety(bridge, init_cond, guard, step_expr, post);
        switch (st) {
            .Sat => {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .proven, .reason = try std.fmt.allocPrint(arena, "инвариант СУЩЕСТВУЕТ: свойство {s} держится", .{t[4]}) });
                rep.proven += 1;
            },
            .Unsat => {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .refuted, .reason = try std.fmt.allocPrint(arena, "инварианта НЕТ: свойство {s} нарушается", .{t[4]}) });
                rep.refuted += 1;
            },
            else => {
                try rep.outcomes.append(alloc, .{ .name = spec, .status = .skip, .reason = "решатель не ответил (Horn: unknown/timeout)" });
                rep.skipped += 1;
            },
        }
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

// =========================================================================
// ШАГ D: ПАРСЕР РЕГУЛЯРКИ ДЛЯ НАТИВНОГО АНАЛИЗА ReDoS
// =========================================================================
// ЗАЧЕМ. `redos.zig` умеет `analyze(root: *const Node)`, но парсера у него
// НЕ БЫЛО — то есть нативный анализ нельзя было применить к настоящей
// регулярке из внешнего файла. Здесь рекурсивный спуск по подмножеству:
// литералы, `.`, `|`, `(`, `)`, `*`, `+`, `?`.
//
// ЧЕСТНАЯ ГРАНИЦА (переделана в ДЕФЕКТЕ #385): это ПОДМНОЖЕНИЕ — литералы,
// `.`, `|`, `(`, `)`, `*`, `+`, `?`. Всё остальное (классы `[a-z]`, `\d`,
// `{m,n}`, `^`, `$`) раньше молча читалось КАК ЛИТЕРАЛ, и анализ шёл по
// ДРУГОЙ регулярке: `(\d+)+` выдавало «ДОКАЗАНО» (нет вложенных кванторов),
// хотя физически взрывается за 1.44 с. Теперь парсер FAIL-CLOSED: встречая
// неподдерживаемый символ, он помечает это и вердикта НЕ ДАЁТ.
const ReParser = struct {
    s: []const u8,
    i: usize = 0,
    arena: std.mem.Allocator,
    /// Первый неподдерживаемый символ (fail-closed, #385). null = всё разобрано.
    unsupported: ?u8 = null,

    fn peek(self: *ReParser) ?u8 {
        return if (self.i < self.s.len) self.s[self.i] else null;
    }

    fn next(self: *ReParser) ?u8 {
        if (self.i >= self.s.len) return null;
        const c = self.s[self.i];
        self.i += 1;
        return c;
    }

    fn node(self: *ReParser) std.mem.Allocator.Error!*redos_mod.Node {
        return try self.arena.create(redos_mod.Node);
    }

    /// alt := concat ('|' concat)*
    fn parseAlt(self: *ReParser) std.mem.Allocator.Error!*redos_mod.Node {
        var items: std.ArrayListUnmanaged(*redos_mod.Node) = .empty;
        try items.append(self.arena, try self.parseConcat());
        while (self.peek() == '|') {
            _ = self.next();
            try items.append(self.arena, try self.parseConcat());
        }
        if (items.items.len == 1) return items.items[0];
        const n = try self.node();
        n.* = .{ .alt = try self.arena.dupe(*redos_mod.Node, items.items) };
        return n;
    }

    /// concat := repeat*
    fn parseConcat(self: *ReParser) std.mem.Allocator.Error!*redos_mod.Node {
        var items: std.ArrayListUnmanaged(*redos_mod.Node) = .empty;
        while (self.peek()) |c| {
            if (c == '|' or c == ')') break;
            try items.append(self.arena, try self.parseRepeat());
        }
        if (items.items.len == 0) {
            const n = try self.node();
            n.* = .{ .lit = 0 };
            return n;
        }
        if (items.items.len == 1) return items.items[0];
        const n = try self.node();
        n.* = .{ .concat = try self.arena.dupe(*redos_mod.Node, items.items) };
        return n;
    }

    /// repeat := atom ('*' | '+' | '?')*
    fn parseRepeat(self: *ReParser) std.mem.Allocator.Error!*redos_mod.Node {
        var cur = try self.parseAtom();
        while (self.peek()) |c| {
            if (c != '*' and c != '+' and c != '?') break;
            _ = self.next();
            const outer = try self.node();
            outer.* = switch (c) {
                '*' => .{ .star = cur },
                '+' => .{ .plus = cur },
                else => .{ .opt = cur },
            };
            cur = outer;
        }
        return cur;
    }

    /// atom := '(' alt ')' | '.' | literal
    fn parseAtom(self: *ReParser) std.mem.Allocator.Error!*redos_mod.Node {
        const c = self.next() orelse {
            const n = try self.node();
            n.* = .{ .lit = 0 };
            return n;
        };
        if (c == '(') {
            const inner = try self.parseAlt();
            if (self.peek() == ')') _ = self.next();
            return inner;
        }
        // ДЕФЕКТ #385 (fail-closed): раньше ЛЮБОЙ незнакомый символ читался как
        // литерал, поэтому `\d` разбиралось как ДВА литерала (`\` и `d`), и
        // анализ шёл по ДРУГОЙ регулярке — выдавая «ДОКАЗАНО» о том, чего не
        // читал. Теперь всё вне подмножества помечается и вердикта не даёт.
        switch (c) {
            '\\', '[', ']', '{', '}', '^', '$' => {
                if (self.unsupported == null) self.unsupported = c;
                const n = try self.node();
                n.* = .{ .lit = 0 };
                return n;
            },
            else => {},
        }
        const n = try self.node();
        n.* = if (c == '.') .any else .{ .lit = c };
        return n;
    }
};

test "шаг D: парсер регулярки + анализ ReDoS" {
    var arena_state = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena_state.deinit();
    const a = arena_state.allocator();

    // `(a+)+` — вложенный квантор: обязан быть уязвим.
    var p1 = ReParser{ .s = "(a+)+", .arena = a };
    try std.testing.expect(redos_mod.analyze(try p1.parseAlt()).vulnerable);

    // `(a|a)*` — неоднозначная альтернатива под квантором: уязвим.
    var p2 = ReParser{ .s = "(a|a)*", .arena = a };
    try std.testing.expect(redos_mod.analyze(try p2.parseAlt()).vulnerable);

    // `(ab|cd)+` — альтернатива БЕЗ общего префикса: НЕ уязвим.
    var p3 = ReParser{ .s = "(ab|cd)+", .arena = a };
    try std.testing.expect(!redos_mod.analyze(try p3.parseAlt()).vulnerable);

    // `abc` — просто литералы: не уязвим.
    var p4 = ReParser{ .s = "abc", .arena = a };
    try std.testing.expect(!redos_mod.analyze(try p4.parseAlt()).vulnerable);
}

test "шаг D: парсер FAIL-CLOSED на синтаксисе вне подмножества (#385)" {
    var arena_state = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena_state.deinit();
    const a = arena_state.allocator();

    // `(\d+)+` физически ВЗРЫВАЕТСЯ (измерено: 1.44 с при N=24), но `\d` вне
    // подмножества парсера. Обязан быть ПОМЕЧЕН, а не прочитан как два
    // литерала (`\` и `d`) — иначе вердикт относился бы к другой регулярке.
    var p1 = ReParser{ .s = "(\\d+)+", .arena = a };
    _ = try p1.parseAlt();
    try std.testing.expectEqual(@as(?u8, '\\'), p1.unsupported);

    // `[a-z]+` — класс символов: тоже вне подмножества.
    var p2 = ReParser{ .s = "[a-z]+", .arena = a };
    _ = try p2.parseAlt();
    try std.testing.expectEqual(@as(?u8, '['), p2.unsupported);

    // `(a+)+` — внутри подмножества: пометки быть НЕ ДОЛЖНО.
    var p3 = ReParser{ .s = "(a+)+", .arena = a };
    _ = try p3.parseAlt();
    try std.testing.expectEqual(@as(?u8, null), p3.unsupported);
}
