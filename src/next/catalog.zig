// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN-Next: SQLite-каталог (.kdb) — §9 спецификации.
//!
//! Таблицы §9.1, индексы §9.2, ограничения §9.3 (стабильные PK, внешние
//! ключи, CHECK по статусам, UNIQUE по путям артефактов).
const std = @import("std");
const ast = @import("ast.zig");
const Project = ast.Project;
const validate = @import("validate.zig");

// Zig 0.17: `@cImport` удалён. Модуль `c_sqlite` создаётся в build.zig
// через `addTranslateC` из include/sqlite3_bridge.h.
const c = @import("c_sqlite");

pub const CatalogError = error{ SqlError, OpenFailed, UnknownTable };

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
            // ДЕФЕКТ (исправлен): сообщение SQLite молча освобождалось —
            // диагностика ошибок была невозможна. Теперь печатаем причину.
            if (errmsg != null) {
                std.debug.print("[!] SQLite: {s}\n", .{std.mem.span(errmsg)});
                c.sqlite3_free(errmsg);
            }
            return CatalogError.SqlError;
        }
    }

    fn execFmt(self: *Catalog, comptime fmt: []const u8, args: anytype) !void {
        const sql = try std.fmt.allocPrintSentinel(self.alloc, fmt, args, 0);
        defer self.alloc.free(sql);
        try self.exec(sql.ptr);
    }

    /// Экранирование строкового литерала (одинарные кавычки удваиваются).
    fn q(self: *Catalog, s: []const u8) ![]u8 {
        var out = std.array_list.Managed(u8).init(self.alloc);
        for (s) |ch| {
            if (ch == '\'') try out.append('\'');
            try out.append(ch);
        }
        return out.toOwnedSlice();
    }

    /// СПИСОК СТАТУСОВ ДЛЯ CHECK-ОГРАНИЧЕНИЯ, СОБРАННЫЙ ИЗ `ast.Status` НА ЭТАПЕ
    /// КОМПИЛЯЦИИ. ЗАЧЕМ (дефект #423): список был скопирован РУКАМИ, и
    /// `conflicted` — статус, который производит аккумулятор joinK (Белнап B),
    /// — в него НЕ попал. Тогда `kernx build` на проекте с конфликтом ПАДАЛ на
    /// CHECK-ограничении, то есть ГЛАВНАЯ возможность (конфликт B(1,1) не
    /// теряется) была НЕПРЕДСТАВИМА в каталоге. Два источника правды для одного
    /// словаря расходятся молча; здесь он ОДИН.
    pub const status_check_list = blk: {
        var out: []const u8 = "";
        for (@typeInfo(ast.Status).@"enum".field_names, 0..) |f, i| {
            if (i != 0) out = out ++ ",";
            out = out ++ "'" ++ f ++ "'";
        }
        break :blk out;
    };

    /// DDL таблицы `claims` — ЕДИНСТВЕННОЕ место, где задан CHECK-список.
    const claims_ddl = "CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY, statement TEXT, " ++
        "status TEXT CHECK(status IN (" ++ status_check_list ++ ")), scope TEXT);";

    /// Прочитать ОДНО текстовое значение (или null).
    fn scalarText(self: *Catalog, sql: [*:0]const u8) !?[]u8 {
        var stmt: ?*c.sqlite3_stmt = null;
        if (c.sqlite3_prepare_v2(self.db, sql, -1, &stmt, null) != c.SQLITE_OK)
            return CatalogError.SqlError;
        defer _ = c.sqlite3_finalize(stmt);
        if (c.sqlite3_step(stmt) != c.SQLITE_ROW) return null;
        const ptr = c.sqlite3_column_text(stmt, 0);
        if (ptr == null) return null;
        const n: usize = @intCast(c.sqlite3_column_bytes(stmt, 0));
        const out = try self.alloc.alloc(u8, n);
        @memcpy(out, ptr[0..n]);
        return out;
    }

    /// МИГРАЦИЯ CHECK-ОГРАНИЧЕНИЯ ТАБЛИЦЫ `claims` (дефект #423).
    ///
    /// ЗАЧЕМ. `CREATE TABLE IF NOT EXISTS` НЕ меняет существующую таблицу,
    /// поэтому каталог, созданный ДО починки, хранит СТАРЫЙ CHECK-список (без
    /// `conflicted`), и `kernx build` на проекте с конфликтом ПАДАЕТ.
    /// ИЗМЕРЕНО на каталоге, созданном до правки: та же ошибка ограничения.
    ///
    /// ПРАВИЛО: пересоздать таблицу и ПЕРЕНЕСТИ данные. Строки, чей статус в
    /// новый список не входит, НЕ выбрасываются молча — о них сообщается.
    fn migrateClaimsStatusCheck(self: *Catalog) !void {
        const cur = (try self.scalarText(
            "SELECT sql FROM sqlite_master WHERE name='claims';")) orelse return;
        defer self.alloc.free(cur);
        if (std.mem.indexOf(u8, cur, status_check_list) != null) return; // актуальна
        std.debug.print("[i] миграция каталога: CHECK-список `claims` устарел — пересоздаю таблицу\n", .{});
        // ПРОЦЕДУРА ИЗ ДОКУМЕНТАЦИИ SQLITE (12 шагов, здесь — необходимый минимум).
        // ЗАЧЕМ ТАК. ИЗМЕРЕНО: голый `ALTER TABLE claims RENAME TO …`
        // ПЕРЕПИСЫВАЕТ ссылки в ДРУГИХ таблицах (`metrics.claim_id REFERENCES
        // "claims_old"(id)`), и после удаления старой таблицы ссылка становится
        // ВИСЯЧЕЙ — каждая следующая операция падает с
        // `no such table: main.claims_old`. Это делало каталог непригодным.
        // `legacy_alter_table=ON` запрещает переписывание ссылок, а
        // `foreign_keys=OFF` — проверки во время перестройки.
        try self.exec("PRAGMA foreign_keys = OFF;");
        try self.exec("PRAGMA legacy_alter_table = ON;");
        try self.exec("ALTER TABLE claims RENAME TO claims_migr;");
        try self.exec(claims_ddl);
        try self.exec("INSERT OR IGNORE INTO claims(id,statement,status,scope) " ++
            "SELECT id,statement,status,scope FROM claims_migr;");
        const lost = (try self.countTable("claims_migr")) - (try self.countTable("claims"));
        if (lost > 0) std.debug.print(
            "[!] миграция: {d} строк(и) со статусом ВНЕ словаря НЕ перенесены\n", .{lost});
        try self.exec("DROP TABLE claims_migr;");
        try self.exec("PRAGMA legacy_alter_table = OFF;");
        try self.exec("PRAGMA foreign_keys = ON;");
        // ЦЕЛОСТНОСТЬ: после миграции ссылки обязаны сходиться. Если нет —
        // сообщаем ГРОМКО (молчаливая порча каталога недопустима).
        const fk = (try self.scalarText("PRAGMA foreign_key_check;")) orelse null;
        if (fk) |bad| {
            defer self.alloc.free(bad);
            std.debug.print("[!] миграция: foreign_key_check нашёл нарушение: {s}\n", .{bad});
        }
    }

    pub fn initSchema(self: *Catalog) !void {
        try self.exec(
            \\CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, version TEXT, root TEXT);
            \\CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, path TEXT UNIQUE, kind TEXT, hash TEXT);
            \\CREATE TABLE IF NOT EXISTS modules(id TEXT PRIMARY KEY, name TEXT);
            \\CREATE TABLE IF NOT EXISTS symbols(id TEXT PRIMARY KEY, artifact_id TEXT, name TEXT);
        ++ claims_ddl ++
            \\
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
            \\CREATE TABLE IF NOT EXISTS audit_chain(seq INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
            \\CREATE INDEX IF NOT EXISTS idx_claim_status ON claims(status);
            \\CREATE INDEX IF NOT EXISTS idx_metric_claim ON metrics(claim_id);
            \\CREATE INDEX IF NOT EXISTS idx_rel_from ON relations(from_id);
            \\CREATE INDEX IF NOT EXISTS idx_rel_to ON relations(to_id);
            \\CREATE INDEX IF NOT EXISTS idx_artifact_hash ON artifacts(hash);
        );
        // ДЕФЕКТ #423: существующий каталог СО СТАРЫМ CHECK-списком иначе остался бы
        // сломанным навсегда (`CREATE TABLE IF NOT EXISTS` его не меняет).
        try self.migrateClaimsStatusCheck();
    }

    pub fn insertProject(self: *Catalog, p: Project) !void {
        try self.exec("BEGIN;");
        errdefer self.exec("ROLLBACK;") catch {};

        const pname = try self.q(p.name);
        defer self.alloc.free(pname);
        const pver = try self.q(p.version orelse "");
        defer self.alloc.free(pver);
        const proot = try self.q(p.root orelse "");
        defer self.alloc.free(proot);
        try self.execFmt("INSERT OR REPLACE INTO projects(id,name,version,root) VALUES('project:main','{s}','{s}','{s}');", .{
            pname, pver, proot,
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
            const ek = try self.q(e.kind);
            defer self.alloc.free(ek);
            try self.execFmt("INSERT OR REPLACE INTO evidence(id,kind,source) VALUES('{s}','{s}','{s}');", .{ eid, ek, es });
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
            const code = try self.q(dg.code);
            defer self.alloc.free(code);
            try self.execFmt("INSERT INTO diagnostics(code,severity,where_clause,message) VALUES('{s}','{s}','{s}','{s}');", .{
                code, @tagName(dg.severity), w, m,
            });
        }
        try self.exec("COMMIT;");
    }

    pub fn recordSnapshot(self: *Catalog, id: []const u8, created_at: i64) !void {
        const sid = try self.q(id);
        defer self.alloc.free(sid);
        try self.execFmt("INSERT OR REPLACE INTO snapshots(id,created_at) VALUES('{s}',{d});", .{ sid, created_at });
    }

    pub fn recordCacheEntry(self: *Catalog, content_hash: []const u8, path: []const u8) !void {
        const pth = try self.q(path);
        defer self.alloc.free(pth);
        const ch = try self.q(content_hash);
        defer self.alloc.free(ch);
        try self.execFmt("INSERT OR REPLACE INTO cache_entries(content_hash,path) VALUES('{s}','{s}');", .{ ch, pth });
    }

    /// Запрос: число утверждений по статусу (§9.2: индекс claim status).
    pub fn countClaimsByStatus(self: *Catalog, status: []const u8) !i64 {
        const st = try self.q(status);
        defer self.alloc.free(st);
        const sql = try std.fmt.allocPrintSentinel(self.alloc, "SELECT COUNT(*) FROM claims WHERE status='{s}';", .{st}, 0);
        defer self.alloc.free(sql);
        var stmt: ?*c.sqlite3_stmt = null;
        if (c.sqlite3_prepare_v2(self.db, sql.ptr, -1, &stmt, null) != c.SQLITE_OK) return CatalogError.SqlError;
        defer _ = c.sqlite3_finalize(stmt);
        if (c.sqlite3_step(stmt) != c.SQLITE_ROW) return CatalogError.SqlError;
        return c.sqlite3_column_int64(stmt, 0);
    }

    /// РАЗРЕШЁННЫЕ таблицы: имя таблицы НЕЛЬЗЯ экранировать кавычками
    /// (это идентификатор, а не литерал), поэтому используем БЕЛЫЙ СПИСОК.
    /// ДЕФЕКТ (был): произвольная подстановка `{s}` в имя таблицы — это
    /// классический вектор SQL-инъекции через имя объекта.
    const ALLOWED_TABLES = [_][]const u8{
        "projects",   "artifacts", "modules",   "symbols", "claims",
        "evidence",   "executions", "proofs",   "metrics", "relations",
        "decisions",  "blockers",  "snapshots", "questions", "cache_entries",
        "diagnostics", "claims_migr",
    };

    pub fn countTable(self: *Catalog, table: []const u8) !i64 {
        var allowed = false;
        for (ALLOWED_TABLES) |t| {
            if (std.mem.eql(u8, t, table)) {
                allowed = true;
                break;
            }
        }
        if (!allowed) return CatalogError.UnknownTable;
        const sql = try std.fmt.allocPrintSentinel(self.alloc, "SELECT COUNT(*) FROM {s};", .{table}, 0);
        defer self.alloc.free(sql);
        var stmt: ?*c.sqlite3_stmt = null;
        if (c.sqlite3_prepare_v2(self.db, sql.ptr, -1, &stmt, null) != c.SQLITE_OK) return CatalogError.SqlError;
        defer _ = c.sqlite3_finalize(stmt);
        if (c.sqlite3_step(stmt) != c.SQLITE_ROW) return CatalogError.SqlError;
        return c.sqlite3_column_int64(stmt, 0);
    }
    // =====================================================================
    //  ЭШЕЛОН 2, ПУНКТ 11: TAMPER-EVIDENT MERKLE AUDIT CHAIN
    //
    //  ЗАЧЕМ. Журнал вердиктов Белнапа — это аудиторский след (требование
    //  EU AI Act): задним числом нельзя ни подменить запись, ни удалить
    //  неудобный провал `F`. Каждая запись связывается с предыдущей:
    //
    //      hash_i = BLAKE3(prev_hash_i || record_i)
    //
    //  Подмена или удаление ЛЮБОЙ записи ломает цепочку (и разрыв в `seq`).
    // =====================================================================

    pub const AuditStatus = union(enum) {
        ok: usize,
        broken: struct { seq: i64, why: []const u8 },
    };

    fn hex32(digest: [32]u8, out: *[64]u8) []const u8 {
        const hexd = "0123456789abcdef";
        for (digest, 0..) |b, i| {
            out[i * 2] = hexd[b >> 4];
            out[i * 2 + 1] = hexd[b & 0x0f];
        }
        return out[0..64];
    }

    /// Хеш ЗАПИСИ: BLAKE3(prev_hash || record). Разделитель не нужен: длина
    /// `prev_hash` фиксирована (64 hex-символа), поэтому склейка однозначна.
    fn chainHash(prev_hash: []const u8, record: []const u8, out: *[64]u8) []const u8 {
        var h = std.crypto.hash.Blake3.init(.{});
        h.update(prev_hash);
        h.update(record);
        var d: [32]u8 = undefined;
        h.final(&d);
        return hex32(d, out);
    }

    /// Последний `hash` цепочки (или 64 нуля, если журнал пуст).
    fn lastChainHash(self: *Catalog, buf: *[64]u8) ![]const u8 {
        const sql = "SELECT hash FROM audit_chain ORDER BY seq DESC LIMIT 1;";
        var stmt: ?*c.sqlite3_stmt = null;
        if (c.sqlite3_prepare_v2(self.db, sql, -1, &stmt, null) != c.SQLITE_OK) return error.Sql;
        defer _ = c.sqlite3_finalize(stmt);
        const rc = c.sqlite3_step(stmt);
        if (rc == c.SQLITE_ROW) {
            const txt = c.sqlite3_column_text(stmt, 0);
            const n = c.sqlite3_column_bytes(stmt, 0);
            if (txt != null and n == 64) {
                @memcpy(buf, txt[0..64]);
                return buf[0..64];
            }
        }
        @memset(buf, '0');
        return buf[0..64];
    }

    /// ДОБАВИТЬ ЗАПИСЬ В ЖУРНАЛ (аудит-след вердикта).
    pub fn appendAudit(self: *Catalog, record: []const u8) !void {
        var pb: [64]u8 = undefined;
        const prev = try self.lastChainHash(&pb);
        var hb: [64]u8 = undefined;
        const h = chainHash(prev, record, &hb);
        const r = try self.q(record);
        defer self.alloc.free(r);
        try self.execFmt("INSERT INTO audit_chain(record,prev_hash,hash) VALUES('{s}','{s}','{s}');", .{ r, prev, h });
    }

    /// ПРОВЕРИТЬ ЦЕЛОСТНОСТЬ ЖУРНАЛА: пересчитать всю цепочку.
    ///
    /// Ловит и ПОДМЕНУ записи (несовпадение хеша), и УДАЛЕНИЕ (разрыв `seq`).
    pub fn verifyAudit(self: *Catalog) !AuditStatus {
        const sql = "SELECT seq,record,prev_hash,hash FROM audit_chain ORDER BY seq;";
        var stmt: ?*c.sqlite3_stmt = null;
        if (c.sqlite3_prepare_v2(self.db, sql, -1, &stmt, null) != c.SQLITE_OK) return error.Sql;
        defer _ = c.sqlite3_finalize(stmt);
        var prev_buf: [64]u8 = undefined;
        @memset(&prev_buf, '0');
        var count: usize = 0;
        var expect_seq: i64 = 1;
        while (c.sqlite3_step(stmt) == c.SQLITE_ROW) {
            const seq = c.sqlite3_column_int64(stmt, 0);
            const rt = c.sqlite3_column_text(stmt, 1);
            const rn: usize = @intCast(c.sqlite3_column_bytes(stmt, 1));
            const pt = c.sqlite3_column_text(stmt, 2);
            const pn: usize = @intCast(c.sqlite3_column_bytes(stmt, 2));
            const ht = c.sqlite3_column_text(stmt, 3);
            const hn: usize = @intCast(c.sqlite3_column_bytes(stmt, 3));
            if (seq != expect_seq) return .{ .broken = .{ .seq = seq, .why = "разрыв в seq — запись УДАЛЕНА" } };
            expect_seq += 1;
            const record = if (rt != null) rt[0..rn] else "";
            const prev = if (pt != null) pt[0..pn] else "";
            const stored = if (ht != null) ht[0..hn] else "";
            if (!std.mem.eql(u8, prev, prev_buf[0..])) {
                return .{ .broken = .{ .seq = seq, .why = "prev_hash не совпал с предыдущей записью" } };
            }
            var hb: [64]u8 = undefined;
            const h = chainHash(prev, record, &hb);
            if (!std.mem.eql(u8, h, stored)) {
                return .{ .broken = .{ .seq = seq, .why = "hash не совпал — запись ПОДМЕНЕНА" } };
            }
            @memcpy(&prev_buf, stored[0..64]);
            count += 1;
        }
        return .{ .ok = count };
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

test "CATALOG РЕГРЕССИЯ (#423): ЛЮБОЙ статус из ast.Status ВСТАВЛЯЕТСЯ" {
    // ЗАЧЕМ. CHECK-список в схеме был скопирован РУКАМИ и разошёлся с `ast.Status`:
    // `conflicted` — статус, который производит аккумулятор joinK (Белнап B), — в него
    // не попал, и `kernx build` на проекте с конфликтом ПАДАЛ на CHECK-ограничении.
    // Тест перебирает ВЕСЬ словарь, поэтому следующее расхождение ловится ЗДЕСЬ, а не
    // в бою (класс #423: два источника правды для одного словаря расходятся молча).
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();

    var cat = try Catalog.open(a, ":memory:");
    defer cat.close();
    try cat.initSchema();

    inline for (@typeInfo(ast.Status).@"enum".field_names) |f| {
        const sql = try std.fmt.allocPrintSentinel(a,
            "INSERT OR REPLACE INTO claims(id,statement,status,scope) VALUES('c:{s}','x','{s}','');",
            .{ f, f }, 0);
        cat.exec(sql) catch |e| {
            std.debug.print("[!] статус '{s}' НЕ вставляется: {s}\n", .{ f, @errorName(e) });
            return e;
        };
    }
    const n = @typeInfo(ast.Status).@"enum".field_names.len;
    try std.testing.expectEqual(@as(i64, n), try cat.countTable("claims"));
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

test "SQL-ИНЪЕКЦИЯ: кавычки в version/root/kind/code экранируются" {
    // ДЕФЕКТ (был): version, root, evidence.kind и diagnostics.code
    // подставлялись в SQL БЕЗ экранирования (в отличие от id/statement).
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var cat = try Catalog.open(a, ":memory:");
    defer cat.close();
    try cat.initSchema();

    const src =
        \\project "p'x" {
        \\  version "1'0"
        \\  root "a'b"
        \\}
        \\artifact "a1" {
        \\  path "src/x.zig"
        \\  kind "source'kind"
        \\}
        \\claim "c" { status proven }
    ;
    const res = try parser.parse(a, src);
    try cat.insertProject(res.project); // не должно падать
    try std.testing.expectEqual(@as(i64, 1), try cat.countTable("projects"));
    try std.testing.expectEqual(@as(i64, 1), try cat.countTable("artifacts"));

    // Диагностика с кавычкой в коде тоже не должна ломать SQL.
    const diags = [_]validate.Diagnostic{.{
        .code = "V'001",
        .severity = .warning,
        .where = "w'here",
        .message = "m'essage",
    }};
    try cat.insertDiagnostics(&diags);
    try std.testing.expectEqual(@as(i64, 1), try cat.countTable("diagnostics"));

    // Белый список таблиц: произвольное имя отвергается.
    try std.testing.expectError(CatalogError.UnknownTable, cat.countTable("claims; DROP TABLE claims;--"));
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

test "АУДИТ-ЦЕПОЧКА: 3 записи проходят проверку (позитивный контроль)" {
    var cat = try Catalog.open(std.testing.allocator, ":memory:");
    defer cat.close();
    try cat.initSchema();
    try cat.appendAudit("verdict: T (1,0) claim=a");
    try cat.appendAudit("verdict: F (0,1) claim=b");
    try cat.appendAudit("verdict: B (1,1) claim=c");
    const st = try cat.verifyAudit();
    try std.testing.expect(st == .ok);
    try std.testing.expectEqual(@as(usize, 3), st.ok);
}

test "АУДИТ-ЦЕПОЧКА: ПОДМЕНА записи ловится" {
    var cat = try Catalog.open(std.testing.allocator, ":memory:");
    defer cat.close();
    try cat.initSchema();
    try cat.appendAudit("verdict: T (1,0) claim=a");
    try cat.appendAudit("verdict: F (0,1) claim=b");
    try cat.appendAudit("verdict: T (1,0) claim=c");
    // Задним числом «улучшаем» провал F -> T (ровно то, против чего строим).
    try cat.exec("UPDATE audit_chain SET record='verdict: T (1,0) claim=b' WHERE seq=2;");
    const st = try cat.verifyAudit();
    try std.testing.expect(st == .broken);
    try std.testing.expectEqual(@as(i64, 2), st.broken.seq);
}

test "АУДИТ-ЦЕПОЧКА: УДАЛЕНИЕ записи ловится (разрыв seq)" {
    var cat = try Catalog.open(std.testing.allocator, ":memory:");
    defer cat.close();
    try cat.initSchema();
    try cat.appendAudit("verdict: T (1,0) claim=a");
    try cat.appendAudit("verdict: F (0,1) claim=b");
    try cat.appendAudit("verdict: T (1,0) claim=c");
    try cat.exec("DELETE FROM audit_chain WHERE seq=2;");
    const st = try cat.verifyAudit();
    try std.testing.expect(st == .broken);
    try std.testing.expectEqual(@as(i64, 3), st.broken.seq);
}
