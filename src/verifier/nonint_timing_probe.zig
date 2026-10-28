// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.

//! ФИЗИЧЕСКИЙ ОРАКУЛ ДЛЯ НЕВМЕШАТЕЛЬСТВА (шаг D плана).
//!
//! ЗАЧЕМ. Модель невмешательства (`noninterference.analyze`) утверждает:
//! `constantTimeEqual` НЕ зависит от данных (нет ветвления по секрету),
//! а `earlyExitEqual` — ЗАВИСИТ (ранний выход по секрету). До этого шага
//! это утверждение никто не сверял с ФИЗИЧЕСКИМ временем.
//!
//! ЧТО ИЗМЕРЯЕТСЯ. Реальные функции из `src/verifier/noninterference.zig`
//! вызываются на двух входах, отличающихся от секрета в РАЗНЫХ ПОЗИЦИЯХ
//! (позиция 1 = ранняя, позиция 16 = поздняя). Меряется МИНИМУМ из N прогонов:
//! минимум устойчив к шуму планировщика, тогда как сумма/среднее — нет.
//!   * constant-time: отношение времён ≈ 1 (позиция отличия не влияет);
//!   * ранний выход  : отношение ≫ 1 (ранняя позиция = короткий путь).
//!
//! ЧЕСТНАЯ ГРАНИЦА: это СТАТИСТИЧЕСКИЙ оракул. Он измеряет РЕАЛЬНОЕ время и
//! подвержен шуму планировщика ОС, поэтому используется только min-of-N с
//! порогом с запасом и НИКОГДА не объявляется доказательством.
const std = @import("std");
const nonint = @import("noninterference.zig");
const compat = @import("compat");

/// ДЛИНА СЕКРЕТА ВЫБРАНА ИЗМЕРЕНИЕМ. На 16 байтах сигнал тонет в накладных
/// расходах таймера (~100 нс): измерено CT_RATIO=1.00, EE_RATIO=1.20 —
/// разница есть, но она того же порядка, что шум. На 4096 байтах разница
/// между позицией отличия 1 и 4096 — это 4095 итераций, то есть на три
/// порядка больше накладных расходов.
const LEN: usize = 4096;

fn makeSecret(comptime flip: ?usize) [LEN]u8 {
    @setEvalBranchQuota(20_000); // 4096 итераций > лимита 1000 по умолчанию
    var a: [LEN]u8 = undefined;
    for (&a, 0..) |*c, i| c.* = @intCast('a' + (i % 26));
    if (flip) |k| a[k] = 'X';
    return a;
}

const SECRET = makeSecret(null);
/// Отличие в ПОЗИЦИИ 1 (короткий путь для раннего выхода).
const EARLY = makeSecret(0);
/// Отличие в ПОСЛЕДНЕЙ позиции (длинный путь для раннего выхода).
const LATE = makeSecret(LEN - 1);

fn ctEarly() void {
    std.mem.doNotOptimizeAway(nonint.constantTimeEqual(&SECRET, &EARLY));
}
fn ctLate() void {
    std.mem.doNotOptimizeAway(nonint.constantTimeEqual(&SECRET, &LATE));
}
fn eeEarly() void {
    std.mem.doNotOptimizeAway(nonint.earlyExitEqual(&SECRET, &EARLY));
}
fn eeLate() void {
    std.mem.doNotOptimizeAway(nonint.earlyExitEqual(&SECRET, &LATE));
}

/// Минимальное время выполнения `f` за `n` прогонов (устойчиво к шуму).
/// `std.time.Timer` удалён в Zig 0.17 -> используется `compat.Timer` (монотонные
/// часы `std.Io.Clock.now(.awake)`), как в тестах самого модуля.
fn minNanos(comptime f: fn () void, n: usize) u64 {
    var best: u64 = std.math.maxInt(u64);
    var i: usize = 0;
    while (i < n) : (i += 1) {
        var t = compat.Timer.start();
        f();
        const d = t.read();
        if (d < best) best = d;
    }
    return best;
}

fn ratio(a: u64, b: u64) f64 {
    const hi: f64 = @floatFromInt(@max(a, b));
    const lo: f64 = @floatFromInt(@max(@min(a, b), 1));
    return hi / lo;
}

pub fn main() !void {
    // ВАЖНО: сборка в Debug (`build.zig`, шаг `nonint-probe`). В ReleaseFast
    // компилятор СВОРАЧИВАЕТ обе функции на comptime-константах, и разница
    // времён исчезает — измерение стало бы бессмысленным (EE_RATIO ≈ 1).
    const n: usize = 1_000;
    const ct_e = minNanos(ctEarly, n);
    const ct_l = minNanos(ctLate, n);
    const ee_e = minNanos(eeEarly, n);
    const ee_l = minNanos(eeLate, n);
    // Печатается ВСЕГДА: оракул должен видеть ЧИСЛА, а не только «ок/не ок».
    std.debug.print("CT_RATIO={d:.4}\n", .{ratio(ct_e, ct_l)});
    std.debug.print("EE_RATIO={d:.4}\n", .{ratio(ee_e, ee_l)});
    std.debug.print("CT_NS={d} EE_NS={d}\n", .{ ct_e, ee_e });
}
