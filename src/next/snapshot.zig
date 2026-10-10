// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN-Next: snapshot и diff (§10 .kbin-контейнер, §6.1 стадии Snapshot/Diff).
//! Формат снапшота — детерминированный, отсортированный текст: воспроизводим
//! побайтно и удобен для diff (критерии 4 и 7 из §20).
const std = @import("std");
const ast = @import("ast.zig");
const validate = @import("validate.zig");

pub const Snapshot = struct { lines: [][]const u8 };

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
    const f = try std.fs.cwd().createFile(path, .{});
    defer f.close();
    var buf = std.ArrayList(u8).init(allocator);
    defer buf.deinit();
    for (snap.lines) |l| {
        try buf.appendSlice(l);
        try buf.append('\n');
    }
    try f.writeAll(buf.items);
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
    return .{ .lines = items };
}

pub const Diff = struct { added: [][]const u8, removed: [][]const u8 };

pub fn diffSnapshots(allocator: std.mem.Allocator, a: Snapshot, b: Snapshot) !Diff {
    var added = std.ArrayList([]const u8).init(allocator);
    var removed = std.ArrayList([]const u8).init(allocator);
    for (b.lines) |l| if (!contains(a.lines, l)) {
        try added.append(l);
    };
    for (a.lines) |l| if (!contains(b.lines, l)) {
        try removed.append(l);
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
