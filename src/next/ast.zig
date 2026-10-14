// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN-Next: модель данных (§5, §7 спецификации KERN-Next).
const std = @import("std");

/// Статусная система (§7). Типизирована, а не свободный текст.
pub const Status = enum {
    proven,
    refuted,
    verified,
    tested,
    compiled,
    empirical,
    hypothesis,
    blocked,
    unknown,
    not_found,
    not_yet_reproducible,
    /// КОНФЛИКТ (Белнап B): есть и подтверждающее, и опровергающее исполнение.
    /// Расширение словаря §7 — необходимо для аккумулятора joinK.
    conflicted,

    pub fn fromString(s: []const u8) ?Status {
        inline for (@typeInfo(Status).@"enum".field_names) |f| {
            if (std.mem.eql(u8, s, f)) return @field(Status, f);
        }
        return null;
    }
};

/// Виды объектов (§5).
pub const Kind = enum {
    project,
    artifact,
    module,
    symbol,
    claim,
    evidence,
    execution,
    proof,
    metric,
    relation,
    decision,
    blocker,
    snapshot,
    question,
    agent_packet,
    cache_entry,

    pub fn fromString(s: []const u8) ?Kind {
        inline for (@typeInfo(Kind).@"enum".field_names) |f| {
            if (std.mem.eql(u8, s, f)) return @field(Kind, f);
        }
        return null;
    }
};

/// Разрешённые типы связей (§4.4).
pub const RelationKind = enum {
    supported_by, depends_on, imports, calls, implements, documents, tests,
    proves, contradicts, updates, duplicates, references, generates,
    derived_from, blocked_by,

    pub fn fromString(s: []const u8) ?RelationKind {
        inline for (@typeInfo(RelationKind).@"enum".field_names) |f| {
            if (std.mem.eql(u8, s, f)) return @field(RelationKind, f);
        }
        return null;
    }
};

pub const Artifact = struct {
    id: []const u8,
    path: []const u8,
    kind: []const u8,
    hash: ?[]const u8,
};

pub const Metric = struct { name: []const u8, value: f64 };

pub const Claim = struct {
    id: []const u8,
    statement: []const u8,
    status: Status,
    scope: ?[]const u8,
    evidence_ids: []const []const u8,
    metrics: []const Metric,
};

pub const Evidence = struct {
    id: []const u8,
    kind: []const u8,
    source: []const u8,
};

pub const Proof = struct {
    id: []const u8,
    path: []const u8,
    system: []const u8,
    theorem: []const u8,
    status: Status,
};

pub const Module = struct {
    id: []const u8,
    name: []const u8,
    requires: []const []const u8,
    ensures: []const []const u8,
};

pub const Link = struct {
    from: []const u8,
    to: []const u8,
    relation: RelationKind,
};

pub const Project = struct {
    name: []const u8,
    version: ?[]const u8,
    root: ?[]const u8,
    artifacts: []const Artifact,
    claims: []const Claim,
    evidence: []const Evidence,
    proofs: []const Proof,
    modules: []const Module,
    links: []const Link,

    pub fn nodeCount(self: Project) usize {
        return 1 + self.artifacts.len + self.claims.len + self.evidence.len +
            self.proofs.len + self.modules.len + self.links.len;
    }
};

/// Стабильный ID: `kind:slug`. Детерминирован от имени → не меняется
/// между пересборками (критерий 9 из §20).
pub fn stableId(allocator: std.mem.Allocator, kind: Kind, name: []const u8) ![]const u8 {
    return std.fmt.allocPrint(allocator, "{s}:{s}", .{ @tagName(kind), name });
}

/// Нормализация: нижний регистр, пробелы → `_` (для slug).
///
/// ⚠️ ДЕФЕКТ #54 (найден тестом 2026-10-14): раньше использовался только
/// `std.ascii.toLower`, поэтому **кириллица не понижалась**: «Вердикт»
/// оставался «Вердикт». Для проекта, который работает с русскими
/// утверждениями («QA и вердикт»), это означало, что два разных написания
/// одного имени дают РАЗНЫЕ slug — то есть нормализация не выполнялась.
///
/// Теперь понижаются и ASCII, и кириллица (UTF-8, 2-байтовые
/// последовательности `D0 xx` / `D1 xx`). Длина НЕ меняется: Ё→ё тоже
/// укладывается в 2 байта (`D0 81` → `D1 91`).
pub fn slugify(allocator: std.mem.Allocator, s: []const u8) ![]const u8 {
    const out = try allocator.alloc(u8, s.len);
    var i: usize = 0;
    while (i < s.len) {
        const c = s[i];
        if (c == ' ') {
            out[i] = '_';
            i += 1;
            continue;
        }
        // Кириллица — 2 байта. ВАЖНО: переход НЕ единообразный.
        //   А..П  (D0 90..9F) -> а..п (D0 B0..BF)   — ведущий байт тот же
        //   Р..Я  (D0 A0..AF) -> р..я (D1 80..8F)   — ведущий D0 -> D1
        //   Ё     (D0 81)     -> ё    (D1 91)
        if (c == 0xD0 and i + 1 < s.len) {
            const n = s[i + 1];
            if (n >= 0x90 and n <= 0x9F) { // А..П
                out[i] = 0xD0;
                out[i + 1] = n + 0x20;
                i += 2;
                continue;
            }
            if (n >= 0xA0 and n <= 0xAF) { // Р..Я
                out[i] = 0xD1;
                out[i + 1] = n - 0x20;
                i += 2;
                continue;
            }
            if (n == 0x81) { // Ё
                out[i] = 0xD1;
                out[i + 1] = 0x91;
                i += 2;
                continue;
            }
        }
        out[i] = std.ascii.toLower(c);
        i += 1;
    }
    return out;
}

pub fn isKnownStatus(s: []const u8) bool {
    return Status.fromString(s) != null;
}

// =========================================================================
// ТЕСТЫ (добавлены аудитом 2026-10-14: модуль был БЕЗ прямых тестов)
// =========================================================================

const testing = std.testing;

test "AST: Status.fromString знает ВСЕ объявленные статусы" {
    // Круговой обход: каждое поле enum обязано парситься обратно.
    inline for (@typeInfo(Status).@"enum".field_names) |f| {
        const got = Status.fromString(f);
        try testing.expect(got != null);
        try testing.expectEqualStrings(f, @tagName(got.?));
    }
}

test "AST: Status.fromString отвергает неизвестное (регистр важен)" {
    try testing.expect(Status.fromString("PROVEN") == null); // регистр
    try testing.expect(Status.fromString("proven ") == null); // пробел
    try testing.expect(Status.fromString("") == null);
    try testing.expect(Status.fromString("не-статус") == null);
}

test "AST: conflicted — часть словаря статусов (Белнап B)" {
    // Расширение §7 для аккумулятора joinK: без него конфликт невыразим.
    try testing.expectEqual(Status.conflicted, Status.fromString("conflicted").?);
}

test "AST: Kind.fromString и RelationKind.fromString — круговой обход" {
    inline for (@typeInfo(Kind).@"enum".field_names) |f| {
        try testing.expect(Kind.fromString(f) != null);
    }
    inline for (@typeInfo(RelationKind).@"enum".field_names) |f| {
        try testing.expect(RelationKind.fromString(f) != null);
    }
    try testing.expect(Kind.fromString("не-вид") == null);
    try testing.expect(RelationKind.fromString("не-связь") == null);
}

test "AST: nodeCount считает проект + все коллекции" {
    var empty = Project{
        .name = "p", .version = null, .root = null,
        .artifacts = &.{}, .claims = &.{}, .evidence = &.{},
        .proofs = &.{}, .modules = &.{}, .links = &.{},
    };
    // Пустой проект — это ОДИН узел (сам проект), не ноль.
    try testing.expectEqual(@as(usize, 1), empty.nodeCount());

    const arts = [_]Artifact{.{ .id = "a", .path = "p", .kind = "k", .hash = null }};
    const claims = [_]Claim{
        .{ .id = "c1", .statement = "t1", .status = .unknown, .scope = null, .evidence_ids = &.{}, .metrics = &.{} },
        .{ .id = "c2", .statement = "t2", .status = .unknown, .scope = null, .evidence_ids = &.{}, .metrics = &.{} },
    };
    empty.artifacts = &arts;
    empty.claims = &claims;
    try testing.expectEqual(@as(usize, 4), empty.nodeCount());
}

test "AST: stableId детерминирован и формата kind:name" {
    const a = try stableId(testing.allocator, .claim, "QA и вердикт");
    defer testing.allocator.free(a);
    const b = try stableId(testing.allocator, .claim, "QA и вердикт");
    defer testing.allocator.free(b);
    // Критерий 9 из §20: ID не меняется между пересборками.
    try testing.expectEqualStrings(a, b);
    try testing.expectEqualStrings("claim:QA и вердикт", a);
}

test "AST: stableId различает вид при том же имени" {
    const c = try stableId(testing.allocator, .claim, "x");
    defer testing.allocator.free(c);
    const e = try stableId(testing.allocator, .evidence, "x");
    defer testing.allocator.free(e);
    try testing.expect(!std.mem.eql(u8, c, e));
}

test "AST: slugify — нижний регистр, пробелы в подчёркивания" {
    const s = try slugify(testing.allocator, "QA и Вердикт TEST");
    defer testing.allocator.free(s);
    try testing.expectEqualStrings("qa_и_вердикт_test", s);
    try testing.expectEqual(@as(usize, "QA и Вердикт TEST".len), s.len);
}

test "AST: slugify сохраняет длину (не расширяется в байтах)" {
    // Важно: многобайтовый UTF-8 не должен «размножаться».
    const src = "привет мир";
    const s = try slugify(testing.allocator, src);
    defer testing.allocator.free(s);
    try testing.expectEqual(src.len, s.len);
    // «привет» = 6 букв × 2 байта = 12 байт, значит пробел на индексе 12.
    try testing.expect(s[12] == '_');
}

test "AST: slugify понижает КИРИЛЛИЦУ (дефект #54)" {
    // Раньше `std.ascii.toLower` не трогал не-ASCII: «Вердикт» оставался
    // «Вердикт», и два написания одного имени давали РАЗНЫЕ slug.
    const s = try slugify(testing.allocator, "ВЕРДИКТ ЁЖ");
    defer testing.allocator.free(s);
    try testing.expectEqualStrings("вердикт_ёж", s);
    // Длина не изменилась (Ё→ё укладывается в 2 байта).
    try testing.expectEqual(@as(usize, "ВЕРДИКТ ЁЖ".len), s.len);
}

test "AST: slugify идемпотентен (повторная нормализация не меняет)" {
    const once = try slugify(testing.allocator, "Тест ИДЕМПОТЕНТНОСТИ");
    defer testing.allocator.free(once);
    const twice = try slugify(testing.allocator, once);
    defer testing.allocator.free(twice);
    try testing.expectEqualStrings(once, twice);
}

test "AST: isKnownStatus согласован со Status.fromString" {
    try testing.expect(isKnownStatus("tested"));
    try testing.expect(isKnownStatus("conflicted"));
    try testing.expect(!isKnownStatus("ТЕСТ"));
    try testing.expect(!isKnownStatus(""));
}
