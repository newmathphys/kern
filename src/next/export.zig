// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN-Next: экспорт — agent packet (§17) и human report (§14.1).
const std = @import("std");
const ast = @import("ast.zig");
const atomic = @import("atomic");
const validate = @import("validate.zig");
const compat = @import("compat");

fn isProven(s: ast.Status) bool {
    return s == .proven or s == .verified or s == .tested or s == .compiled;
}
fn isBlocked(s: ast.Status) bool {
    return s == .blocked or s == .unknown or s == .not_yet_reproducible;
}

fn jsonEscape(w: anytype, s: []const u8) !void {
    for (s) |ch| switch (ch) {
        '"' => try w.writeAll("\\\""),
        '\\' => try w.writeAll("\\\\"),
        '\n' => try w.writeAll("\\n"),
        '\t' => try w.writeAll("\\t"),
        '\r' => try w.writeAll("\\r"),
        0x08 => try w.writeAll("\\b"),
        0x0C => try w.writeAll("\\f"),
        else => {
            // БАГ-ФИКС: JSON запрещает СЫРЫЕ управляющие символы (< 0x20).
            // Раньше они писались как есть -> невалидный JSON.
            if (ch < 0x20) {
                try w.print("\\u{x:0>4}", .{ch});
            } else {
                try w.writeByte(ch);
            }
        },
    };
}

/// Agent Packet (handoff следующему ИИ-агенту): только выжимка — что
/// доказано, что заблокировано, где противоречия, что делать дальше.
pub fn writePacket(allocator: std.mem.Allocator, path: []const u8,
                   p: ast.Project, diags: []const validate.Diagnostic,
                   scope: []const u8) !void {
    var buf = compat.BufWriter.init(allocator);
    defer buf.deinit();
    const w = buf.writer();

    try w.writeAll("{\n");
    try w.writeAll("  \"v\": \"1.3\",\n");
    try w.writeAll("  \"task\": \"verify_claims\",\n");
    try w.writeAll("  \"truth_rule\": \"e=1_only_after_required_verification\",\n");
    try w.writeAll("  \"scope\": \"");
    try jsonEscape(w, scope);
    try w.writeAll("\",\n");

    // proven
    try w.writeAll("  \"proven\": [\n");
    var first = true;
    for (p.claims) |cl| {
        if (!isProven(cl.status)) continue;
        if (!first) try w.writeAll(",\n");
        first = false;
        try w.writeAll("    {\"id\": \"");
        try jsonEscape(w, cl.id);
        try w.writeAll("\", \"status\": \"");
        try w.writeAll(@tagName(cl.status));
        try w.writeAll("\", \"statement\": \"");
        try jsonEscape(w, cl.statement);
        try w.writeAll("\"}");
    }
    try w.writeAll("\n  ],\n");

    // blocked
    try w.writeAll("  \"blocked\": [\n");
    first = true;
    for (p.claims) |cl| {
        if (!isBlocked(cl.status)) continue;
        if (!first) try w.writeAll(",\n");
        first = false;
        try w.writeAll("    {\"id\": \"");
        try jsonEscape(w, cl.id);
        try w.writeAll("\", \"status\": \"");
        try w.writeAll(@tagName(cl.status));
        try w.writeAll("\"}");
    }
    try w.writeAll("\n  ],\n");

    // contradictions
    try w.writeAll("  \"contradictions\": [\n");
    first = true;
    for (p.links) |l| {
        if (l.relation != .contradicts) continue;
        if (!first) try w.writeAll(",\n");
        first = false;
        try w.writeAll("    {\"from\": \"");
        try jsonEscape(w, l.from);
        try w.writeAll("\", \"to\": \"");
        try jsonEscape(w, l.to);
        try w.writeAll("\"}");
    }
    for (p.claims) |cl| {
        if (cl.status != .refuted and cl.status != .conflicted) continue;
        if (!first) try w.writeAll(",\n");
        first = false;
        try w.writeAll("    {\"id\": \"");
        try jsonEscape(w, cl.id);
        try w.writeAll("\", \"reason\": \"refuted\"}");
    }
    try w.writeAll("\n  ],\n");

    // next_steps (из диагностик-ошибок)
    try w.writeAll("  \"next_steps\": [\n");
    first = true;
    for (diags) |d| {
        if (d.severity != .err) continue;
        if (!first) try w.writeAll(",\n");
        first = false;
        try w.writeAll("    \"");
        try w.writeAll(d.code);
        try w.writeAll(": ");
        try jsonEscape(w, d.message);
        try w.writeAll("\"");
    }
    try w.writeAll("\n  ],\n");

    // stats
    var proven: usize = 0;
    var blocked: usize = 0;
    for (p.claims) |cl| {
        if (isProven(cl.status)) proven += 1;
        if (isBlocked(cl.status)) blocked += 1;
    }
    try w.print("  \"stats\": {{\"nodes\": {d}, \"claims\": {d}, \"proven\": {d}, \"blocked\": {d}, \"diagnostics\": {d}}}\n", .{ p.nodeCount(), p.claims.len, proven, blocked, diags.len });
    try w.writeAll("}\n");

    // АТОМАРНО: tmp + fsync + rename (иначе обрыв -> обрезанный packet/report).
    try atomic.writeFileAtomic(allocator, path, buf.items());
}

/// Human report (§14.1): summary, verified claims, blocked, contradictions,
/// next steps.
pub fn writeReport(allocator: std.mem.Allocator, path: []const u8,
                   p: ast.Project, diags: []const validate.Diagnostic) !void {
    var buf = compat.BufWriter.init(allocator);
    defer buf.deinit();
    const w = buf.writer();

    try w.print("# KERN-Next — отчёт по проекту `{s}`\n\n", .{p.name});
    try w.print("Версия: {s}. Узлов: {d}. Диагностик: {d} (ошибок: {d}).\n\n", .{
        p.version orelse "-", p.nodeCount(), diags.len, validate.countErrors(diags),
    });

    try w.writeAll("## Доказанные утверждения\n\n");
    var any = false;
    for (p.claims) |cl| {
        if (!isProven(cl.status)) continue;
        any = true;
        try w.print("- `{s}` [{s}] {s}\n", .{ cl.id, @tagName(cl.status), cl.statement });
    }
    if (!any) try w.writeAll("- (нет)\n");

    try w.writeAll("\n## Заблокированные / неизвестные\n\n");
    any = false;
    for (p.claims) |cl| {
        if (!isBlocked(cl.status)) continue;
        any = true;
        try w.print("- `{s}` [{s}] {s}\n", .{ cl.id, @tagName(cl.status), cl.statement });
    }
    if (!any) try w.writeAll("- (нет)\n");

    try w.writeAll("\n## Противоречия\n\n");
    any = false;
    for (p.links) |l| {
        if (l.relation != .contradicts) continue;
        any = true;
        try w.print("- `{s}` противоречит `{s}`\n", .{ l.from, l.to });
    }
    for (p.claims) |cl| {
        if (cl.status != .refuted and cl.status != .conflicted) continue;
        any = true;
        try w.print("- `{s}` [{s}]\n", .{ cl.id, @tagName(cl.status) });
    }
    if (!any) try w.writeAll("- (нет)\n");

    try w.writeAll("\n## Следующие шаги\n\n");
    any = false;
    for (diags) |d| {
        if (d.severity != .err) continue;
        any = true;
        try w.print("- [{s}] {s}: {s}\n", .{ d.code, d.where, d.message });
    }
    if (!any) try w.writeAll("- (нет)\n");

    // АТОМАРНО: tmp + fsync + rename (иначе обрыв -> обрезанный packet/report).
    try atomic.writeFileAtomic(allocator, path, buf.items());
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "EXPORT: agent packet содержит proven/blocked и валиден как JSON-структура" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const src =
        \\project "P" { version "1" }
        \\claim "ok" { status proven }
        \\claim "bad" { status blocked }
        \\claim "no" { status refuted }
    ;
    const res = try parser.parse(a, src);
    try writePacket(a, "/tmp/kern_packet_test.json", res.project, &.{}, "current-issue");
    defer compat.deleteFile("/tmp/kern_packet_test.json") catch {};
    const data = try compat.readFileAlloc(a, "/tmp/kern_packet_test.json", 1 << 20);
    try std.testing.expect(std.mem.indexOf(u8, data, "\"proven\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, data, "ok") != null);
    try std.testing.expect(std.mem.indexOf(u8, data, "\"blocked\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, data, "current-issue") != null);
}

test "EXPORT: human report содержит разделы" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const res = try parser.parse(a, "project \"P\" { version \"1\" }\nclaim \"ok\" { status proven }");
    try writeReport(a, "/tmp/kern_report_test.md", res.project, &.{});
    defer compat.deleteFile("/tmp/kern_report_test.md") catch {};
    const data = try compat.readFileAlloc(a, "/tmp/kern_report_test.md", 1 << 20);
    try std.testing.expect(std.mem.indexOf(u8, data, "## Доказанные утверждения") != null);
    try std.testing.expect(std.mem.indexOf(u8, data, "## Следующие шаги") != null);
}

test "ФИКС JSON: управляющие символы экранируются (валидный JSON)" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    // claim со спецсимволами: кавычка, бэкслеш, TAB, \x01
    const src = "claim \"q\\\" b\\\\ t\x01 end\" { status proven }";
    const res = try parser.parse(a, src);
    try writePacket(a, "/tmp/json_esc_test.json", res.project, &.{}, "s\x01cope");
    defer compat.deleteFile("/tmp/json_esc_test.json") catch {};
    const data = try compat.readFileAlloc(a, "/tmp/json_esc_test.json", 1 << 20);
    // Сырой \x01 в JSON недопустим
    try std.testing.expect(std.mem.indexOfScalar(u8, data, 0x01) == null);
    try std.testing.expect(std.mem.indexOf(u8, data, "\\u0001") != null);
}
