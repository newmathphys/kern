//! KERN-Next: движок конвейера (§6.1): parse → validate → catalog → snapshot
//! → packet/report, с инкрементальным кэшем (§6.2).
const std = @import("std");
const ast = @import("ast.zig");
const parser = @import("parser.zig");
const validate = @import("validate.zig");
const catalog = @import("catalog.zig");
const snapshot = @import("snapshot.zig");
const exp = @import("export.zig");
const truth = @import("truth.zig");
const cache = @import("cache.zig");

pub const BuildOutcome = struct {
    nodes: usize,
    claims: usize,
    diagnostics: usize,
    errors: usize,
    skipped: bool,
};

pub fn build(allocator: std.mem.Allocator, source_path: []const u8,
             out_dir: []const u8, scope: []const u8, force: bool) !BuildOutcome {
    const source = try std.fs.cwd().readFileAlloc(allocator, source_path, 1 << 24);
    defer allocator.free(source);
    const hash = try cache.sha256Hex(allocator, source);
    defer allocator.free(hash);

    std.fs.cwd().makePath(out_dir) catch {};

    const cache_path = try std.fmt.allocPrint(allocator, "{s}/.kerncache", .{out_dir});
    defer allocator.free(cache_path);
    var c = try cache.Cache.load(allocator, cache_path);

    const snap_path = try std.fmt.allocPrint(allocator, "{s}/project.ksnap", .{out_dir});
    defer allocator.free(snap_path);

    if (!force and c.isUnchanged(source_path, hash)) {
        if (std.fs.cwd().access(snap_path, .{})) |_| {
            return .{ .nodes = 0, .claims = 0, .diagnostics = 0, .errors = 0, .skipped = true };
        } else |_| {}
    }

    const res = try parser.parse(allocator, source);
    var project = res.project;
    // РЕЗОЛЮЦИЯ: машинные свидетельства исполнения -> статус (Белнап-аккумулятор).
    const resolved = try truth.resolve(allocator, project);
    project.claims = resolved.claims;
    const diags = try validate.validate(allocator, project);

    const kdb_path = try std.fmt.allocPrintZ(allocator, "{s}/project.kdb", .{out_dir});
    defer allocator.free(kdb_path);
    var cat = try catalog.Catalog.open(allocator, kdb_path.ptr);
    defer cat.close();
    try cat.initSchema();
    try cat.insertProject(project);
    try cat.insertDiagnostics(diags);
    try cat.recordSnapshot("snapshot:latest", std.time.timestamp());
    try cat.recordCacheEntry(hash, source_path);

    const snap = try snapshot.build(allocator, project, diags);
    try snapshot.writeFile(allocator, snap_path, snap);

    const packet_path = try std.fmt.allocPrint(allocator, "{s}/agent_packet.json", .{out_dir});
    defer allocator.free(packet_path);
    try exp.writePacket(allocator, packet_path, project, diags, scope);

    const report_path = try std.fmt.allocPrint(allocator, "{s}/report.md", .{out_dir});
    defer allocator.free(report_path);
    try exp.writeReport(allocator, report_path, project, diags);

    try c.put(source_path, hash);
    try c.save(cache_path);

    return .{
        .nodes = project.nodeCount(),
        .claims = project.claims.len,
        .diagnostics = diags.len,
        .errors = validate.countErrors(diags),
        .skipped = false,
    };
}

pub fn diffFiles(allocator: std.mem.Allocator, a: []const u8, b: []const u8) !snapshot.Diff {
    const sa = try snapshot.readFile(allocator, a);
    const sb = try snapshot.readFile(allocator, b);
    return snapshot.diffSnapshots(allocator, sa, sb);
}

// =========================================================================
// ТЕСТЫ (§15.5 roundtrip: build → snapshot → diff)
// =========================================================================

test "ENGINE: build пишет каталог, снапшот, packet и report" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();

    const dir = "/tmp/kernnext_engine_test";
    std.fs.cwd().deleteTree(dir) catch {};
    defer std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    const src_path = "/tmp/kernnext_engine_test/p.kern";
    const src =
        \\project "P" { version "1" }
        \\artifact "a.rs" { kind "source" }
        \\claim "ok" { status proven }
    ;
    {
        const f = try std.fs.cwd().createFile(src_path, .{});
        defer f.close();
        try f.writeAll(src);
    }

    const out1 = try build(a, src_path, dir, "issue-1", false);
    try std.testing.expect(!out1.skipped);
    try std.testing.expect(out1.claims == 1);

    try std.fs.cwd().access("/tmp/kernnext_engine_test/project.kdb", .{});
    try std.fs.cwd().access("/tmp/kernnext_engine_test/project.ksnap", .{});
    try std.fs.cwd().access("/tmp/kernnext_engine_test/agent_packet.json", .{});
    try std.fs.cwd().access("/tmp/kernnext_engine_test/report.md", .{});

    // повторный запуск без изменений → пропуск (критерий 10)
    const out2 = try build(a, src_path, dir, "issue-1", false);
    try std.testing.expect(out2.skipped);

    // --force пересобирает
    const out3 = try build(a, src_path, dir, "issue-1", true);
    try std.testing.expect(!out3.skipped);
}
