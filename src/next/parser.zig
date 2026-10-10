// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN-Next: лексер + парсер языка .kern (§6 синтаксис, §7 статусы).
const std = @import("std");
const ast = @import("ast.zig");
const Project = ast.Project;

pub const Diagnostic = struct { line: usize, message: []const u8 };

pub const ParseResult = struct {
    project: Project,
    diagnostics: []Diagnostic,
};

const Tag = enum { ident, string, number, lbrace, rbrace, equals, arrow, eof };
const Token = struct { tag: Tag, text: []const u8, line: usize };

const Lexer = struct {
    src: []const u8,
    pos: usize = 0,
    line: usize = 1,

    fn skipWs(self: *Lexer) void {
        while (self.pos < self.src.len) {
            const c = self.src[self.pos];
            if (c == '\n') {
                self.line += 1;
                self.pos += 1;
            } else if (c == ' ' or c == '\t' or c == '\r') {
                self.pos += 1;
            } else if (c == '/' and self.pos + 1 < self.src.len and self.src[self.pos + 1] == '/') {
                while (self.pos < self.src.len and self.src[self.pos] != '\n') self.pos += 1;
            } else break;
        }
    }

    fn next(self: *Lexer) Token {
        self.skipWs();
        const ln = self.line;
        if (self.pos >= self.src.len) return .{ .tag = .eof, .text = "", .line = ln };
        const c = self.src[self.pos];
        switch (c) {
            '{' => {
                self.pos += 1;
                return .{ .tag = .lbrace, .text = "{", .line = ln };
            },
            '}' => {
                self.pos += 1;
                return .{ .tag = .rbrace, .text = "}", .line = ln };
            },
            '=' => {
                self.pos += 1;
                return .{ .tag = .equals, .text = "=", .line = ln };
            },
            '"' => {
                self.pos += 1;
                const s = self.pos;
                while (self.pos < self.src.len and self.src[self.pos] != '"') {
                    if (self.src[self.pos] == '\\' and self.pos + 1 < self.src.len) self.pos += 1;
                    self.pos += 1;
                }
                const text = self.src[s..self.pos];
                if (self.pos < self.src.len) self.pos += 1;
                return .{ .tag = .string, .text = text, .line = ln };
            },
            '-' => {
                if (self.pos + 1 < self.src.len and self.src[self.pos + 1] == '>') {
                    self.pos += 2;
                    return .{ .tag = .arrow, .text = "->", .line = ln };
                }
                self.pos += 1;
                return .{ .tag = .ident, .text = "-", .line = ln };
            },
            else => {},
        }
        if (std.ascii.isDigit(c)) {
            const s = self.pos;
            while (self.pos < self.src.len and (std.ascii.isDigit(self.src[self.pos]) or self.src[self.pos] == '.' or self.src[self.pos] == '-')) self.pos += 1;
            return .{ .tag = .number, .text = self.src[s..self.pos], .line = ln };
        }
        if (std.ascii.isAlphabetic(c) or c == '_') {
            const s = self.pos;
            while (self.pos < self.src.len and (std.ascii.isAlphanumeric(self.src[self.pos]) or self.src[self.pos] == '_')) self.pos += 1;
            return .{ .tag = .ident, .text = self.src[s..self.pos], .line = ln };
        }
        self.pos += 1;
        return self.next();
    }
};

const Field = struct {
    key: []const u8,
    value: []const u8,
    extra: []const u8 = "",
    tag: Tag = .ident,
    line: usize,
};

const Parser = struct {
    allocator: std.mem.Allocator,
    lex: Lexer,
    cur: Token,
    diags: *std.ArrayList(Diagnostic),

    fn advance(self: *Parser) void {
        self.cur = self.lex.next();
    }

    fn err(self: *Parser, line: usize, msg: []const u8) !void {
        try self.diags.append(.{ .line = line, .message = try std.fmt.allocPrint(self.allocator, "{s}", .{msg}) });
    }

    fn expect(self: *Parser, tag: Tag, what: []const u8) !Token {
        if (self.cur.tag != tag) {
            try self.diags.append(.{ .line = self.cur.line, .message = try std.fmt.allocPrint(self.allocator, "ожидалось {s}, получено '{s}'", .{ what, self.cur.text }) });
            return error.ParseError;
        }
        const t = self.cur;
        self.advance();
        return t;
    }

    fn readBlock(self: *Parser) ![]Field {
        _ = try self.expect(.lbrace, "'{'");
        var fields = std.ArrayList(Field).init(self.allocator);
        while (self.cur.tag != .rbrace and self.cur.tag != .eof) {
            if (self.cur.tag != .ident) {
                try self.err(self.cur.line, "в блоке ожидался ключ");
                return error.ParseError;
            }
            const key = self.cur.text;
            const kline = self.cur.line;
            self.advance();
            if (std.mem.eql(u8, key, "metric")) {
                const name = try self.expect(.ident, "имя метрики");
                _ = try self.expect(.equals, "'='");
                const v = self.cur;
                self.advance();
                try fields.append(.{ .key = "metric", .value = name.text, .extra = v.text, .tag = v.tag, .line = kline });
                continue;
            }
            var val: []const u8 = "";
            var vtag: Tag = .ident;
            if (self.cur.tag == .equals) {
                self.advance();
                val = self.cur.text;
                vtag = self.cur.tag;
                self.advance();
            } else {
                val = self.cur.text;
                vtag = self.cur.tag;
                self.advance();
            }
            try fields.append(.{ .key = key, .value = val, .tag = vtag, .line = kline });
        }
        _ = try self.expect(.rbrace, "'}'");
        return fields.toOwnedSlice();
    }

    fn firstString(fields: []const Field, key: []const u8) ?[]const u8 {
        for (fields) |f| if (std.mem.eql(u8, f.key, key)) return f.value;
        return null;
    }
};

pub fn parse(allocator: std.mem.Allocator, source: []const u8) !ParseResult {
    var diags = std.ArrayList(Diagnostic).init(allocator);

    var p = Parser{ .allocator = allocator, .lex = .{ .src = source }, .cur = undefined, .diags = &diags };
    p.advance();

    var artifacts = std.ArrayList(ast.Artifact).init(allocator);
    var claims = std.ArrayList(ast.Claim).init(allocator);
    var evidence = std.ArrayList(ast.Evidence).init(allocator);
    var proofs = std.ArrayList(ast.Proof).init(allocator);
    var modules = std.ArrayList(ast.Module).init(allocator);
    var links = std.ArrayList(ast.Link).init(allocator);

    var name: []const u8 = "<unnamed>";
    var version: ?[]const u8 = null;
    var root: ?[]const u8 = null;

    while (p.cur.tag != .eof) {
        if (p.cur.tag != .ident) {
            try p.err(p.cur.line, "ожидался блок верхнего уровня");
            break;
        }
        const kw = p.cur.text;
        const kwline = p.cur.line;
        p.advance();

        if (std.mem.eql(u8, kw, "project")) {
            const nm = try p.expect(.string, "имя проекта");
            name = nm.text;
            const f = try p.readBlock();
            if (Parser.firstString(f, "version")) |v| version = v;
            if (Parser.firstString(f, "root")) |v| root = v;
        } else if (std.mem.eql(u8, kw, "artifact")) {
            const path = try p.expect(.string, "путь артефакта");
            const f = try p.readBlock();
            const kind = Parser.firstString(f, "kind") orelse "unknown";
            const hash = Parser.firstString(f, "hash");
            try artifacts.append(.{ .id = try ast.stableId(allocator, .artifact, path.text), .path = path.text, .kind = kind, .hash = hash });
        } else if (std.mem.eql(u8, kw, "claim")) {
            const stmt = try p.expect(.string, "текст утверждения");
            const f = try p.readBlock();
            const status_str = Parser.firstString(f, "status") orelse "unknown";
            const status = ast.Status.fromString(status_str) orelse blk: {
                try p.err(kwline, "неизвестный статус утверждения");
                break :blk ast.Status.unknown;
            };
            var ev_ids = std.ArrayList([]const u8).init(allocator);
            var metrics = std.ArrayList(ast.Metric).init(allocator);
            for (f) |fl| {
                if (std.mem.eql(u8, fl.key, "evidence")) {
                    const eid = try ast.stableId(allocator, .evidence, fl.value);
                    try ev_ids.append(eid);
                    // Дедупликация: одно свидетельство на один источник, даже если
                    // на него ссылаются несколько утверждений (иначе V005-дубликаты).
                    var seen = false;
                    for (evidence.items) |existing| {
                        if (std.mem.eql(u8, existing.id, eid)) {
                            seen = true;
                            break;
                        }
                    }
                    if (!seen) {
                        try evidence.append(.{ .id = eid, .kind = "run", .source = fl.value });
                    }
                } else if (std.mem.eql(u8, fl.key, "metric")) {
                    const v = std.fmt.parseFloat(f64, fl.extra) catch 0;
                    try metrics.append(.{ .name = fl.value, .value = v });
                }
            }
            try claims.append(.{
                .id = try ast.stableId(allocator, .claim, stmt.text),
                .statement = stmt.text,
                .status = status,
                .scope = Parser.firstString(f, "context"),
                .evidence_ids = try ev_ids.toOwnedSlice(),
                .metrics = try metrics.toOwnedSlice(),
            });
        } else if (std.mem.eql(u8, kw, "proof")) {
            const path = try p.expect(.string, "путь доказательства");
            const f = try p.readBlock();
            const system = Parser.firstString(f, "system") orelse "unknown";
            const theorem = Parser.firstString(f, "theorem") orelse "unknown";
            const status_str = Parser.firstString(f, "status") orelse "unknown";
            const status = ast.Status.fromString(status_str) orelse ast.Status.unknown;
            try proofs.append(.{ .id = try ast.stableId(allocator, .proof, path.text), .path = path.text, .system = system, .theorem = theorem, .status = status });
        } else if (std.mem.eql(u8, kw, "module")) {
            const nm = try p.expect(.string, "имя модуля");
            const f = try p.readBlock();
            var reqs = std.ArrayList([]const u8).init(allocator);
            var ens = std.ArrayList([]const u8).init(allocator);
            for (f) |fl| {
                if (std.mem.eql(u8, fl.key, "require")) try reqs.append(fl.value);
                if (std.mem.eql(u8, fl.key, "ensure")) try ens.append(fl.value);
            }
            try modules.append(.{ .id = try ast.stableId(allocator, .module, nm.text), .name = nm.text, .requires = try reqs.toOwnedSlice(), .ensures = try ens.toOwnedSlice() });
        } else if (std.mem.eql(u8, kw, "link")) {
            const from = try p.expect(.string, "источник связи");
            _ = try p.expect(.arrow, "'->'");
            const to = try p.expect(.string, "цель связи");
            const f = try p.readBlock();
            const rel_str = Parser.firstString(f, "relation") orelse "references";
            const rel = ast.RelationKind.fromString(rel_str) orelse blk: {
                try p.err(kwline, "неизвестный тип связи");
                break :blk ast.RelationKind.references;
            };
            try links.append(.{ .from = from.text, .to = to.text, .relation = rel });
        } else {
            try p.err(kwline, "неизвестный блок верхнего уровня");
            _ = try p.readBlock();
        }
    }

    return .{
        .project = .{
            .name = name,
            .version = version,
            .root = root,
            .artifacts = try artifacts.toOwnedSlice(),
            .claims = try claims.toOwnedSlice(),
            .evidence = try evidence.toOwnedSlice(),
            .proofs = try proofs.toOwnedSlice(),
            .modules = try modules.toOwnedSlice(),
            .links = try links.toOwnedSlice(),
        },
        .diagnostics = try diags.toOwnedSlice(),
    };
}

// =========================================================================
// ТЕСТЫ (§15.1 parser tests)
// =========================================================================

test "PARSER: полный проект из примера §6" {
    const src =
        \\project "AI-Connector" {
        \\  version "1.0"
        \\  root "."
        \\}
        \\artifact "src/main.rs" {
        \\  kind "source"
        \\  hash "sha256:abc"
        \\}
        \\claim "throughput improved" {
        \\  status empirical
        \\  evidence "run:vllm_2026_10_09"
        \\  metric tok_per_s = 3832
        \\  context "batch=128"
        \\}
        \\proof "formal/RII.lean" {
        \\  system "Lean4"
        \\  theorem "commit_preserves_consistency"
        \\  status compiled
        \\}
        \\link "claim:throughput improved" -> "artifact:run:vllm_2026_10_09" {
        \\  relation "supported_by"
        \\}
    ;
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const res = try parse(arena.allocator(), src);
    try std.testing.expectEqual(@as(usize, 0), res.diagnostics.len);
    try std.testing.expectEqualStrings("AI-Connector", res.project.name);
    try std.testing.expectEqualStrings("1.0", res.project.version.?);
    try std.testing.expectEqual(@as(usize, 1), res.project.artifacts.len);
    try std.testing.expectEqual(@as(usize, 1), res.project.claims.len);
    try std.testing.expectEqual(@as(usize, 1), res.project.proofs.len);
    try std.testing.expectEqual(@as(usize, 1), res.project.links.len);
    try std.testing.expectEqual(ast.Status.empirical, res.project.claims[0].status);
    try std.testing.expectEqual(@as(usize, 1), res.project.claims[0].metrics.len);
    try std.testing.expectApproxEqAbs(@as(f64, 3832), res.project.claims[0].metrics[0].value, 0.001);
}

test "PARSER: неизвестный статус даёт диагностику, но не падает" {
    const src = "claim \"x\" { status bogus }";
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const res = try parse(arena.allocator(), src);
    try std.testing.expect(res.diagnostics.len >= 1);
    try std.testing.expectEqual(ast.Status.unknown, res.project.claims[0].status);
}

test "PARSER: стабильный ID не меняется при повторном разборе" {
    const src = "claim \"throughput improved\" { status proven }";
    var a1 = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer a1.deinit();
    var a2 = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer a2.deinit();
    const r1 = try parse(a1.allocator(), src);
    const r2 = try parse(a2.allocator(), src);
    try std.testing.expectEqualStrings(r1.project.claims[0].id, r2.project.claims[0].id);
}

test "ФАЗЗИНГ: случайные и битые .kern не паникуют" {
    var prng = std.Random.DefaultPrng.init(0x5EED);
    const rand = prng.random();
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();

    // 1) чисто случайные байты (печатные)
    var i: usize = 0;
    while (i < 3000) : (i += 1) {
        var buf = std.ArrayList(u8).init(a);
        const n = rand.uintLessThan(usize, 300);
        var j: usize = 0;
        while (j < n) : (j += 1) {
            try buf.append(rand.uintLessThan(u8, 95) + 32);
        }
        _ = parse(a, buf.items) catch {};
        _ = arena.reset(.retain_capacity);
    }

    // 2) структурно «почти валидные», но битые
    const bad = [_][]const u8{
        "project",
        "project \"X\" {",
        "project \"X\" {",
        "claim \"a\" { status }",
        "claim \"a\" { status proven evidence }",
        "link \"a\" -> { relation }",
        "link -> \"b\" {}",
        "{\"\"\"}",
        "claim \"\" {}",
        "metric x = = 1",
        "claim \"a\" { status proven } }",
        "}",
        "proof \"\" { system \"\" theorem \"\" status }",
    };
    for (bad) |src| {
        _ = parse(a, src) catch {};
    }
    // 3) глубокая вложенность (не должна ронять стек бесконечно)
    var deep = std.ArrayList(u8).init(a);
    var d: usize = 0;
    while (d < 1000) : (d += 1) try deep.appendSlice("module \"m\" {");
    _ = parse(a, deep.items) catch {};
}
