// Copyright (c) 2026 mrbritneyxxx. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN-Next: SQLite-каталог (.kdb) — §9 спецификации.
//!
//! Таблицы §9.1, индексы §9.2, ограничения §9.3 (стабильные PK, внешние
//! ключи, CHECK по статусам, UNIQUE по путям артефактов).
const std = @import("std");
const ast = @import("ast.zig");
const Project = ast.Project;
const validate = @import("validate.zig");

const c = @cImport({
    @cInclude("sqlite3.h");
});

pub const CatalogError = error{ SqlError, OpenFailed };

pub const Catalog = struct {
    db: *c.sqlite3,
    alloc: std.mem.Allocator,

    pub fn open(alloc: std.mem.Allocator, path: [*:0]const u8) !Catalog {
        var db: ?*c.sqlite3 = null;
        const rc = c.sqlite3_open_v2(path, &db, c.SQLITE_OPEN_READWRITE | c.SQLITE_OPEN_CREATE, null);
        if (rc != c.SQLITE_OK or db == null) return CatalogError.OpenFailed;
        var cat = Catalog{ .db = db.?, .alloc = alloc };
        try cat.exec("PRAGMA foreign_keys = ON;");
        try cat.exec("PRAGMA journal_mode = MEMORY;");
        return cat;
    }

    pub fn close(self: *Catalog) void {
        _ = c.sqlite3_close(self.db);
    }

    fn exec(self: *Catalog, sql: [*:0]const u8) !void {
        var errmsg: [*c]u8 = null;
        if (c.sqlite3_exec(self.db, sql, null, null, &errmsg) != c.SQLITE_OK) {
            if (errmsg != null) c.sqlite3_free(errmsg);
            return CatalogError.SqlError;
        }
    }

    fn execFmt(self: *Catalog, comptime fmt: []const u8, args: anytype) !void {
        const sql = try std.fmt.allocPrintZ(self.alloc, fmt, args);
        defer self.alloc.free(sql);
        try self.exec(sql.ptr);
    }

    /// Экранирование строкового литерала (одинарные кавычки удваиваются).
    fn q(self: *Catalog, s: []const u8) ![]u8 {
        var out = std.ArrayList(u8).init(self.alloc);
        for (s) |ch| {
            if (ch == '\'') try out.append('\'');
            try out.append(ch);
        }
        return out.toOwnedSlice();
    }

    pub fn initSchema(self: *Catalog) !void {
        try self.exec(
            \\CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, version TEXT, root TEXT);
            \\CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, path TEXT UNIQUE, kind TEXT, hash TEXT);
            \\CREATE TABLE IF NOT EXISTS modules(id TEXT PRIMARY KEY, name TEXT);
            \\CREATE TABLE IF NOT EXISTS symbols(id TEXT PRIMARY KEY, artifact_id TEXT, name TEXT);
            \\CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY, statement TEXT, status TEXT CHECK(status IN ('proven','refuted','verified','tested','compiled','empirical','hypothesis','blocked','unknown','not_found','not_yet_reproducible')), scope TEXT);
            \\CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, kind TEXT, source TEXT);
            \\CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY, command TEXT, status TEXT);
            \\CREATE TABLE IF NOT EXISTS proofs(id TEXT PRIMARY KEY, path TEXT, system TEXT, theorem TEXT, status TEXT);
            \\CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT REFERENCES claims(id), name TEXT, value REAL);
            \\CREATE TABLE IF NOT EXISTS relations(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT, to_id TEXT, relation TEXT);
            \\CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, text TEXT);
            \\CREATE TABLE IF NOT EXISTS blockers(id TEXT PRIMARY KEY, text TEXT);
            \\CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, created_at INTEGER);
            \\CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, text TEXT);
            \\CREATE TABLE IF NOT EXISTS agent_packets(id TEXT PRIMARY KEY, scope TEXT);
            \\CREATE TABLE IF NOT EXISTS cache_entries(content_hash TEXT PRIMARY KEY, path TEXT);
            \\CREATE TABLE IF NOT EXISTS diagnostics(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, severity TEXT, where_clause TEXT, message TEXT);
            \\CREATE INDEX IF NOT EXISTS idx_claim_status ON claims(status);
            \\CREATE INDEX IF NOT EXISTS idx_metric_claim ON metrics(claim_id);
            \\CREATE INDEX IF NOT EXISTS idx_rel_from ON relations(from_id);
            \\CREATE INDEX IF NOT EXISTS idx_rel_to ON relations(to_id);
            \\CREATE INDEX IF NOT EXISTS idx_artifact_hash ON artifacts(hash);
        );
    }

    pub fn insertProject(self: *Catalog, p: Project) !void {
        try self.exec("BEGIN;");
        errdefer self.exec("ROLLBACK;") catch {};

        const pname = try self.q(p.name);
        defer self.alloc.free(pname);
        try self.execFmt("INSERT OR REPLACE INTO projects(id,name,version,root) VALUES('project:main','{s}','{s}','{s}');", .{
            pname,
            p.version orelse "",
            p.root orelse "",
        });

        for (p.artifacts) |a| {
            const aid = try self.q(a.id);
            defer self.alloc.free(aid);
            const ap = try self.q(a.path);
            defer self.alloc.free(ap);
            const ak = try self.q(a.kind);
            defer self.alloc.free(ak);
            const ah = try self.q(a.hash orelse "");
            defer self.alloc.free(ah);
            try self.execFmt("INSERT OR REPLACE INTO artifacts(id,path,kind,hash) VALUES('{s}','{s}','{s}','{s}');", .{ aid, ap, ak, ah });
        }

        for (p.evidence) |e| {
            const eid = try self.q(e.id);
            defer self.alloc.free(eid);
            const es = try self.q(e.source);
            defer self.alloc.free(es);
            try self.execFmt("INSERT OR REPLACE INTO evidence(id,kind,source) VALUES('{s}','{s}','{s}');", .{ eid, e.kind, es });
        }

        for (p.claims) |cl| {
            const cid = try self.q(cl.id);
            defer self.alloc.free(cid);
            const st = try self.q(cl.statement);
            defer self.alloc.free(st);
            const sc = try self.q(cl.scope orelse "");
            defer self.alloc.free(sc);
            try self.execFmt("INSERT OR REPLACE INTO claims(id,statement,status,scope) VALUES('{s}','{s}','{s}','{s}');", .{
                cid, st, @tagName(cl.status), sc,
            });
            for (cl.metrics) |m| {
                const mn = try self.q(m.name);
                defer self.alloc.free(mn);
                try self.execFmt("INSERT INTO metrics(claim_id,name,value) VALUES('{s}','{s}',{d});", .{ cid, mn, m.value });
            }
        }

        for (p.proofs) |pr| {
            const pid = try self.q(pr.id);
            defer self.alloc.free(pid);
            const pp = try self.q(pr.path);
            defer self.alloc.free(pp);
            const ps = try self.q(pr.system);
            defer self.alloc.free(ps);
            const pt = try self.q(pr.theorem);
            defer self.alloc.free(pt);
            try self.execFmt("INSERT OR REPLACE INTO proofs(id,path,system,theorem,status) VALUES('{s}','{s}','{s}','{s}','{s}');", .{ pid, pp, ps, pt, @tagName(pr.status) });
        }

        for (p.modules) |m| {
            const mid = try self.q(m.id);
            defer self.alloc.free(mid);
            const mn = try self.q(m.name);
            defer self.alloc.free(mn);
            try self.execFmt("INSERT OR REPLACE INTO modules(id,name) VALUES('{s}','{s}');", .{ mid, mn });
        }

        for (p.links) |l| {
            const lf = try self.q(l.from);
            defer self.alloc.free(lf);
            const lt = try self.q(l.to);
            defer self.alloc.free(lt);
            try self.execFmt("INSERT INTO relations(from_id,to_id,relation) VALUES('{s}','{s}','{s}');", .{ lf, lt, @tagName(l.relation) });
        }

        try self.exec("COMMIT;");
    }

    pub fn insertDiagnostics(self: *Catalog, diags: []const validate.Diagnostic) !void {
        try self.exec("BEGIN;");
        errdefer self.exec("ROLLBACK;") catch {};
        for (diags) |dg| {
            const w = try self.q(dg.where);
            defer self.alloc.free(w);
            const m = try self.q(dg.message);
            defer self.alloc.free(m);
            try self.execFmt("INSERT INTO diagnostics(code,severity,where_clause,message) VALUES('{s}','{s}','{s}','{s}');", .{
                dg.code, @tagName(dg.severity), w, m,
            });
        }
        try self.exec("COMMIT;");
    }

    pub fn recordSnapshot(self: *Catalog, id: []const u8, created_at: i64) !void {
        try self.execFmt("INSERT OR REPLACE INTO snapshots(id,created_at) VALUES('{s}',{d});", .{ id, created_at });
    }

    pub fn recordCacheEntry(self: *Catalog, content_hash: []const u8, path: []const u8) !void {
        const pth = try self.q(path);
        defer self.alloc.free(pth);
        try self.execFmt("INSERT OR REPLACE INTO cache_entries(content_hash,path) VALUES('{s}','{s}');", .{ content_hash, pth });
    }

    /// Запрос: число утверждений по статусу (§9.2: индекс claim status).
    pub fn countClaimsByStatus(self: *Catalog, status: []const u8) !i64 {
        const sql = try std.fmt.allocPrintZ(self.alloc, "SELECT COUNT(*) FROM claims WHERE status='{s}';\x00", .{status});
        defer self.alloc.free(sql);
        var stmt: ?*c.sqlite3_stmt = null;
        if (c.sqlite3_prepare_v2(self.db, sql.ptr, -1, &stmt, null) != c.SQLITE_OK) return CatalogError.SqlError;
        defer _ = c.sqlite3_finalize(stmt);
        if (c.sqlite3_step(stmt) != c.SQLITE_ROW) return CatalogError.SqlError;
        return c.sqlite3_column_int64(stmt, 0);
    }

    pub fn countTable(self: *Catalog, table: []const u8) !i64 {
        const sql = try std.fmt.allocPrintZ(self.alloc, "SELECT COUNT(*) FROM {s};\x00", .{table});
        defer self.alloc.free(sql);
        var stmt: ?*c.sqlite3_stmt = null;
        if (c.sqlite3_prepare_v2(self.db, sql.ptr, -1, &stmt, null) != c.SQLITE_OK) return CatalogError.SqlError;
        defer _ = c.sqlite3_finalize(stmt);
        if (c.sqlite3_step(stmt) != c.SQLITE_ROW) return CatalogError.SqlError;
        return c.sqlite3_column_int64(stmt, 0);
    }
};

// =========================================================================
// ТЕСТЫ (§15.2: каталог)
// =========================================================================

test "CATALOG: схема, вставка проекта и запрос по статусу" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();

    var cat = try Catalog.open(a, ":memory:");
    defer cat.close();
    try cat.initSchema();

    const src =
        \\project "P" { version "1" }
        \\artifact "a.rs" { kind "source" }
        \\claim "c1" { status proven }
        \\claim "c2" { status proven }
        \\claim "c3" { status hypothesis }
    ;
    const res = try parser.parse(a, src);
    try cat.insertProject(res.project);

    try std.testing.expectEqual(@as(i64, 3), try cat.countTable("claims"));
    try std.testing.expectEqual(@as(i64, 2), try cat.countClaimsByStatus("proven"));
    try std.testing.expectEqual(@as(i64, 1), try cat.countClaimsByStatus("hypothesis"));
    try std.testing.expectEqual(@as(i64, 1), try cat.countTable("artifacts"));
}

const parser = @import("parser.zig");

test "CATALOG РЕГРЕССИЯ: одинарная кавычка в id/тексте не ломает SQL" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var cat = try Catalog.open(a, ":memory:");
    defer cat.close();
    try cat.initSchema();
    // Раньше падало с SqlError: id 'claim:it's ...' не экранировался.
    const src = "claim \"it's a 'quoted' claim\" { status proven }";
    const res = try parser.parse(a, src);
    try cat.insertProject(res.project);
    try std.testing.expectEqual(@as(i64, 1), try cat.countTable("claims"));
}

test "PARSER РЕГРЕССИЯ: повторный evidence дедуплицируется" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const src =
        \\project "P" { version "1" }
        \\claim "a" { status proven evidence "run:same" }
        \\claim "b" { status proven evidence "run:same" }
    ;
    const res = try parser.parse(a, src);
    try std.testing.expectEqual(@as(usize, 1), res.project.evidence.len);
    const diags = try validate.validate(a, res.project);
    try std.testing.expectEqual(@as(usize, 0), validate.countErrors(diags));
}
