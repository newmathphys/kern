// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: кэш доказательств (§ «Инкрементальный Кэш Пруфов»).
//! Ключ — sha256(AST || контракт || свидетелль). Экономит повторные вызовы
//! внешнего решателя (Z3/Lean) — это и есть «экономика токенов/Fuel».
const std = @import("std");
const cov = @import("cov.zig");
const gate = @import("verifier/admission_gate.zig");

pub const ProofCache = struct {
    map: std.AutoHashMap([32]u8, gate.CheckerVerdict),
    hits: usize = 0,
    misses: usize = 0,
    evictions: usize = 0,
    /// Лимит записей. При переполнении вытесняется самая старая (FIFO).
    max_entries: usize = 10_000,
    /// ПОТОКОБЕЗОПАСНОСТЬ: без мьютекса параллельные get/put — гонка (race).
    mutex: std.Thread.Mutex = .{},
    /// SINGLE-FLIGHT: не даёт N потокам одновременно звать решатель для ОДНОЙ
    /// формулы («thundering herd»). Первый считает, остальные ждут и берут кэш.
    flight: std.Thread.Mutex = .{},

    pub fn init(allocator: std.mem.Allocator) ProofCache {
        return .{ .map = std.AutoHashMap([32]u8, gate.CheckerVerdict).init(allocator) };
    }

    /// Эффективность кэша: hits / (hits + misses) * 100%.
    pub fn efficiencyPct(self: ProofCache) f64 {
        const tot = self.hits + self.misses;
        if (tot == 0) return 0;
        return 100.0 * @as(f64, @floatFromInt(self.hits)) / @as(f64, @floatFromInt(tot));
    }

    pub fn deinit(self: *ProofCache) void {
        self.map.deinit();
    }

    pub fn keyOf(ast: [32]u8, contract: [32]u8, proof: []const u8) [32]u8 {
        var hasher = std.crypto.hash.sha2.Sha256.init(.{});
        hasher.update(&ast);
        hasher.update(&contract);
        hasher.update(proof);
        var out: [32]u8 = undefined;
        hasher.final(&out);
        return out;
    }

    pub fn get(self: *ProofCache, k: [32]u8) ?gate.CheckerVerdict {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.map.get(k)) |v| {
            cov.hit(.cache_hit);
            self.hits += 1;
            return v;
        }
        cov.hit(.cache_miss);
        self.misses += 1;
        return null;
    }

    pub fn put(self: *ProofCache, k: [32]u8, v: gate.CheckerVerdict) !void {
        self.mutex.lock();
        defer self.mutex.unlock();
        // ЭВИКЦИЯ: не даём кэшу расти бесконечно (защита от OOM).
        if (self.max_entries > 0 and self.map.count() >= self.max_entries and !self.map.contains(k)) {
            var it = self.map.keyIterator();
            if (it.next()) |key| {
                _ = self.map.remove(key.*);
                cov.hit(.cache_evict);
                self.evictions += 1;
            }
        }
        try self.map.put(k, v);
    }
};

/// Обёртка: чекер, который сначала смотрит в кэш.
fn cachedFn(ctx: ?*anyopaque, allocator: std.mem.Allocator,
            ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    const Ctx = struct { cache: *ProofCache, inner: gate.TrustedChecker };
    const c: *Ctx = @ptrCast(@alignCast(ctx.?));
    const k = ProofCache.keyOf(ast, contract, proof);
    // SINGLE-FLIGHT: держим «flight» на время вычисления. Потоки с той же
    // формулой ждут, затем берут готовый результат из кэша (1 miss, N-1 hits).
    c.cache.flight.lock();
    defer c.cache.flight.unlock();
    if (c.cache.get(k)) |v| return v;
    const v = c.inner.run(allocator, ast, contract, proof);
    c.cache.put(k, v) catch {};
    return v;
}

pub fn cachedChecker(holder: *CtxHolder, cache: *ProofCache, inner: gate.TrustedChecker) gate.TrustedChecker {
    holder.* = .{ .cache = cache, .inner = inner };
    return .{ .ctx = holder, .runFn = cachedFn };
}

/// Владелец контекста обёртки (чтобы ctx жил дольше чекера).
pub const CtxHolder = struct { cache: *ProofCache, inner: gate.TrustedChecker };

// =========================================================================
// ТЕСТЫ
// =========================================================================

fn stubProved(ctx: ?*anyopaque, allocator: std.mem.Allocator,
              ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    return .Proved;
}

test "PROOF-CACHE: второй вызов берётся из кэша" {
    var cache = ProofCache.init(std.testing.allocator);
    defer cache.deinit();
    var holder: CtxHolder = undefined;
    const chk = cachedChecker(&holder, &cache, gate.TrustedChecker{ .runFn = stubProved });

    const ast = [_]u8{0x01} ** 32;
    const con = [_]u8{0x02} ** 32;
    const v1 = chk.run(std.testing.allocator, ast, con, "proof-x");
    const v2 = chk.run(std.testing.allocator, ast, con, "proof-x");
    try std.testing.expectEqual(gate.CheckerVerdict.Proved, v1);
    try std.testing.expectEqual(gate.CheckerVerdict.Proved, v2);
    try std.testing.expectEqual(@as(usize, 1), cache.misses);
    try std.testing.expectEqual(@as(usize, 1), cache.hits);

    // другой payload → промах
    _ = chk.run(std.testing.allocator, ast, con, "proof-y");
    try std.testing.expectEqual(@as(usize, 2), cache.misses);
}

test "PROOF-CACHE: ключ зависит от payload" {
    const a = ProofCache.keyOf([_]u8{1} ** 32, [_]u8{2} ** 32, "a");
    const b = ProofCache.keyOf([_]u8{1} ** 32, [_]u8{2} ** 32, "b");
    try std.testing.expect(!std.mem.eql(u8, &a, &b));
}

test "КЭШ: ключ детерминирован (нет коллизий разных формул)" {
    const ast = [_]u8{0x01} ** 32;
    const con = [_]u8{0x02} ** 32;
    // одинаковые входы -> одинаковый ключ
    try std.testing.expectEqual(ProofCache.keyOf(ast, con, "(= x 1)"),
        ProofCache.keyOf(ast, con, "(= x 1)"));
    // разные формулы -> разные ключи (даже похожие)
    try std.testing.expect(!std.mem.eql(u8, &ProofCache.keyOf(ast, con, "(= x 1)"),
        &ProofCache.keyOf(ast, con, "(= x 2)")));
    try std.testing.expect(!std.mem.eql(u8, &ProofCache.keyOf(ast, con, "x"),
        &ProofCache.keyOf(ast, con, "y")));
}

test "КЭШ: эвикция при переполнении (без утечек)" {
    var cache = ProofCache.init(std.testing.allocator);
    defer cache.deinit();
    cache.max_entries = 100;
    var i: usize = 0;
    while (i < 1000) : (i += 1) {
        var k: [32]u8 = undefined;
        std.mem.writeInt(u64, k[0..8], i, .little);
        try cache.put(k, .Proved);
    }
    try std.testing.expect(cache.map.count() <= 100);
    try std.testing.expect(cache.evictions >= 900);
}

test "КЭШ: efficiencyPct считает правильно" {
    var cache = ProofCache.init(std.testing.allocator);
    defer cache.deinit();
    var holder: CtxHolder = undefined;
    const chk = cachedChecker(&holder, &cache, gate.TrustedChecker{ .runFn = stubProved });
    const ast = [_]u8{0x01} ** 32;
    const con = [_]u8{0x02} ** 32;
    _ = chk.run(std.testing.allocator, ast, con, "p"); // miss
    _ = chk.run(std.testing.allocator, ast, con, "p"); // hit
    _ = chk.run(std.testing.allocator, ast, con, "p"); // hit
    try std.testing.expectApproxEqAbs(@as(f64, 66.67), cache.efficiencyPct(), 0.1);
}

fn countFn(counter: *std.atomic.Value(usize), ctx: ?*anyopaque, allocator: std.mem.Allocator,
           ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    _ = counter.fetchAdd(1, .monotonic);
    std.time.sleep(2 * std.time.ns_per_ms); // имитация «тяжёлого» решателя
    return .Proved;
}

test "ПЧЕЛИНЫЙ РОЙ: 64 потока -> 1 miss + 63 hits (single-flight)" {
    var cache = ProofCache.init(std.testing.allocator);
    defer cache.deinit();
    var calls = std.atomic.Value(usize).init(0);

    const Ctx = struct { cache: *ProofCache, counter: *std.atomic.Value(usize) };
    var c = Ctx{ .cache = &cache, .counter = &calls };
    const chk = gate.TrustedChecker{ .ctx = &c, .runFn = struct {
        fn f(ctx: ?*anyopaque, allocator: std.mem.Allocator, ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
            const cc: *Ctx = @ptrCast(@alignCast(ctx.?));
            return countFn(cc.counter, null, allocator, ast, contract, proof);
        }
    }.f };

    var holder: CtxHolder = undefined;
    const cached = cachedChecker(&holder, &cache, chk);

    const ast = [_]u8{0x11} ** 32;
    const con = [_]u8{0x22} ** 32;
    var threads: [64]std.Thread = undefined;
    var results: [64]gate.CheckerVerdict = undefined;
    for (&threads, 0..) |*th, i| {
        th.* = try std.Thread.spawn(.{}, struct {
            fn run(ch: gate.TrustedChecker, a: [32]u8, c2: [32]u8, out: *gate.CheckerVerdict) void {
                out.* = ch.run(std.testing.allocator, a, c2, "same-formula");
            }
        }.run, .{ cached, ast, con, &results[i] });
    }
    for (&threads) |*th| th.join();
    for (results) |r| try std.testing.expectEqual(gate.CheckerVerdict.Proved, r);

    try std.testing.expectEqual(@as(usize, 1), calls.load(.monotonic)); // решатель вызван РОВНО 1 раз
    try std.testing.expectEqual(@as(usize, 1), cache.misses);
    try std.testing.expectEqual(@as(usize, 63), cache.hits);
}
