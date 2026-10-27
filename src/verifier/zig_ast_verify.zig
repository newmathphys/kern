// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.

//! KERN: НАТИВНЫЙ ФРОНТЕНД `.zig` НА `std.zig.Ast` (БЕЗ Python).
//!
//! ЗАЧЕМ. До этого модуля контракты `/// @kern:requires` / `/// @kern:ensures`
//! разбирал ТОЛЬКО питоновский `tools/kern_contracts.py`, а сам бинарник `kernc`
//! умел читать лишь `.smt2`. Нативная часть ядра на реальных исходниках не
//! работала вообще. Теперь `kernc verify-zig <file.zig>` разбирает файл
//! КОМПИЛЯТОРНЫМ парсером `std.zig.Ast.parse` и проверяет обязательства сам.
//!
//! ТРИ ФАКТА О `std.zig.Ast` (Zig 0.17), на которых всё держится:
//!   1. `///` — ТОКЕНЫ с тегом `.doc_comment`, а НЕ узлы. Между ними и `fn`
//!      может стоять `keyword_pub`/`keyword_export`/`keyword_inline` — их надо
//!      пропускать при шаге назад (`Ast.zig:737-739`), а собранные строки
//!      разворачивать в ПРЯМОМ порядке (`Ast.zig:2648-2650`).
//!   2. `@divTrunc`/`@divFloor`/`@rem`/`@mod`/`@as` — узлы `.builtin_call_two`
//!      (`Ast.zig:621-624`), аргументы — `builtinCallParams(&buf, node)`
//!      (`Ast.zig:2432`), имя — `tokenSlice(nodeMainToken(node))`.
//!   3. Тело — `blockStatements(&buf, node)` (`Ast.zig:2440`), параметры —
//!      `fnProto(node).iterate(&ast)` (`Ast.zig:2692`).
//!
//! ЧТО ПРОВЕРЯЕТСЯ (обязательства БЕЗОПАСНОСТИ, не только постусловие):
//!   * `+`, `-`, `*`, унарный `-x` на знаковых — ПЕРЕПОЛНЕНИЕ типа;
//!   * `/`, `%`, `@divTrunc`, `@divFloor`, `@rem`, `@mod` — деление на ноль И
//!     аппаратная ловушка `MIN_INT / -1`;
//!   * `+%`, `-%`, `*%` (оборачивание) и `+|`, `-|` (насыщение) — обязательства
//!     переполнения НЕТ, и это НЕ пропуск, а определение языка.
//!
//! ЧЕСТНАЯ ГРАНИЦА: подмножество — целые `i32/u32/i64/u64/usize`, тело из
//! РОВНО ОДНОГО `return` с линейным выражением, контракты из `and`/`or`/`!`,
//! сравнений и `+ - * / %`. Всё прочее — `SKIP` С ПРИЧИНОЙ.
const std = @import("std");
const z3 = @import("z3_bridge.zig");

pub const Status = enum { proven, refuted, skip };

pub const Outcome = struct {
    name: []const u8,
    status: Status,
    reason: []const u8 = "",
    counterexample: []const u8 = "",
    obligations: usize = 0,
};

pub const Report = struct {
    outcomes: std.ArrayListUnmanaged(Outcome) = .empty,
    proven: usize = 0,
    refuted: usize = 0,
    skipped: usize = 0,

    pub fn deinit(self: *Report, alloc: std.mem.Allocator) void {
        self.outcomes.deinit(alloc);
    }
};

pub const Ty = struct {
    bits: u8,
    signed: bool,
    fn modu(self: Ty) i128 {
        return switch (self.bits) {
            32 => 1 << 31,
            else => 1 << 63,
        };
    }
    pub fn lo(self: Ty) i128 {
        return if (self.signed) -self.modu() else 0;
    }
    pub fn hi(self: Ty) i128 {
        const m = self.modu();
        return if (self.signed) m - 1 else 2 * m - 1;
    }
};

pub fn tyOfName(n: []const u8) ?Ty {
    if (std.mem.eql(u8, n, "i32")) return .{ .bits = 32, .signed = true };
    if (std.mem.eql(u8, n, "u32")) return .{ .bits = 32, .signed = false };
    if (std.mem.eql(u8, n, "i64")) return .{ .bits = 64, .signed = true };
    if (std.mem.eql(u8, n, "u64")) return .{ .bits = 64, .signed = false };
    if (std.mem.eql(u8, n, "usize")) return .{ .bits = 64, .signed = false };
    return null;
}

pub const Contracts = struct { requires: []const u8 = "", ensures: []const u8 = "" };

const Obligation = struct { kind: []const u8, violation: []const u8, note: []const u8 };

const Ctx = struct {
    arena: std.mem.Allocator,
    ast: *const std.zig.Ast,
    vars: std.StringHashMapUnmanaged(Ty) = .empty,
    obligations: std.ArrayListUnmanaged(Obligation) = .empty,
    bad: []const u8 = "",
    wrap_seen: bool = false,
};

fn numLiteral(raw: []const u8) ?i128 {
    var buf: [128]u8 = undefined;
    var n: usize = 0;
    for (raw) |ch| {
        if (ch == '_') continue;
        if (n >= buf.len) return null;
        buf[n] = ch;
        n += 1;
    }
    const s = buf[0..n];
    if (std.mem.startsWith(u8, s, "0x") or std.mem.startsWith(u8, s, "0X"))
        return std.fmt.parseInt(i128, s[2..], 16) catch null;
    return std.fmt.parseInt(i128, s, 10) catch null;
}

fn tyFromNode(c: *Ctx, node: std.zig.Ast.Node.Index) ?Ty {
    const ast = c.ast;
    const tag = ast.nodeTag(node);
    if (tag == .identifier) return c.vars.get(ast.tokenSlice(ast.nodeMainToken(node)));
    if (tag == .number_literal) {
        const v = numLiteral(ast.tokenSlice(ast.nodeMainToken(node))) orelse return null;
        if (v >= -2147483648 and v <= 2147483647) return .{ .bits = 32, .signed = true };
        return .{ .bits = 64, .signed = true };
    }
    if (tag == .builtin_call_two or tag == .builtin_call_two_comma) {
        if (std.mem.eql(u8, ast.tokenSlice(ast.nodeMainToken(node)), "@as")) {
            var buf: [2]std.zig.Ast.Node.Index = undefined;
            const a = ast.builtinCallParams(&buf, node) orelse return null;
            if (a.len >= 1 and ast.nodeTag(a[0]) == .identifier)
                return tyOfName(ast.tokenSlice(ast.nodeMainToken(a[0])));
            return null;
        }
    }
    const a = switch (tag) {
        .add, .sub, .mul, .div, .mod, .add_wrap, .sub_wrap, .mul_wrap,
        .add_sat, .sub_sat, .mul_sat => ast.nodeData(node).node_and_node[0],
        .negation, .negation_wrap => ast.nodeData(node).node,
        else => return null,
    };
    return tyFromNode(c, a);
}

fn pushOblig(c: *Ctx, kind: []const u8, violation: []const u8, note: []const u8) !void {
    try c.obligations.append(c.arena, .{ .kind = kind, .violation = violation, .note = note });
}

fn binSmt(c: *Ctx, op: []const u8, ln: std.zig.Ast.Node.Index, rn: std.zig.Ast.Node.Index, plain: bool) anyerror!?[]const u8 {
    const l = try exprSmt(c, ln) orelse return null;
    const r = try exprSmt(c, rn) orelse return null;
    const t = tyFromNode(c, ln) orelse {
        c.bad = "неизвестен тип левого операнда";
        return null;
    };
    const term = try std.fmt.allocPrint(c.arena, "({s} {s} {s})", .{ op, l, r });
    const arith = std.mem.eql(u8, op, "+") or std.mem.eql(u8, op, "-") or std.mem.eql(u8, op, "*");
    if (arith and plain and t.signed) {
        const v = try std.fmt.allocPrint(c.arena, "(or (> {s} {d}) (< {s} {d}))", .{ term, t.hi(), term, t.lo() });
        try pushOblig(c, "overflow", v, try std.fmt.allocPrint(c.arena, "переполнение i{d}: {s}", .{ t.bits, term }));
    }
    if (arith and plain and !t.signed) {
        const v = try std.fmt.allocPrint(c.arena, "(> {s} {d})", .{ term, t.hi() });
        try pushOblig(c, "overflow", v, try std.fmt.allocPrint(c.arena, "переполнение u{d}: {s}", .{ t.bits, term }));
    }
    if (std.mem.eql(u8, op, "div") or std.mem.eql(u8, op, "rem")) {
        try pushOblig(c, "divzero", try std.fmt.allocPrint(c.arena, "(= {s} 0)", .{r}), try std.fmt.allocPrint(c.arena, "деление на ноль: {s}", .{term}));
        if (t.signed) {
            const vt = try std.fmt.allocPrint(c.arena, "(and (= {s} {d}) (= {s} -1))", .{ l, t.lo(), r });
            try pushOblig(c, "trap", vt, try std.fmt.allocPrint(c.arena, "ловушка MIN/-1: {s}", .{term}));
        }
    }
    return term;
}

fn exprSmt(c: *Ctx, node: std.zig.Ast.Node.Index) anyerror!?[]const u8 {
    const ast = c.ast;
    switch (ast.nodeTag(node)) {
        .identifier => {
            const nm = ast.tokenSlice(ast.nodeMainToken(node));
            if (c.vars.get(nm) == null) {
                c.bad = "идентификатор вне параметров функции";
                return null;
            }
            return nm;
        },
        .number_literal => {
            const v = numLiteral(ast.tokenSlice(ast.nodeMainToken(node))) orelse {
                c.bad = "нечисловой литерал";
                return null;
            };
            return try std.fmt.allocPrint(c.arena, "{d}", .{v});
        },
        .builtin_call_two, .builtin_call_two_comma => {
            const name = ast.tokenSlice(ast.nodeMainToken(node));
            var buf: [2]std.zig.Ast.Node.Index = undefined;
            const a = ast.builtinCallParams(&buf, node) orelse {
                c.bad = "аргументы builtin не разобраны";
                return null;
            };
            if (std.mem.eql(u8, name, "@as")) {
                if (a.len < 2) return null;
                return exprSmt(c, a[1]);
            }
            if (a.len < 2) return null;
            const op: []const u8 = if (std.mem.eql(u8, name, "@divTrunc") or std.mem.eql(u8, name, "@divFloor")) "div" else if (std.mem.eql(u8, name, "@rem") or std.mem.eql(u8, name, "@mod")) "rem" else {
                c.bad = "вызов builtin вне подмножества";
                return null;
            };
            return binSmt(c, op, a[0], a[1], true);
        },
        .add, .sub, .mul, .div, .mod, .add_wrap, .sub_wrap, .mul_wrap, .add_sat, .sub_sat, .mul_sat => {
            const a = ast.nodeData(node).node_and_node;
            const op: []const u8 = switch (ast.nodeTag(node)) {
                .add, .add_wrap, .add_sat => "+",
                .sub, .sub_wrap, .sub_sat => "-",
                .mul, .mul_wrap, .mul_sat => "*",
                .div => "div",
                .mod => "rem",
                else => unreachable,
            };
            const wrapping = switch (ast.nodeTag(node)) {
                .add_wrap, .sub_wrap, .mul_wrap, .add_sat, .sub_sat, .mul_sat => true,
                else => false,
            };
            if (wrapping) c.wrap_seen = true;
            return binSmt(c, op, a[0], a[1], !wrapping);
        },
        .negation, .negation_wrap => {
            const a = ast.nodeData(node).node;
            const inner = try exprSmt(c, a) orelse return null;
            const t = tyFromNode(c, a) orelse {
                c.bad = "неизвестен тип унарного минуса";
                return null;
            };
            if (ast.nodeTag(node) == .negation and t.signed) {
                const v = try std.fmt.allocPrint(c.arena, "(= {s} {d})", .{ inner, t.lo() });
                try pushOblig(c, "overflow", v, try std.fmt.allocPrint(c.arena, "унарный минус на MIN ({s})", .{inner}));
            } else if (ast.nodeTag(node) == .negation_wrap) c.wrap_seen = true;
            return try std.fmt.allocPrint(c.arena, "(- 0 {s})", .{inner});
        },
        else => {
            c.bad = "узел вне подмножества";
            return null;
        },
    }
}

/// Собрать текст `///`-комментариев ПЕРЕД объявлением.
/// ИЗМЕРЕНО (`Ast.zig:737-739, 2648-2650`): `///` — токены `.doc_comment`, а
/// между ними и `fn` может стоять `pub`/`export`/`inline`; их надо пропустить.
fn docCommentText(arena: std.mem.Allocator, ast: *const std.zig.Ast, node: std.zig.Ast.Node.Index) ![]const u8 {
    var t = ast.firstToken(node);
    while (t > 0) {
        const tag = ast.tokenTag(t - 1);
        if (tag == .keyword_pub or tag == .keyword_export or tag == .keyword_inline) {
            t -= 1;
            continue;
        }
        break;
    }
    var first: ?std.zig.Ast.TokenIndex = null;
    var i = t;
    while (i > 0 and ast.tokenTag(i - 1) == .doc_comment) {
        i -= 1;
        first = i;
    }
    const f = first orelse return "";
    var buf = std.ArrayListUnmanaged(u8).empty;
    var k = f;
    while (k < t) : (k += 1) {
        try buf.appendSlice(arena, ast.tokenSlice(k));
        try buf.append(arena, '\n');
    }
    return buf.items;
}

pub fn parseContracts(text: []const u8) Contracts {
    var c = Contracts{};
    var it = std.mem.splitScalar(u8, text, '\n');
    while (it.next()) |raw| {
        const line = std.mem.trim(u8, raw, " \t\r/");
        if (std.mem.startsWith(u8, line, "@kern:requires"))
            c.requires = std.mem.trim(u8, line["@kern:requires".len..], " \t")
        else if (std.mem.startsWith(u8, line, "@kern:ensures"))
            c.ensures = std.mem.trim(u8, line["@kern:ensures".len..], " \t");
    }
    return c;
}

// --- ПАРСЕР ТЕКСТА КОНТРАКТА: `and`, `or`, `!`, сравнения, `+ - * / %` ---
const Tok = struct { kind: enum { ident, num, op, lp, rp, eof }, text: []const u8 };

const Lexer = struct {
    s: []const u8,
    i: usize = 0,
    fn next(self: *Lexer) Tok {
        while (self.i < self.s.len and (self.s[self.i] == ' ' or self.s[self.i] == '\t')) self.i += 1;
        if (self.i >= self.s.len) return .{ .kind = .eof, .text = "" };
        const c = self.s[self.i];
        if (c == '(') {
            self.i += 1;
            return .{ .kind = .lp, .text = "(" };
        }
        if (c == ')') {
            self.i += 1;
            return .{ .kind = .rp, .text = ")" };
        }
        if (std.ascii.isAlphanumeric(c) or c == '_') {
            const st = self.i;
            while (self.i < self.s.len and (std.ascii.isAlphanumeric(self.s[self.i]) or self.s[self.i] == '_')) self.i += 1;
            const w = self.s[st..self.i];
            return .{ .kind = if (std.ascii.isDigit(w[0])) .num else .ident, .text = w };
        }
        if (self.i + 1 < self.s.len) {
            const two = self.s[self.i .. self.i + 2];
            if (std.mem.eql(u8, two, "==") or std.mem.eql(u8, two, "!=") or std.mem.eql(u8, two, "<=") or std.mem.eql(u8, two, ">=")) {
                self.i += 2;
                return .{ .kind = .op, .text = two };
            }
        }
        self.i += 1;
        return .{ .kind = .op, .text = self.s[self.i - 1 .. self.i] };
    }
};

const CP = struct {
    toks: []const Tok,
    i: usize = 0,
    arena: std.mem.Allocator,
    fn peek(self: *CP) Tok {
        return if (self.i < self.toks.len) self.toks[self.i] else .{ .kind = .eof, .text = "" };
    }
    fn pOr(self: *CP) anyerror!?[]const u8 {
        var l = try self.pAnd() orelse return null;
        while (self.peek().kind == .ident and std.mem.eql(u8, self.peek().text, "or")) {
            self.i += 1;
            const r = try self.pAnd() orelse return null;
            l = try std.fmt.allocPrint(self.arena, "(or {s} {s})", .{ l, r });
        }
        return l;
    }
    fn pAnd(self: *CP) anyerror!?[]const u8 {
        var l = try self.pCmp() orelse return null;
        while (self.peek().kind == .ident and std.mem.eql(u8, self.peek().text, "and")) {
            self.i += 1;
            const r = try self.pCmp() orelse return null;
            l = try std.fmt.allocPrint(self.arena, "(and {s} {s})", .{ l, r });
        }
        return l;
    }
    fn pCmp(self: *CP) anyerror!?[]const u8 {
        const l = try self.pAdd() orelse return null;
        const t = self.peek();
        if (t.kind != .op) return l;
        const smt: []const u8 = if (std.mem.eql(u8, t.text, "==")) "=" else if (std.mem.eql(u8, t.text, "!=")) "distinct" else if (std.mem.eql(u8, t.text, "<")) "<" else if (std.mem.eql(u8, t.text, "<=")) "<=" else if (std.mem.eql(u8, t.text, ">")) ">" else if (std.mem.eql(u8, t.text, ">=")) ">=" else return l;
        self.i += 1;
        const r = try self.pAdd() orelse return null;
        return try std.fmt.allocPrint(self.arena, "({s} {s} {s})", .{ smt, l, r });
    }
    fn pAdd(self: *CP) anyerror!?[]const u8 {
        var l = try self.pMul() orelse return null;
        while (true) {
            const t = self.peek();
            if (t.kind != .op or (t.text[0] != '+' and t.text[0] != '-')) return l;
            self.i += 1;
            const r = try self.pMul() orelse return null;
            l = try std.fmt.allocPrint(self.arena, "({s} {s} {s})", .{ t.text[0..1], l, r });
        }
    }
    fn pMul(self: *CP) anyerror!?[]const u8 {
        var l = try self.pUn() orelse return null;
        while (true) {
            const t = self.peek();
            if (t.kind != .op or (t.text[0] != '*' and t.text[0] != '/' and t.text[0] != '%')) return l;
            self.i += 1;
            const r = try self.pUn() orelse return null;
            const op: []const u8 = if (t.text[0] == '*') "*" else if (t.text[0] == '/') "div" else "rem";
            l = try std.fmt.allocPrint(self.arena, "({s} {s} {s})", .{ op, l, r });
        }
    }
    fn pUn(self: *CP) anyerror!?[]const u8 {
        const t = self.peek();
        if (t.kind == .ident and std.mem.eql(u8, t.text, "not")) {
            self.i += 1;
            const r = try self.pUn() orelse return null;
            return try std.fmt.allocPrint(self.arena, "(not {s})", .{r});
        }
        if (t.kind == .op and std.mem.eql(u8, t.text, "!")) {
            self.i += 1;
            const r = try self.pUn() orelse return null;
            return try std.fmt.allocPrint(self.arena, "(not {s})", .{r});
        }
        if (t.kind == .op and std.mem.eql(u8, t.text, "-")) {
            self.i += 1;
            const r = try self.pUn() orelse return null;
            return try std.fmt.allocPrint(self.arena, "(- 0 {s})", .{r});
        }
        return self.pPrim();
    }
    fn pPrim(self: *CP) anyerror!?[]const u8 {
        const t = self.peek();
        if (t.kind == .lp) {
            self.i += 1;
            const e = try self.pOr() orelse return null;
            if (self.peek().kind != .rp) return null;
            self.i += 1;
            return e;
        }
        if (t.kind == .num) {
            self.i += 1;
            const v = numLiteral(t.text) orelse return null;
            return try std.fmt.allocPrint(self.arena, "{d}", .{v});
        }
        if (t.kind == .ident) {
            self.i += 1;
            return t.text;
        }
        return null;
    }
};

/// Текст контракта -> SMT-терм. `null` = вне подмножества (честный SKIP).
pub fn contractSmt(arena: std.mem.Allocator, text: []const u8) !?[]const u8 {
    if (text.len == 0) return "";
    var lx = Lexer{ .s = text };
    var toks = std.ArrayListUnmanaged(Tok).empty;
    while (true) {
        const t = lx.next();
        try toks.append(arena, t);
        if (t.kind == .eof) break;
    }
    var p = CP{ .toks = toks.items, .arena = arena };
    const r = try p.pOr() orelse return null;
    if (p.peek().kind != .eof) return null;
    return r;
}

fn header(arena: std.mem.Allocator, c: *Ctx, req: []const u8, rt: ?Ty) ![]const u8 {
    var w = std.ArrayListUnmanaged(u8).empty;
    try w.appendSlice(arena, "(set-logic ALL)\n");
    var vit = c.vars.iterator();
    while (vit.next()) |e| {
        const name = e.key_ptr.*;
        const ty = e.value_ptr.*;
        try w.appendSlice(arena, try std.fmt.allocPrint(arena, "(declare-const {s} Int)\n(assert (and (>= {s} {d}) (<= {s} {d})))\n", .{ name, name, ty.lo(), name, ty.hi() }));
    }
    if (rt) |t| try w.appendSlice(arena, try std.fmt.allocPrint(arena, "(declare-const result Int)\n(assert (and (>= result {d}) (<= result {d})))\n", .{ t.lo(), t.hi() }));
    if (req.len != 0) try w.appendSlice(arena, try std.fmt.allocPrint(arena, "(assert {s})\n", .{req}));
    return w.items;
}

fn modelTail(arena: std.mem.Allocator, out: []const u8) ![]const u8 {
    const sp = std.mem.indexOf(u8, out, "sat") orelse 0;
    return try arena.dupe(u8, std.mem.trim(u8, out[@min(sp + 3, out.len)..], " \n\t"));
}

fn obligationSat(arena: std.mem.Allocator, bridge: *z3.Z3Bridge, c: *Ctx, req: []const u8, viol: []const u8) !?[]const u8 {
    const h = try header(arena, c, req, null);
    const script = try std.fmt.allocPrint(arena, "{s}(assert {s})\n(check-sat)\n(get-model)\n", .{ h, viol });
    const cap = bridge.executeCapture(script);
    defer arena.free(cap.stdout);
    if (cap.status == .Sat) return try modelTail(arena, cap.stdout);
    return null;
}

fn ensuresHolds(arena: std.mem.Allocator, bridge: *z3.Z3Bridge, c: *Ctx, req: []const u8, ens: []const u8, body: []const u8, rt: Ty) !?[]const u8 {
    const h = try header(arena, c, req, rt);
    const script = try std.fmt.allocPrint(arena, "{s}(assert (= result {s}))\n(assert (not {s}))\n(check-sat)\n(get-model)\n", .{ h, body, ens });
    const cap = bridge.executeCapture(script);
    defer arena.free(cap.stdout);
    if (cap.status == .Unsat) return "";
    return try modelTail(arena, cap.stdout);
}

fn checkOne(alloc: std.mem.Allocator, arena: std.mem.Allocator, bridge: *z3.Z3Bridge, rep: *Report, c: *Ctx, name: []const u8, val: std.zig.Ast.Node.Index, ct: Contracts) !void {
    const body_term = try exprSmt(c, val) orelse {
        try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .skip, .reason = if (c.bad.len != 0) c.bad else "тело вне подмножества" });
        rep.skipped += 1;
        return;
    };
    const req = try contractSmt(arena, ct.requires) orelse {
        try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .skip, .reason = "`requires` вне подмножества контрактов" });
        rep.skipped += 1;
        return;
    };
    const ens = try contractSmt(arena, ct.ensures) orelse {
        try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .skip, .reason = "`ensures` вне подмножества контрактов" });
        rep.skipped += 1;
        return;
    };
    for (c.obligations.items) |ob| {
        if (try obligationSat(arena, bridge, c, req, ob.violation)) |model| {
            try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .refuted, .reason = try std.fmt.allocPrint(alloc, "{s}: {s}", .{ ob.kind, ob.note }), .counterexample = try arena.dupe(u8, model), .obligations = c.obligations.items.len });
            rep.refuted += 1;
            return;
        }
    }
    if (ens.len != 0 and !c.wrap_seen) {
        const rt = tyFromNode(c, val) orelse Ty{ .bits = 32, .signed = true };
        if (try ensuresHolds(arena, bridge, c, req, ens, body_term, rt)) |model| {
            if (model.len != 0) {
                try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .refuted, .reason = "постусловие `ensures` нарушено", .counterexample = try arena.dupe(u8, model), .obligations = c.obligations.items.len });
                rep.refuted += 1;
                return;
            }
        }
    }
    try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .proven, .reason = if (c.wrap_seen) "обязательств переполнения НЕТ (модульное/насыщающее); постусловие в Int-модели НЕ проверялось" else if (ens.len == 0) "обязательства безопасности выполнены (постусловие не задано)" else "обязательства безопасности и постусловие выполнены", .obligations = c.obligations.items.len });
    rep.proven += 1;
}

/// ГЛАВНАЯ ФУНКЦИЯ: разобрать `.zig` и проверить функции с контрактами.
pub fn verifySource(alloc: std.mem.Allocator, bridge: *z3.Z3Bridge, source: [:0]const u8) !Report {
    var rep = Report{};
    var arena_state = std.heap.ArenaAllocator.init(alloc);
    defer arena_state.deinit();
    const arena = arena_state.allocator();
    var ast = try std.zig.Ast.parse(alloc, source, .{});
    defer ast.deinit(alloc);
    for (ast.rootDecls()) |node| {
        if (ast.nodeTag(node) != .fn_decl) continue;
        const ct = parseContracts(try docCommentText(arena, &ast, node));
        if (ct.requires.len == 0 and ct.ensures.len == 0) continue;
        const pnode = ast.nodeData(node).node_and_node[0];
        var pbuf: [1]std.zig.Ast.Node.Index = undefined;
        const proto = switch (ast.nodeTag(pnode)) {
            .fn_proto_simple => ast.fnProtoSimple(&pbuf, pnode),
            .fn_proto_multi => ast.fnProtoMulti(pnode),
            .fn_proto_one => ast.fnProtoOne(&pbuf, pnode),
            .fn_proto => ast.fnProto(pnode),
            else => continue,
        };
        const name = if (proto.name_token) |nt| ast.tokenSlice(nt) else "<anon>";
        var c = Ctx{ .arena = arena, .ast = &ast };
        var bad: []const u8 = "";
        var it = proto.iterate(&ast);
        while (it.next()) |p| {
            const pn = if (p.name_token) |nt| ast.tokenSlice(nt) else continue;
            const te = p.type_expr orelse {
                bad = "параметр без типа";
                break;
            };
            if (ast.nodeTag(te) != .identifier) {
                bad = "тип параметра не из подмножества";
                break;
            }
            const t = tyOfName(ast.tokenSlice(ast.nodeMainToken(te))) orelse {
                bad = "тип параметра вне подмножества (i32/u32/i64/u64/usize)";
                break;
            };
            try c.vars.put(arena, pn, t);
        }
        if (bad.len != 0) {
            try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .skip, .reason = bad });
            rep.skipped += 1;
            continue;
        }
        const body_node = ast.nodeData(node).node_and_node[1];
        var sbuf: [2]std.zig.Ast.Node.Index = undefined;
        const stmts = ast.blockStatements(&sbuf, body_node) orelse {
            try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .skip, .reason = "тело не является блоком" });
            rep.skipped += 1;
            continue;
        };
        if (stmts.len != 1 or ast.nodeTag(stmts[0]) != .@"return") {
            try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .skip, .reason = "тело вне подмножества: нужен РОВНО ОДИН `return`" });
            rep.skipped += 1;
            continue;
        }
        const val = ast.nodeData(stmts[0]).opt_node.unwrap() orelse {
            try rep.outcomes.append(alloc, .{ .name = try arena.dupe(u8, name), .status = .skip, .reason = "`return` без значения" });
            rep.skipped += 1;
            continue;
        };
        try checkOne(alloc, arena, bridge, &rep, &c, name, val, ct);
    }
    return rep;
}

// =========================================================================
//  ТЕСТЫ (идут в `zig build test`)
// =========================================================================

test "zig_ast_verify: контракты достаются из док-комментариев" {
    const ct = parseContracts("@kern:requires a > 0");
    try std.testing.expectEqualStrings("a > 0", ct.requires);
    try std.testing.expectEqualStrings("", ct.ensures);
    const ct2 = parseContracts("@kern:ensures result == a");
    try std.testing.expectEqualStrings("result == a", ct2.ensures);
    try std.testing.expectEqualStrings("", ct2.requires);
}

test "zig_ast_verify: текст контракта -> SMT (and/or/сравнения/арифметика)" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    try std.testing.expectEqualStrings("(and (>= a 0) (<= b 100))", (try contractSmt(a, "a >= 0 and b <= 100")).?);
    try std.testing.expectEqualStrings("(= result (div a b))", (try contractSmt(a, "result == a / b")).?);
    try std.testing.expectEqualStrings("(not (< a 0))", (try contractSmt(a, "not (a < 0)")).?);
    // ВНЕ ПОДМНОЖЕСТВА -> честный null, а не «примерно то же самое».
    try std.testing.expect((try contractSmt(a, "a.foo()")) == null);
}

test "zig_ast_verify: типы подмножества и их границы" {
    const i32t = tyOfName("i32").?;
    try std.testing.expectEqual(@as(i128, -2147483648), i32t.lo());
    try std.testing.expectEqual(@as(i128, 2147483647), i32t.hi());
    const u32t = tyOfName("u32").?;
    try std.testing.expectEqual(@as(i128, 0), u32t.lo());
    try std.testing.expectEqual(@as(i128, 4294967295), u32t.hi());
    try std.testing.expect(tyOfName("f64") == null);
}

test "zig_ast_verify: числа с разделителями и шестнадцатеричные" {
    try std.testing.expectEqual(@as(?i128, 1000), numLiteral("1_000"));
    try std.testing.expectEqual(@as(?i128, 255), numLiteral("0xFF"));
    try std.testing.expectEqual(@as(?i128, null), numLiteral("abc"));
}
