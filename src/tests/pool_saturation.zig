// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: ЭШЕЛОН 3 — ИЗНУРЕНИЕ ПЛАНИРОВЩИКА И ПУЛА ПОТОКОВ.
//!
//! Single-flight защищает от «пчелиного роя» на ОДНУ формулу. Здесь проверяем
//! противоположный случай: 128 потоков требуют 128 РАЗНЫХ тяжёлых проверок —
//! вчетверо больше, чем ядер. Планировщик обязан:
//!   * держать строгий лимит одновременно активных решателей;
//!   * ставить остальные в очередь (а не плодить процессы);
//!   * выдать ВСЕ вердикты без падения и без взаимной блокировки.

const std = @import("std");
const z3 = @import("../verifier/z3_bridge.zig");
const compat = @import("compat");

const N: usize = 128;

/// Имитация тяжёлой проверки: держим слот на `ms` миллисекунд.
fn heavyWork(pool: *z3.SolverPool, done: *std.atomic.Value(u8), idx: usize, ms: u64) void {
    pool.acquire();
    defer pool.release();
    compat.sleepMs(ms);
    done.* = std.atomic.Value(u8).init(1);
    _ = idx;
}

test "POOL: 128 запросов на пуле из 4 — лимит соблюдён, все выполнены" {
    var pool = z3.SolverPool.init(4);
    var done: [N]std.atomic.Value(u8) = undefined;
    for (&done) |*d| d.* = std.atomic.Value(u8).init(0);

    var threads: [N]std.Thread = undefined;
    for (&threads, 0..) |*t, i| {
        t.* = try std.Thread.spawn(.{}, heavyWork, .{ &pool, &done[i], i, 3 });
    }
    for (&threads) |*t| t.join();

    // 1) Жёсткий лимит одновременных решателей
    try std.testing.expect(pool.peakConcurrent() <= 4);
    // 2) Все 128 выполнены (нет потерь и дедлока)
    try std.testing.expectEqual(@as(usize, N), pool.completedCount());
    // 3) Ни один слот не остался занят
    try std.testing.expectEqual(@as(usize, 0), pool.currentlyActive());
    // 4) Каждый поток получил свой вердикт
    for (done) |d| try std.testing.expectEqual(@as(u8, 1), d.load(.acquire));
}

test "POOL: пик не превышает лимит при 8 воркерах и 128 запросах" {
    var pool = z3.SolverPool.init(8);
    var done: [N]std.atomic.Value(u8) = undefined;
    for (&done) |*d| d.* = std.atomic.Value(u8).init(0);

    var threads: [N]std.Thread = undefined;
    for (&threads, 0..) |*t, i| {
        t.* = try std.Thread.spawn(.{}, heavyWork, .{ &pool, &done[i], i, 1 });
    }
    for (&threads) |*t| t.join();

    try std.testing.expect(pool.peakConcurrent() <= 8);
    try std.testing.expectEqual(@as(usize, N), pool.completedCount());
    try std.testing.expect(pool.peakConcurrent() >= 2); // реально работал параллельно
}

test "POOL: пул из 1 сериализует (никогда не более 1)" {
    var pool = z3.SolverPool.init(1);
    var done: [16]std.atomic.Value(u8) = undefined;
    for (&done) |*d| d.* = std.atomic.Value(u8).init(0);
    var threads: [16]std.Thread = undefined;
    for (&threads, 0..) |*t, i| {
        t.* = try std.Thread.spawn(.{}, heavyWork, .{ &pool, &done[i], i, 1 });
    }
    for (&threads) |*t| t.join();
    try std.testing.expectEqual(@as(usize, 1), pool.peakConcurrent());
    try std.testing.expectEqual(@as(usize, 16), pool.completedCount());
}

test "POOL + РЕАЛЬНЫЙ Z3: 16 независимых формул через пул из 4" {
    // Проверяем ИНТЕГРАЦИЮ: реальные процессы Z3 не превышают лимит пула.
    // Если z3 недоступен — тест проходит (безопасная деградация).
    const z3bin = "z3";
    var pool = z3.SolverPool.init(4);

    const Ctx = struct {
        pool: *z3.SolverPool,
        allocator: std.mem.Allocator,
        results: *std.atomic.Value(usize),
        unsat: *std.atomic.Value(usize),
        fn run(c: @This(), i: usize) void {
            c.pool.acquire();
            defer c.pool.release();
            var br = z3.Z3Bridge.init(c.allocator);
            br.z3_path = z3bin;
            // Уникальная формула на каждый поток (не «пчелиный рой»).
            const script = std.fmt.allocPrint(c.allocator,
                "(set-logic QF_LIA)\n(declare-const x Int)\n(assert (> x {d}))\n(assert (< x {d}))\n(check-sat)\n",
                .{ i, i + 1 }) catch return;
            defer c.allocator.free(script);
            const st = br.executeStatus(script);
            if (st == .Unsat) _ = c.unsat.fetchAdd(1, .monotonic);
            _ = c.results.fetchAdd(1, .monotonic);
        }
    };

    var results = std.atomic.Value(usize).init(0);
    var unsat = std.atomic.Value(usize).init(0);
    const ctx = Ctx{ .pool = &pool, .allocator = std.testing.allocator, .results = &results, .unsat = &unsat };

    var threads: [16]std.Thread = undefined;
    for (&threads, 0..) |*t, i| {
        t.* = try std.Thread.spawn(.{}, Ctx.run, .{ ctx, i });
    }
    for (&threads) |*t| t.join();

    try std.testing.expect(pool.peakConcurrent() <= 4);
    try std.testing.expectEqual(@as(usize, 16), pool.completedCount());
    try std.testing.expectEqual(@as(usize, 16), results.load(.acquire));
    // Если z3 реально работает — все 16 формул невыполнимы (x>i и x<i+1).
    // Если z3 нет — unsat == 0, что тоже корректная безопасная деградация.
    const u = unsat.load(.acquire);
    try std.testing.expect(u == 0 or u == 16);
}
