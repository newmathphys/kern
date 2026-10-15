// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: кэш доказательств (§ «Инкрементальный Кэш Пруфов»).
//! Ключ — sha256(AST || контракт || свидетелль). Экономит повторные вызовы
//! внешнего решателя (Z3/Lean) — это и есть «экономика токенов/Fuel».
const std = @import("std");
const cov = @import("cov.zig");
const gate = @import("verifier/admission_gate.zig");
const compat = @import("compat");

pub const ProofCache = struct {
    map: std.AutoHashMap([32]u8, gate.CheckerVerdict),
    /// Ключи, которые СЕЙЧАС считаются (per-key single-flight).
    inflight: std.AutoHashMap([32]u8, void),
    hits: usize = 0,
    misses: usize = 0,
    evictions: usize = 0,
    /// Лимит записей. При переполнении вытесняется самая старая (FIFO).
    max_entries: usize = 10_000,
    /// ПОТОКОБЕЗОПАСНОСТЬ: без мьютекса параллельные get/put — гонка (race).
    mutex: std.Io.Mutex = std.Io.Mutex.init,
    /// Условная переменная для ожидания завершения чужого вычисления.
    cond: std.Io.Condition = std.Io.Condition.init,

    pub fn init(allocator: std.mem.Allocator) ProofCache {
        return .{
            .map = std.AutoHashMap([32]u8, gate.CheckerVerdict).init(allocator),
            .inflight = std.AutoHashMap([32]u8, void).init(allocator),
        };
    }

    /// Эффективность кэша: hits / (hits + misses) * 100%.
    pub fn efficiencyPct(self: ProofCache) f64 {
        const tot = self.hits + self.misses;
        if (tot == 0) return 0;
        return 100.0 * @as(f64, @floatFromInt(self.hits)) / @as(f64, @floatFromInt(tot));
    }

    pub fn deinit(self: *ProofCache) void {
        self.map.deinit();
        self.inflight.deinit();
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
        self.mutex.lockUncancelable(compat.io());
        defer self.mutex.unlock(compat.io());
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
        self.mutex.lockUncancelable(compat.io());
        defer self.mutex.unlock(compat.io());
        self.evictIfNeededLocked(k);
        try self.map.put(k, v);
    }

    /// ЭВИКЦИЯ (FIFO): не даём кэшу расти бесконечно (защита от OOM).
    /// Вызывать ТОЛЬКО под захваченным `mutex`.
    fn evictIfNeededLocked(self: *ProofCache, k: [32]u8) void {
        if (self.max_entries > 0 and self.map.count() >= self.max_entries and !self.map.contains(k)) {
            var it = self.map.keyIterator();
            if (it.next()) |key| {
                _ = self.map.remove(key.*);
                cov.hit(.cache_evict);
                self.evictions += 1;
            }
        }
    }

    // =====================================================================
    // SINGLE-FLIGHT ПО КЛЮЧУ (а не глобальный!)
    // =====================================================================
    //
    // ДЕФЕКТ (исправлен): раньше single-flight был ОДИН мьютекс на весь кэш.
    // Формально «пчелиный рой» (64 потока на ОДНУ формулу) он лечил, но
    // попутно СЕРИАЛИЗОВАЛ работу над РАЗНЫМИ формулами: при 8 ядрах
    // решатель вызывался только из одного потока за раз. Теперь in-flight
    // отслеживается ПО КЛЮЧУ, и независимые формулы считаются параллельно.

    pub const Begin = union(enum) {
        /// Значение уже в кэше.
        cached: gate.CheckerVerdict,
        /// Этот поток обязан посчитать (ключ помечен in-flight).
        compute,
        /// Ключ уже считается другим потоком — надо подождать.
        wait,
    };

    /// Начать работу с ключом: кэш / вычислить самому / подождать.
    pub fn begin(self: *ProofCache, k: [32]u8) Begin {
        self.mutex.lockUncancelable(compat.io());
        defer self.mutex.unlock(compat.io());
        if (self.map.get(k)) |v| {
            cov.hit(.cache_hit);
            self.hits += 1;
            return .{ .cached = v };
        }
        if (self.inflight.contains(k)) return .wait;
        self.inflight.put(k, {}) catch {}; // OOM: считаем сами (без резервации)
        cov.hit(.cache_miss);
        self.misses += 1;
        return .compute;
    }

    /// Завершить вычисление: записать результат и разбудить ожидающих.
    pub fn finish(self: *ProofCache, k: [32]u8, v: gate.CheckerVerdict) void {
        self.mutex.lockUncancelable(compat.io());
        defer self.mutex.unlock(compat.io());
        self.evictIfNeededLocked(k);
        self.map.put(k, v) catch {};
        _ = self.inflight.remove(k);
        self.cond.broadcast(compat.io());
    }

    /// Дождаться завершения чужого вычисления этого ключа.
    pub fn waitFor(self: *ProofCache, k: [32]u8) void {
        self.mutex.lockUncancelable(compat.io());
        defer self.mutex.unlock(compat.io());
        while (self.inflight.contains(k)) self.cond.wait(compat.io(), &self.mutex) catch {};
    }

    /// Число формул, считающихся ПРЯМО СЕЙЧАС (для тестов конкурентности).
    pub fn inFlight(self: *ProofCache) usize {
        self.mutex.lockUncancelable(compat.io());
        defer self.mutex.unlock(compat.io());
        return self.inflight.count();
    }
};

/// Обёртка: чекер, который сначала смотрит в кэш.
fn cachedFn(ctx: ?*anyopaque, allocator: std.mem.Allocator,
            ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    const Ctx = struct { cache: *ProofCache, inner: gate.TrustedChecker };
    const c: *Ctx = @ptrCast(@alignCast(ctx.?));
    const k = ProofCache.keyOf(ast, contract, proof);

    // SINGLE-FLIGHT ПО КЛЮЧУ: потоки с ОДНОЙ формулой ждут (1 miss, N-1 hits),
    // а с РАЗНЫМИ — считаются параллельно (раньше был глобальный мьютекс).
    switch (c.cache.begin(k)) {
        .cached => |v| return v,
        .compute => {
            const v = c.inner.run(allocator, ast, contract, proof);
            c.cache.finish(k, v);
            return v;
        },
        .wait => {
            c.cache.waitFor(k);
            if (c.cache.get(k)) |v| return v;
            // Редкий случай: вычисливший поток не сохранил результат (OOM) —
            // считаем сами, чтобы НЕ вернуть пустой вердикт.
            const v = c.inner.run(allocator, ast, contract, proof);
            c.cache.finish(k, v);
            return v;
        },
    }
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

    const ast = @as([32]u8, @splat(0x01));
    const con = @as([32]u8, @splat(0x02));
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
    const a = ProofCache.keyOf(@as([32]u8, @splat(1)), @as([32]u8, @splat(2)), "a");
    const b = ProofCache.keyOf(@as([32]u8, @splat(1)), @as([32]u8, @splat(2)), "b");
    try std.testing.expect(!std.mem.eql(u8, &a, &b));
}

test "КЭШ: ключ детерминирован (нет коллизий разных формул)" {
    const ast = @as([32]u8, @splat(0x01));
    const con = @as([32]u8, @splat(0x02));
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
    const ast = @as([32]u8, @splat(0x01));
    const con = @as([32]u8, @splat(0x02));
    _ = chk.run(std.testing.allocator, ast, con, "p"); // miss
    _ = chk.run(std.testing.allocator, ast, con, "p"); // hit
    _ = chk.run(std.testing.allocator, ast, con, "p"); // hit
    try std.testing.expectApproxEqAbs(@as(f64, 66.67), cache.efficiencyPct(), 0.1);
}

fn countFn(counter: *std.atomic.Value(usize), ctx: ?*anyopaque, allocator: std.mem.Allocator,
           ast: [32]u8, contract: [32]u8, proof: []const u8) gate.CheckerVerdict {
    _ = .{ ctx, allocator, ast, contract, proof };
    _ = counter.fetchAdd(1, .monotonic);
    compat.sleepMs(2); // имитация «тяжёлого» решателя
    return .Proved;
}

test "SINGLE-FLIGHT ПО КЛЮЧУ: РАЗНЫЕ формулы считаются ПАРАЛЛЕЛЬНО" {
    // ДЕФЕКТ (был): глобальный мьютекс сериализовал ВСЕ формулы — при 8 ядрах
    // решатель вызывался из одного потока за раз. Проверяем, что при РАЗНЫХ
    // ключах несколько потоков находятся in-flight ОДНОВРЕМЕННО.
    var cache = ProofCache.init(std.testing.allocator);
    defer cache.deinit();

    const N = 8;
    var active = std.atomic.Value(usize).init(0);
    var peak = std.atomic.Value(usize).init(0);

    const W = struct {
        fn run(c: *ProofCache, i: usize, act: *std.atomic.Value(usize), pk: *std.atomic.Value(usize)) void {
            var k: [32]u8 = @as([32]u8, @splat(0));
            k[0] = @intCast(i); // РАЗНЫЕ ключи
            switch (c.begin(k)) {
                .compute => {
                    const now = act.fetchAdd(1, .acq_rel) + 1;
                    while (true) {
                        const cur = pk.load(.acquire);
                        if (now <= cur) break;
                        if (pk.cmpxchgWeak(cur, now, .acq_rel, .acquire) == null) break;
                    }
                    compat.sleepMs(15); // имитация работы решателя
                    _ = act.fetchSub(1, .acq_rel);
                    c.finish(k, .Proved);
                },
                .cached => {},
                .wait => {},
            }
        }
    };

    var threads: [N]std.Thread = undefined;
    for (0..N) |i| threads[i] = try std.Thread.spawn(.{}, W.run, .{ &cache, i, &active, &peak });
    for (threads) |t| t.join();

    const p = peak.load(.acquire);
    std.debug.print("\n[SINGLE-FLIGHT] разных формул одновременно в работе: {d} (из {d})\n", .{ p, N });
    // При глобальном мьютексе пик был бы 1. Требуем хотя бы 2.
    try std.testing.expect(p >= 2);
    // Все ключи записаны, in-flight пуст.
    try std.testing.expectEqual(@as(usize, 0), cache.inFlight());
    try std.testing.expectEqual(@as(usize, N), cache.map.count());
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

    const ast = @as([32]u8, @splat(0x11));
    const con = @as([32]u8, @splat(0x22));
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
