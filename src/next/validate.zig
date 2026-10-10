// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN-Next: валидатор (§8 спецификации). Возвращает структурированные
//! диагностики, а не падает.
const std = @import("std");
const ast = @import("ast.zig");
const Project = ast.Project;

pub const Severity = enum { err, warning, info };

pub const Diagnostic = struct {
    code: []const u8,
    severity: Severity,
    where: []const u8,
    message: []const u8,
};

const KNOWN_ARTIFACT_KINDS = [_][]const u8{ "source", "binary", "doc", "config", "data", "schema", "unknown" };

fn isHex(s: []const u8) bool {
    if (s.len == 0) return false;
    for (s) |c| if (!std.ascii.isHex(c)) return false;
    return true;
}

fn hashOk(h: []const u8) bool {
    // Формат: <algo>:<hex>. Поддерживаем sha256/blake3 по 64 hex-символа.
    const idx = std.mem.indexOfScalar(u8, h, ':') orelse return false;
    const algo = h[0..idx];
    const hex = h[idx + 1 ..];
    if (!(std.mem.eql(u8, algo, "sha256") or std.mem.eql(u8, algo, "blake3"))) return false;
    return hex.len == 64 and isHex(hex);
}

pub fn validate(allocator: std.mem.Allocator, p: Project) ![]Diagnostic {
    var d = std.ArrayList(Diagnostic).init(allocator);

    const add = struct {
        fn f(list: *std.ArrayList(Diagnostic), code: []const u8, sev: Severity, where: []const u8, msg: []const u8) !void {
            try list.append(.{ .code = code, .severity = sev, .where = where, .message = msg });
        }
    }.f;

    // (2) обязательные поля проекта
    if (p.name.len == 0 or std.mem.eql(u8, p.name, "<unnamed>"))
        try add(&d, "V002", .err, "project", "не задано имя проекта");

    // Карта ID для проверок ссылок (правила 4, 5, 6)
    var ids = std.StringHashMap(ast.Kind).init(allocator);
    defer ids.deinit();

    for (p.artifacts) |a| {
        // (1) известный вид артефакта
        var known = false;
        for (KNOWN_ARTIFACT_KINDS) |k| if (std.mem.eql(u8, k, a.kind)) {
            known = true;
        };
        if (!known) try add(&d, "V001", .warning, a.id, "неизвестный вид артефакта");
        // (2) путь обязателен
        if (a.path.len == 0) try add(&d, "V002", .err, a.id, "пустой путь артефакта");
        // (7) формат хэша
        if (a.hash) |h| if (!hashOk(h)) try add(&d, "V007", .err, a.id, "неверный формат хэша (ожидается algo:hex64)");
        // (5) дубликаты ID
        const gop = try ids.getOrPut(a.id);
        if (gop.found_existing) try add(&d, "V005", .err, a.id, "дубликат ID артефакта");
        gop.value_ptr.* = .artifact;
    }

    for (p.evidence) |e| {
        const gop = try ids.getOrPut(e.id);
        if (gop.found_existing) try add(&d, "V005", .err, e.id, "дубликат ID свидетельства");
        gop.value_ptr.* = .evidence;
    }

    for (p.claims) |c| {
        if (c.statement.len == 0) try add(&d, "V002", .err, c.id, "пустое утверждение");
        // (10) blocked/unknown должны быть явно помечены
        if (c.status == .blocked or c.status == .unknown)
            if (c.scope == null) try add(&d, "V010", .warning, c.id, "blocked/unknown без явной пометки (context)");
        // (8) метрики
        for (c.metrics) |m| {
            if (m.name.len == 0) try add(&d, "V008", .err, c.id, "метрика без имени");
            if (std.math.isNan(m.value)) try add(&d, "V008", .err, c.id, "метрика NaN");
        }
        // (4) ссылки на свидетельства
        for (c.evidence_ids) |eid| {
            if (!ids.contains(eid)) try add(&d, "V004", .warning, c.id, "ссылка на неразрешённое свидетельство");
        }
        const gop = try ids.getOrPut(c.id);
        if (gop.found_existing) try add(&d, "V005", .err, c.id, "дубликат ID утверждения");
        gop.value_ptr.* = .claim;
    }

    for (p.proofs) |pr| {
        // (9) у доказательства должны быть путь и система
        if (pr.path.len == 0) try add(&d, "V009", .err, pr.id, "у доказательства нет пути");
        if (std.mem.eql(u8, pr.system, "unknown")) try add(&d, "V009", .err, pr.id, "у доказательства не указана система");
        const gop = try ids.getOrPut(pr.id);
        if (gop.found_existing) try add(&d, "V005", .err, pr.id, "дубликат ID доказательства");
        gop.value_ptr.* = .proof;
    }

    for (p.modules) |m| {
        const gop = try ids.getOrPut(m.id);
        if (gop.found_existing) try add(&d, "V005", .err, m.id, "дубликат ID модуля");
        gop.value_ptr.* = .module;
    }

    // (6) концы связей должны существовать
    for (p.links) |l| {
        if (!ids.contains(l.from)) try add(&d, "V006", .warning, l.from, "источник связи не разрешён");
        if (!ids.contains(l.to)) try add(&d, "V006", .warning, l.to, "цель связи не разрешена");
    }

    return d.toOwnedSlice();
}

pub fn countErrors(diags: []const Diagnostic) usize {
    var n: usize = 0;
    for (diags) |x| if (x.severity == .err) {
        n += 1;
    };
    return n;
}

// =========================================================================
// ТЕСТЫ (§15.2 validation tests)
// =========================================================================

test "VALIDATE: чистый проект без ошибок" {
    const parser = @import("parser.zig");
    const src =
        \\project "P" { version "1" }
        \\artifact "a.rs" { kind "source" hash "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
        \\claim "c" { status proven evidence "run:1" }
        \\link "claim:c" -> "artifact:a.rs" { relation "supported_by" }
    ;
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const res = try parser.parse(arena.allocator(), src);
    const diags = try validate(arena.allocator(), res.project);
    try std.testing.expectEqual(@as(usize, 0), countErrors(diags));
}

test "VALIDATE: битый хэш и дубликат ID ловятся" {
    const parser = @import("parser.zig");
    const src =
        \\project "P" { version "1" }
        \\artifact "a.rs" { kind "source" hash "md5:zz" }
        \\artifact "a.rs" { kind "source" }
        \\proof "p.lean" { status compiled }
    ;
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const res = try parser.parse(arena.allocator(), src);
    const diags = try validate(arena.allocator(), res.project);
    var saw_hash = false;
    var saw_dup = false;
    var saw_proof = false;
    for (diags) |x| {
        if (std.mem.eql(u8, x.code, "V007")) saw_hash = true;
        if (std.mem.eql(u8, x.code, "V005")) saw_dup = true;
        if (std.mem.eql(u8, x.code, "V009")) saw_proof = true;
    }
    try std.testing.expect(saw_hash and saw_dup and saw_proof);
}
