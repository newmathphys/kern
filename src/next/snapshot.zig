// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN-Next: snapshot и diff (§10 .kbin-контейнер, §6.1 стадии Snapshot/Diff).
//! Формат снапшота — детерминированный, отсортированный текст: воспроизводим
//! побайтно и удобен для diff (критерии 4 и 7 из §20).
const std = @import("std");
const ast = @import("ast.zig");
const validate = @import("validate.zig");
const atomic = @import("atomic");

pub const Snapshot = struct {
    lines: [][]const u8,
    /// 🔴 ДЕФЕКТ (найден аудитом, ИСПРАВЛЕН): `readFile` возвращал срезы ВНУТРЬ
    /// прочитанного буфера, но сам буфер не отдавал — до 16 МБ на снапшот
    /// утекали (арена в CLI маскировала утечку, библиотека — нет).
    /// Теперь снапшот ВЛАДЕЕТ буфером и освобождает его в `deinit`.
    backing: ?[]u8 = null,

    pub fn deinit(self: *Snapshot, allocator: std.mem.Allocator) void {
        if (self.backing) |b| {
            // readFile: строки — СРЕЗЫ внутрь буфера, отдельно не выделялись.
            allocator.free(b);
        } else {
            // build: каждая строка выделена отдельно (allocPrint).
            for (self.lines) |l| allocator.free(l);
        }
        allocator.free(self.lines);
    }
};

fn cmp(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.order(u8, a, b) == .lt;
}

fn contains(hay: []const []const u8, needle: []const u8) bool {
    for (hay) |h| if (std.mem.eql(u8, h, needle)) return true;
    return false;
}

pub fn build(allocator: std.mem.Allocator, p: ast.Project, diags: []const validate.Diagnostic) !Snapshot {
    var list = std.ArrayList([]const u8).init(allocator);
    try list.append(try std.fmt.allocPrint(allocator, "project\t{s}\t{s}\t{s}", .{ p.name, p.version orelse "-", p.root orelse "-" }));
    for (p.artifacts) |a| try list.append(try std.fmt.allocPrint(allocator, "artifact\t{s}\t{s}\t{s}\t{s}", .{ a.id, a.path, a.kind, a.hash orelse "-" }));
    for (p.evidence) |e| try list.append(try std.fmt.allocPrint(allocator, "evidence\t{s}\t{s}", .{ e.id, e.source }));
    for (p.claims) |cl| try list.append(try std.fmt.allocPrint(allocator, "claim\t{s}\t{s}\t{s}", .{ cl.id, @tagName(cl.status), cl.statement }));
    for (p.proofs) |pr| try list.append(try std.fmt.allocPrint(allocator, "proof\t{s}\t{s}\t{s}\t{s}", .{ pr.id, @tagName(pr.status), pr.path, pr.system }));
    for (p.modules) |m| try list.append(try std.fmt.allocPrint(allocator, "module\t{s}\t{s}", .{ m.id, m.name }));
    for (p.links) |l| try list.append(try std.fmt.allocPrint(allocator, "relation\t{s}\t{s}\t{s}", .{ l.from, l.to, @tagName(l.relation) }));
    for (diags) |d| try list.append(try std.fmt.allocPrint(allocator, "diagnostic\t{s}\t{s}\t{s}\t{s}", .{ d.code, @tagName(d.severity), d.where, d.message }));
    const items = try list.toOwnedSlice();
    std.mem.sort([]const u8, items, {}, cmp);
    return .{ .lines = items };
}

pub fn writeFile(allocator: std.mem.Allocator, path: []const u8, snap: Snapshot) !void {
    var buf = std.ArrayList(u8).init(allocator);
    defer buf.deinit();
    for (snap.lines) |l| {
        try buf.appendSlice(l);
        try buf.append('\n');
    }
    // АТОМАРНО: обрыв записи не должен оставить обрезанный снапшот
    // (по нему принимается решение «файл не изменился»).
    try atomic.writeFileAtomic(allocator, path, buf.items);
}

pub fn readFile(allocator: std.mem.Allocator, path: []const u8) !Snapshot {
    const data = try std.fs.cwd().readFileAlloc(allocator, path, 1 << 24);
    var list = std.ArrayList([]const u8).init(allocator);
    var it = std.mem.splitScalar(u8, data, '\n');
    while (it.next()) |l| if (l.len > 0) {
        try list.append(l);
    };
    const items = try list.toOwnedSlice();
    std.mem.sort([]const u8, items, {}, cmp);
    return .{ .lines = items, .backing = data };
}

pub const Diff = struct {
    added: [][]const u8,
    removed: [][]const u8,

    /// Освободить результат diff (строки принадлежат ему).
    pub fn deinit(self: *Diff, allocator: std.mem.Allocator) void {
        for (self.added) |s| allocator.free(s);
        for (self.removed) |s| allocator.free(s);
        allocator.free(self.added);
        allocator.free(self.removed);
    }
};

pub fn diffSnapshots(allocator: std.mem.Allocator, a: Snapshot, b: Snapshot) !Diff {
    var added = std.ArrayList([]const u8).init(allocator);
    var removed = std.ArrayList([]const u8).init(allocator);
    // КОПИРУЕМ строки: результат diff не должен зависеть от времени жизни
    // снапшотов (иначе после их освобождения получим висячие указатели).
    for (b.lines) |l| if (!contains(a.lines, l)) {
        try added.append(try allocator.dupe(u8, l));
    };
    for (a.lines) |l| if (!contains(b.lines, l)) {
        try removed.append(try allocator.dupe(u8, l));
    };
    return .{ .added = try added.toOwnedSlice(), .removed = try removed.toOwnedSlice() };
}

// =========================================================================
// ТЕСТЫ (§15.4/§15.5: snapshot + roundtrip + diff)
// =========================================================================

test "SNAPSHOT: сборка детерминирована и отсортирована" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const src =
        \\project "P" { version "1" }
        \\claim "c" { status proven }
        \\artifact "a.rs" { kind "source" }
    ;
    const r1 = try parser.parse(a, src);
    const r2 = try parser.parse(a, src);
    const s1 = try build(a, r1.project, &.{});
    const s2 = try build(a, r2.project, &.{});
    try std.testing.expectEqual(s1.lines.len, s2.lines.len);
    for (s1.lines, s2.lines) |x, y| try std.testing.expectEqualStrings(x, y);
    // отсортировано
    for (s1.lines[0 .. s1.lines.len - 1], s1.lines[1..]) |x, y| try std.testing.expect(std.mem.order(u8, x, y) == .lt);
}

test "УТЕЧКИ: Snapshot/Diff полностью освобождаются (проверка testing.allocator)" {
    // ДЕФЕКТ (был): readFile возвращал срезы внутрь буфера, но не отдавал
    // сам буфер — утечка до 16 МБ на снапшот (арена в CLI это маскировала).
    const parser = @import("parser.zig");
    // Парсер аллоцирует много мелких объектов — его вызовы уводим в арену,
    // чтобы детектор утечек проверял ИМЕННО код snapshot (build/readFile/diff).
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const pa = arena.allocator();
    const p1 = try parser.parse(pa, "claim \"c1\" { status proven }");
    const p2 = try parser.parse(pa, "claim \"c1\" { status proven }\nclaim \"c2\" { status refuted }");

    const a = std.testing.allocator; // детектор утечек для snapshot

    var s1 = try build(a, p1.project, &.{});
    defer s1.deinit(a); // build: строки выделены отдельно
    var s2 = try build(a, p2.project, &.{});
    defer s2.deinit(a);

    const path_a = "/tmp/kern_snap_leak_a.ksnap";
    const path_b = "/tmp/kern_snap_leak_b.ksnap";
    defer std.fs.cwd().deleteFile(path_a) catch {};
    defer std.fs.cwd().deleteFile(path_b) catch {};
    try writeFile(a, path_a, s1);
    try writeFile(a, path_b, s2);

    var ra = try readFile(a, path_a);
    defer ra.deinit(a); // readFile: владеет буфером
    var rb = try readFile(a, path_b);
    defer rb.deinit(a);

    var d = try diffSnapshots(a, ra, rb);
    defer d.deinit(a); // результат diff владеет своими строками

    try std.testing.expectEqual(@as(usize, 1), d.added.len);
    try std.testing.expectEqual(@as(usize, 0), d.removed.len);
    // Если бы diff возвращал срезы в rb, после rb.deinit здесь был бы
    // висячий указатель. Копия гарантирует корректность.
    try std.testing.expect(std.mem.indexOf(u8, d.added[0], "c2") != null);
}

test "DIFF: добавленное утверждение видно" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const old = try parser.parse(a, "claim \"c1\" { status proven }");
    const new = try parser.parse(a, "claim \"c1\" { status proven }\nclaim \"c2\" { status refuted }");
    const s_old = try build(a, old.project, &.{});
    const s_new = try build(a, new.project, &.{});
    const d = try diffSnapshots(a, s_old, s_new);
    try std.testing.expectEqual(@as(usize, 1), d.added.len);
    try std.testing.expectEqual(@as(usize, 0), d.removed.len);
    try std.testing.expect(std.mem.indexOf(u8, d.added[0], "c2") != null);
}
