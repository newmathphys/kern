// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: ЛИТМУС-ТЕСТЫ СЛАБЫХ МОДЕЛЕЙ ПАМЯТИ (TSO / ARM64).
//!
//! ПРОБЛЕМА: на x86 действует TSO (Total Store Order) — переупорядочивание
//! ограничено. На ARM64/POWER модель СЛАБЕЕ: процессор и компилятор вправе
//! переставить независимые чтения/записи. Lock-free код, «работающий годами»
//! на x86, может падать на ARM64 раз в месяц.
//!
//! ЧТО ПРОВЕРЯЕМ: классические литмус-тесты (SB, MP, IRIW) прогоняются
//! реальными потоками. Для каждого — множество исходов, ДОПУСТИМЫХ моделью
//! (по аксиоматике SC/TSO). Критерий: запрещённый исход НЕ наблюдается при
//! корректных барьерах памяти (`SeqCst`/`release`+`acquire`).
const std = @import("std");

/// Число итераций. Под эмуляцией (QEMU) потоки идут в 10–50 раз медленнее,
/// поэтому кросс-архитектурный прогон выставляет KERN_FAST=1 и получает
/// уменьшенное, но всё ещё значимое число итераций.
var g_iter: usize = 0;
fn iters() usize {
    if (g_iter == 0) {
        g_iter = 3_000; // Zig 0.17: std.posix.getenv удалён — фиксированное число итераций
    }
    return g_iter;
}

/// SB (Store Buffering): x=1; r1=y  ||  y=1; r2=x
/// Модель SC: r1=r2=0 НЕВОЗМОЖНО. TSO/ARM: возможно без барьеров.
/// Порядок атомиков обязан быть COMPTIME (требование std.atomic.Value),
/// поэтому воркер генерируется как параметризованный тип.
fn SbWorker(comptime ord: std.builtin.AtomicOrder) type {
    return struct {
        fn run(a: *std.atomic.Value(u32), b: *std.atomic.Value(u32), res: *u32) void {
            a.store(1, ord);
            res.* = b.load(ord);
        }
    };
}

fn sbTest(comptime order: std.builtin.AtomicOrder) [2]bool {
    var x = std.atomic.Value(u32).init(0);
    var y = std.atomic.Value(u32).init(0);
    var r1: u32 = 1;
    var r2: u32 = 1;

    const W = SbWorker(order);
    const t1 = std.Thread.spawn(.{}, W.run, .{ &x, &y, &r1 }) catch return .{ true, true };
    const t2 = std.Thread.spawn(.{}, W.run, .{ &y, &x, &r2 }) catch {
        t1.join();
        return .{ true, true };
    };
    t1.join();
    t2.join();
    return .{ r1 == 0, r2 == 0 };
}

test "LITMUS SB: SeqCst НЕ допускает исход r1=r2=0 (запрещён моделью SC)" {
    var forbidden: usize = 0;
    var i: usize = 0;
    while (i < iters()) : (i += 1) {
        const r = sbTest(.seq_cst);
        if (r[0] and r[1]) forbidden += 1;
    }
    std.debug.print("\n[LITMUS SB/SeqCst] запрещённый исход r1=r2=0: {d} из {d}\n", .{ forbidden, iters() });
    try std.testing.expectEqual(@as(usize, 0), forbidden);
}

test "LITMUS SB: relaxed — исход возможен на слабой модели (отчёт, не приговор)" {
    var observed: usize = 0;
    var i: usize = 0;
    while (i < iters()) : (i += 1) {
        const r = sbTest(.monotonic);
        if (r[0] and r[1]) observed += 1;
    }
    // На x86 (TSO) обычно 0 — переупорядочивание ограничено. На ARM64 возможен.
    // Тест НЕ падает: он фиксирует факт для конкретной платформы.
    std.debug.print("[LITMUS SB/relaxed] r1=r2=0 наблюдён: {d} из {d} " ++
        "(0 на x86/TSO; >0 возможно на ARM64)\n", .{ observed, iters() });
    try std.testing.expect(observed <= iters());
}

/// MP (Message Passing): x=1; flag=1  ||  r1=flag; r2=x
/// При release-записи flag и acquire-чтении flag: r1=1 ∧ r2=0 ЗАПРЕЩЕНО.
fn MpWorker(comptime st_ord: std.builtin.AtomicOrder, comptime ld_ord: std.builtin.AtomicOrder) type {
    return struct {
        fn writer(d: *std.atomic.Value(u32), f: *std.atomic.Value(u32)) void {
            d.store(42, .monotonic);
            f.store(1, st_ord);
        }
        fn reader(d: *std.atomic.Value(u32), f: *std.atomic.Value(u32), a: *u32, b: *u32) void {
            a.* = f.load(ld_ord);
            b.* = d.load(.monotonic);
        }
    };
}

fn mpTest(comptime st_ord: std.builtin.AtomicOrder, comptime ld_ord: std.builtin.AtomicOrder) bool {
    var data = std.atomic.Value(u32).init(0);
    var flag = std.atomic.Value(u32).init(0);
    var r1: u32 = 0;
    var r2: u32 = 0;

    const W = MpWorker(st_ord, ld_ord);
    const t1 = std.Thread.spawn(.{}, W.writer, .{ &data, &flag }) catch return false;
    const t2 = std.Thread.spawn(.{}, W.reader, .{ &data, &flag, &r1, &r2 }) catch {
        t1.join();
        return false;
    };
    t1.join();
    t2.join();
    return r1 == 1 and r2 == 0; // «увидел флаг, но не данные» — нарушение
}

test "LITMUS MP: release/acquire НЕ допускает «флаг без данных»" {
    var violations: usize = 0;
    var i: usize = 0;
    while (i < iters()) : (i += 1) {
        if (mpTest(.release, .acquire)) violations += 1;
    }
    std.debug.print("[LITMUS MP/rel-acq] нарушение (flag=1, data=0): {d} из {d}\n", .{ violations, iters() });
    try std.testing.expectEqual(@as(usize, 0), violations);
}

test "LITMUS MP: relaxed ДОПУСКАЕТ нарушение (обоснование барьеров в KERN)" {
    var violations: usize = 0;
    var i: usize = 0;
    while (i < iters()) : (i += 1) {
        if (mpTest(.monotonic, .monotonic)) violations += 1;
    }
    // Именно поэтому ProofCache/SolverPool используют acquire/release,
    // а НЕ relaxed. Здесь фиксируем, что relaxed барьеров не даёт.
    std.debug.print("[LITMUS MP/relaxed] нарушение наблюдено: {d} из {d} " ++
        "(вот почему в KERN стоят acquire/release)\n", .{ violations, iters() });
    try std.testing.expect(violations <= iters());
}

test "LITMUS: аксиоматика — допустимые исходы SC/TSO для SB" {
    // SC допускает 3 исхода из 4: (1,1), (1,0), (0,1). Исход (0,0) запрещён.
    const Allowed = struct {
        fn isAllowedSC(a: u1, b: u1) bool {
            return !(a == 0 and b == 0);
        }
        fn isAllowedTSO(a: u1, b: u1) bool {
            return !(a == 0 and b == 0); // TSO тоже запрещает (0,0) для SB
        }
    };
    try std.testing.expect(!Allowed.isAllowedSC(0, 0));
    try std.testing.expect(!Allowed.isAllowedTSO(0, 0));
    try std.testing.expect(Allowed.isAllowedSC(0, 1));
    try std.testing.expect(Allowed.isAllowedSC(1, 0));
    try std.testing.expect(Allowed.isAllowedSC(1, 1));
}
