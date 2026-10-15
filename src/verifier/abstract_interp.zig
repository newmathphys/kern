// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: АБСТРАКТНАЯ ИНТЕРПРЕТАЦИЯ (интервалы + widening/narrowing).
//!
//! Идея Патрика Кузо (создана для ракеты Ariane 5): инварианты можно
//! ВЫЧИСЛЯТЬ, а не угадывать. Переменные представляются геометрическим телом
//! (здесь — интервалом [lo, hi]); на каждой итерации тело расширяется
//! (WIDENING), пока не достигнет неподвижной точки, затем уточняется
//! (NARROWING).
//!
//! ЗАЧЕМ, если есть Z3: SMT «сдаётся по таймауту» на циклах с большим числом
//! развёрток. Абстрактная интерпретация даёт инвариант за О(1) итераций —
//! ценой потери точности (over-approximation). Это ДОПОЛНЯЮЩИЙ метод.
const std = @import("std");

pub const INF: i64 = std.math.maxInt(i64);

pub const Interval = struct {
    lo: i64,
    hi: i64, // INF означает +∞

    pub const top = Interval{ .lo = std.math.minInt(i64), .hi = INF };

    pub fn single(v: i64) Interval {
        return .{ .lo = v, .hi = v };
    }

    pub fn isEmpty(self: Interval) bool {
        return self.lo > self.hi;
    }

    pub fn eql(a: Interval, b: Interval) bool {
        return a.lo == b.lo and a.hi == b.hi;
    }

    /// Объединение (join): наименьшее тело, содержащее оба.
    pub fn join(a: Interval, b: Interval) Interval {
        return .{ .lo = @min(a.lo, b.lo), .hi = @max(a.hi, b.hi) };
    }

    /// Пересечение (meet).
    pub fn meet(a: Interval, b: Interval) Interval {
        return .{ .lo = @max(a.lo, b.lo), .hi = @min(a.hi, b.hi) };
    }

    /// WIDENING: если граница растёт — прыгаем в ±∞.
    /// Гарантирует завершение анализа за конечное число шагов.
    pub fn widen(a: Interval, b: Interval) Interval {
        return .{
            .lo = if (b.lo < a.lo) std.math.minInt(i64) else a.lo,
            .hi = if (b.hi > a.hi) INF else a.hi,
        };
    }

    /// NARROWING: уточняем после widening.
    pub fn narrow(a: Interval, b: Interval) Interval {
        return .{
            .lo = if (a.lo == std.math.minInt(i64)) b.lo else a.lo,
            .hi = if (a.hi == INF) b.hi else a.hi,
        };
    }

    /// Абстрактное сложение с константой (насыщающее).
    pub fn addConst(a: Interval, k: i64) Interval {
        return .{ .lo = a.lo +| k, .hi = if (a.hi == INF) INF else a.hi +| k };
    }

    /// Ограничение по предикату `x < bound` (вход в тело цикла).
    pub fn restrictLt(a: Interval, bound: i64) Interval {
        return a.meet(.{ .lo = std.math.minInt(i64), .hi = bound - 1 });
    }

    /// Ограничение по предикату `x >= bound` (выход из цикла).
    pub fn restrictGe(a: Interval, bound: i64) Interval {
        return a.meet(.{ .lo = bound, .hi = INF });
    }
};

pub const LoopResult = struct {
    invariant: Interval,
    exit_state: Interval,
    iterations: usize,
    widened: bool,
};

/// Анализ цикла `x := init; while (x < bound) x := x + step;`
/// БЕЗ SMT и БЕЗ разворачивания — через неподвижную точку.
pub fn analyzeLinearLoop(init: i64, step: i64, bound: i64) LoopResult {
    var inv = Interval.single(init);
    var iters: usize = 0;
    var widened = false;

    // 1. WIDENING до неподвижной точки (завершение гарантировано).
    while (iters < 64) : (iters += 1) {
        const guarded = inv.restrictLt(bound);
        if (guarded.isEmpty()) break;
        const body = guarded.addConst(step);
        const w = inv.widen(inv.join(body));
        if (Interval.eql(w, inv)) break;
        inv = w;
        widened = true;
    }

    // 2. NARROWING: уточняем инвариант.
    // Инвариант на ВХОДЕ цикла обязан лежать в (guard ∪ {init}): либо это
    // начальное значение, либо мы вошли в тело (значит guard был истинен).
    var k: usize = 0;
    while (k < 16) : (k += 1) {
        const guarded = inv.restrictLt(bound);
        const body = guarded.addConst(step);
        const head_ok = Interval.single(init).join(inv.restrictLt(bound));
        const refined = inv.narrow(inv.join(body)).meet(head_ok);
        if (Interval.eql(refined, inv)) break;
        inv = refined;
    }

    // Выход из цикла: последнее тело при истинном guard, затем x >= bound.
    const exit_state = inv.restrictLt(bound).addConst(step).restrictGe(bound);

    return .{
        .invariant = inv,
        .exit_state = exit_state,
        .iterations = iters,
        .widened = widened,
    };
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "ABSINT: widening гарантирует завершение (растущий счётчик -> +inf)" {
    var inv = Interval.single(0);
    var it: usize = 0;
    while (it < 64) : (it += 1) {
        const body = inv.restrictLt(10).addConst(1);
        const w = inv.widen(inv.join(body));
        if (Interval.eql(w, inv)) break;
        inv = w;
    }
    try std.testing.expect(it < 64); // сошлось быстро
    try std.testing.expectEqual(INF, inv.hi); // widening расширил до +∞
}

test "ABSINT: цикл x:=0; while(x<10) x+=1 — инвариант [0,9], выход x>=10" {
    const r = analyzeLinearLoop(0, 1, 10);
    // ДЕФЕКТ #39 (найден can-fail): проверка `lo >= 10` проходила и для
    // ПУСТОГО интервала (lo=10, hi=9): meet([0,9],[10,∞]) даёт lo>hi.
    // Значит утверждение НЕ проверяло, что состояние выхода вообще достижимо.
    // Добавлена явная проверка непустоты.
    try std.testing.expect(!r.invariant.isEmpty());
    try std.testing.expect(!r.exit_state.isEmpty());
    try std.testing.expect(r.invariant.lo >= 0);
    try std.testing.expect(r.invariant.hi <= 9);
    try std.testing.expect(r.exit_state.lo >= 10);
    // Доказательство свойства БЕЗ SMT: x никогда не станет отрицательным.
    try std.testing.expect(r.invariant.lo >= 0);
}

test "ABSINT: шаг 2 — инвариант [0,9], выход x>=10" {
    const r = analyzeLinearLoop(0, 2, 10);
    try std.testing.expect(r.invariant.lo >= 0);
    try std.testing.expect(r.invariant.hi <= 9);
    try std.testing.expect(r.exit_state.lo >= 10);
}

test "ABSINT: интервалы — join/meet/widen/narrow корректны" {
    const a = Interval{ .lo = 0, .hi = 5 };
    const b = Interval{ .lo = 3, .hi = 9 };
    try std.testing.expect(Interval.eql(a.join(b), .{ .lo = 0, .hi = 9 }));
    try std.testing.expect(Interval.eql(a.meet(b), .{ .lo = 3, .hi = 5 }));
    try std.testing.expectEqual(INF, a.widen(b).hi);
    try std.testing.expectEqual(@as(i64, 9), Interval.top.narrow(b).hi);
}

test "ABSINT: уход к переполнению — widening видит +∞ (потенциальный overflow)" {
    const r = analyzeLinearLoop(0, 1, std.math.maxInt(i64) - 2);
    try std.testing.expect(r.widened);
    try std.testing.expect(r.exit_state.lo > std.math.maxInt(i64) - 3);
}
