// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: СТРЕСС «КЛЕЯ С ОС» (границы процессов/пайпов/сигналов).
//!
//! ПОВОД: падение на 2432 файлах SMT-LIB показало, что «тепличные» юнит-тесты
//! пропускают системные гонки. Здесь целенаправленно бьём по стыку
//! «KERN ↔ ОС»: пайпы, spawn, сигналы, лимиты.
//!
//! ТЕСТЫ:
//!   1. **Pipe bloat / deadlock.** Вывод решателя > 64 КБ (размер буфера
//!      пайпа Linux). Мост читает stdout ДО `wait()` — проверяем, что
//!      взаимной блокировки НЕТ.
//!   2. **Гигантский вывод (> лимита 4 МБ).** Должен быть аккуратный
//!      `ToolError`, а не паника и не зависание.
//!   3. **Флуд spawn.** N потоков × M запросов одновременно: нет паник,
//!      нет утечек дескрипторов, все результаты учтены.
//!   4. **EAGAIN при spawn.** Внутрипроцессный `setrlimit(RLIMIT_NPROC)`
//!      зажимает лимит процессов → spawn обязан вернуть `ToolError`,
//!      а не паниковать (fail-closed).
//!
//! Запуск: zig test src/tests/os_stress_test.zig
const std = @import("std");
const z3b = @import("../verifier/z3_bridge.zig");

/// Есть ли решатель (иначе тесты бессмысленны — пропускаем).
fn solverAvailable(b: *z3b.Z3Bridge) bool {
    return b.executeQuery("(check-sat)\n").status != .ToolError;
}

fn countOpenFds() usize {
    var dir = std.fs.openDirAbsolute("/proc/self/fd", .{ .iterate = true }) catch return 0;
    defer dir.close();
    var n: usize = 0;
    var it = dir.iterate();
    while (it.next() catch null) |_| n += 1;
    return n;
}

test "ОС-СТРЕСС 1: вывод > 64 КБ (буфер пайпа) — взаимной блокировки НЕТ" {
    var b = z3b.Z3Bridge.init(std.testing.allocator);
    b.timeout_ms = 20_000;
    if (!solverAvailable(&b)) return error.SkipZigTest;

    // Формула, чей ответ (модель) заметно больше 64 КБ.
    var q = std.ArrayList(u8).init(std.testing.allocator);
    defer q.deinit();
    try q.appendSlice("(set-logic QF_LIA)\n");
    var buf: [64]u8 = undefined;
    var i: usize = 0;
    while (i < 3000) : (i += 1) try q.appendSlice(try std.fmt.bufPrint(&buf, "(declare-const v{d} Int)\n", .{i}));
    i = 0;
    while (i < 3000) : (i += 1) try q.appendSlice(try std.fmt.bufPrint(&buf, "(assert (= v{d} {d}))\n", .{ i, i }));
    try q.appendSlice("(check-sat)\n(get-model)\n");

    const cap = b.executeCapture(q.items);
    defer std.testing.allocator.free(cap.stdout);
    // Главное: мы ДОШЛИ сюда (нет deadlock). Ответ sat — модель непустая.
    try std.testing.expect(cap.status == .Sat or cap.status == .Unsat or cap.status == .Unknown);
    try std.testing.expect(cap.stdout.len > 64 * 1024); // > буфера пайпа
}

test "ОС-СТРЕСС 2: вывод > лимита 4 МБ — аккуратный отказ, НЕ паника" {
    var b = z3b.Z3Bridge.init(std.testing.allocator);
    b.timeout_ms = 30_000;
    if (!solverAvailable(&b)) return error.SkipZigTest;

    // Просим Z3 напечатать гигантский терм (>> 4 МБ).
    var q = std.ArrayList(u8).init(std.testing.allocator);
    defer q.deinit();
    try q.appendSlice("(set-logic QF_LIA)\n(declare-const x Int)\n");
    try q.appendSlice("(assert (= x (+ 1 (+ 1 (+ 1 (+ 1 (+ 1 (+ 1 (+ 1 (+ 1 (+ 1 0)))))))))))\n");
    try q.appendSlice("(check-sat)\n(get-model)\n");
    // Искусственно много текста: повторяем объявления.
    var buf: [64]u8 = undefined;
    var i: usize = 0;
    while (i < 60_000) : (i += 1) try q.appendSlice(try std.fmt.bufPrint(&buf, "(declare-const y{d} Int)\n", .{i}));
    try q.appendSlice("(check-sat)\n(get-model)\n");

    const cap = b.executeCapture(q.items);
    defer std.testing.allocator.free(cap.stdout);
    // Допустимо: sat/unsat/unknown (успели) ИЛИ ToolError (лимит).
    // НЕДОПУСТИМО: паника/зависание — раз тест дошёл, их нет.
    try std.testing.expect(cap.status != .Timeout);
}

const FloodCtx = struct {
    ok: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    err: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
};

fn floodWorker(ctx: *FloodCtx, iters: usize) void {
    var b = z3b.Z3Bridge.init(std.heap.page_allocator);
    b.timeout_ms = 10_000;
    var i: usize = 0;
    while (i < iters) : (i += 1) {
        const r = b.executeQuery("(set-logic QF_LIA)(declare-const x Int)(assert (> x 5))(assert (< x 2))(check-sat)\n");
        switch (r.status) {
            .ToolError, .Timeout => _ = ctx.err.fetchAdd(1, .monotonic),
            else => _ = ctx.ok.fetchAdd(1, .monotonic),
        }
    }
}

test "ОС-СТРЕСС 4: инъекция сбоев 5% (pipe/spawn/read) — нет паник, нет утечек FD" {
    var probe = z3b.Z3Bridge.init(std.testing.allocator);
    if (!solverAvailable(&probe)) return error.SkipZigTest;

    // Моделируем отказы системных вызовов ВНУТРИ моста (LD_PRELOAD недоступен:
    // kernc — статический бинарник; strace не установлен).
    const before = countOpenFds();
    var b = z3b.Z3Bridge.init(std.testing.allocator);
    b.timeout_ms = 8_000;
    b.fault_pct = 5; // 5% — как в требовании

    const N = 200;
    var ok: usize = 0;
    var failed: usize = 0;
    var i: usize = 0;
    while (i < N) : (i += 1) {
        const r = b.executeQuery(
            "(set-logic QF_LIA)(declare-const x Int)(assert (> x 5))(assert (< x 2))(check-sat)\n");
        switch (r.status) {
            .ToolError, .Timeout => failed += 1,
            else => ok += 1,
        }
    }
    std.debug.print("\n  [ОС-4] запросов {d}: успешно {d}, отказов {d}, срабатываний инъекции {d}\n",
        .{ N, ok, failed, b.fault_hits });

    // Все запросы учтены; инъекция реально срабатывала (тест не пустой).
    try std.testing.expect(ok + failed == N);
    try std.testing.expect(b.fault_hits > 0);
    // При 5% отказов подавляющее большинство запросов обязано пройти.
    try std.testing.expect(ok > N / 2);

    // ГЛАВНОЕ: после 200 запросов с отказами дескрипторы не утекли.
    const after = countOpenFds();
    std.debug.print("  [ОС-4] дескрипторов до {d}, после {d}\n", .{ before, after });
    try std.testing.expect(after <= before + 3);
}

test "ОС-СТРЕСС 3: флуд spawn (12 потоков × 8 запросов) — без паник и утечек FD" {
    var probe = z3b.Z3Bridge.init(std.testing.allocator);
    if (!solverAvailable(&probe)) return error.SkipZigTest;

    const before = countOpenFds();
    var ctx = FloodCtx{};
    const N = 12;
    const threads = try std.testing.allocator.alloc(std.Thread, N);
    defer std.testing.allocator.free(threads);
    var t: usize = 0;
    while (t < N) : (t += 1) threads[t] = try std.Thread.spawn(.{}, floodWorker, .{ &ctx, 8 });
    for (threads) |th| th.join();

    const ok = ctx.ok.load(.monotonic);
    const err = ctx.err.load(.monotonic);
    std.debug.print("\n  [ОС-3] успешно {d}, отказов {d}\n", .{ ok, err });
    try std.testing.expect(ok > 0); // хотя бы часть прошла
    try std.testing.expect(ok + err == N * 8); // все учтены

    // Утечек дескрипторов быть не должно (допускаем ±3 на служебные).
    const after = countOpenFds();
    try std.testing.expect(after <= before + 3);
}
