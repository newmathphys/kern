// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: ВЕРОЯТНОСТНАЯ МОДЕЛЬ-ЧЕКИНГ (DTMC / PCTL).
//!
//! Детерминированный верификатор отвечает «путь проходим или нет». Но в
//! криптографии (генерация ключей, разделение секрета), сетевых протоколах
//! (экспоненциальная задержка Ethernet) и консенсусах (Raft/Paxos) поведение
//! ЗАВИСИТ ОТ СЛУЧАЙНОСТИ. Там вопрос звучит иначе:
//!   «Какова вероятность P≤10⁻⁹, что система войдёт в deadlock за 100 шагов?»
//!
//! Математический аппарат — марковские цепи (DTMC) и вероятностная
//! темпоральная логика PCTL. KERN решает уравнения достижимости
//! итерацией по значению (value iteration) до неподвижной точки.
//!
//! Где ловим баги: смещение энтропии PRNG, редкие сценарии «сговора»,
//! которые гарантированно наступают при длительной работе.
const std = @import("std");

pub const Dtmc = struct {
    allocator: std.mem.Allocator,
    n: usize,
    /// Матрица переходов: trans[i][j] — вероятность из i в j (строка = 1).
    trans: [][]f64,

    pub fn init(allocator: std.mem.Allocator, n: usize) !Dtmc {
        const trans = try allocator.alloc([]f64, n);
        for (trans) |*row| {
            row.* = try allocator.alloc(f64, n);
            @memset(row.*, 0);
        }
        return .{ .allocator = allocator, .n = n, .trans = trans };
    }

    pub fn deinit(self: *Dtmc) void {
        for (self.trans) |row| self.allocator.free(row);
        self.allocator.free(self.trans);
    }

    pub fn set(self: *Dtmc, i: usize, j: usize, p: f64) void {
        self.trans[i][j] = p;
    }

    /// Проверка стохастичности: каждая строка суммируется в 1.
    pub fn isStochastic(self: *const Dtmc) bool {
        for (self.trans) |row| {
            var s: f64 = 0;
            for (row) |p| s += p;
            if (@abs(s - 1.0) > 1e-9) return false;
        }
        return true;
    }

    /// Вероятности ДОСТИЖИМОСТИ целевых состояний: P(F target).
    /// Итерация по значению до неподвижной точки.
    /// Целевые состояния — поглощающие (вероятность 1).
    pub fn reachProbability(self: *const Dtmc, target: []const bool, iters: usize) ![]f64 {
        const x = try self.allocator.alloc(f64, self.n);
        errdefer self.allocator.free(x);
        for (x, 0..) |*v, i| v.* = if (target[i]) 1.0 else 0.0;

        var it: usize = 0;
        while (it < iters) : (it += 1) {
            var delta: f64 = 0;
            var i: usize = 0;
            while (i < self.n) : (i += 1) {
                if (target[i]) continue; // поглощающее
                var acc: f64 = 0;
                for (self.trans[i], 0..) |p, j| acc += p * x[j];
                delta = @max(delta, @abs(acc - x[i]));
                x[i] = acc;
            }
            if (delta < 1e-12) break;
        }
        return x;
    }
};

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "DTMC: смещённая монета — P(провал) = 0.01" {
    var m = try Dtmc.init(std.testing.allocator, 3);
    defer m.deinit();
    // 0 = старт, 1 = ПРОВАЛ (поглощающий), 2 = успех (поглощающий)
    m.set(0, 1, 0.01);
    m.set(0, 2, 0.99);
    m.set(1, 1, 1.0);
    m.set(2, 2, 1.0);
    try std.testing.expect(m.isStochastic());

    const target = [_]bool{ false, true, false }; // «достичь ПРОВАЛА»
    const x = try m.reachProbability(&target, 10_000);
    defer std.testing.allocator.free(x);
    try std.testing.expect(@abs(x[0] - 0.01) < 1e-9);
    try std.testing.expect(@abs(x[1] - 1.0) < 1e-9);
}

test "DTMC: 3 попытки с p=0.9 — P(провал) = 0.1³ = 0.001" {
    var m = try Dtmc.init(std.testing.allocator, 5);
    defer m.deinit();
    // 0,1,2 — попытки; 3 — ИТОГОВЫЙ провал; 4 — успех.
    // Модель «3 попытки»: неудача каждой попытки ведёт к СЛЕДУЮЩЕЙ,
    // а в провал попадаем только если провалились ВСЕ три (0.1³).
    m.set(0, 1, 0.1); // попытка 0 провалилась -> попытка 1
    m.set(0, 4, 0.9); // попытка 0 успешна
    m.set(1, 2, 0.1); // попытка 1 провалилась -> попытка 2
    m.set(1, 4, 0.9);
    m.set(2, 3, 0.1); // попытка 2 провалилась -> ИТОГОВЫЙ провал
    m.set(2, 4, 0.9);
    m.set(3, 3, 1.0);
    m.set(4, 4, 1.0);

    const target = [_]bool{ false, false, false, true, false };
    const x = try m.reachProbability(&target, 10_000);
    defer std.testing.allocator.free(x);
    try std.testing.expect(@abs(x[0] - 0.001) < 1e-9); // 0.1^3
}

test "DTMC PCTL: проверка порога P≤0.01 [ F fail ]" {
    var m = try Dtmc.init(std.testing.allocator, 3);
    defer m.deinit();
    m.set(0, 1, 0.001); // очень редкий сбой
    m.set(0, 2, 0.999);
    m.set(1, 1, 1.0);
    m.set(2, 2, 1.0);

    const fail = [_]bool{ false, true, false };
    const x = try m.reachProbability(&fail, 10_000);
    defer std.testing.allocator.free(x);

    // PCTL: P≤0.01 [ F fail ] — истинно (0.001 <= 0.01).
    try std.testing.expect(x[0] <= 0.01);
    // А вот P≤0.0001 [ F fail ] — ЛОЖНО (0.001 > 0.0001): редкий сбой
    // гарантированно наступит при длительной работе.
    try std.testing.expect(!(x[0] <= 0.0001));
}

test "DTMC: нестохастическая матрица отвергается (модель некорректна)" {
    var m = try Dtmc.init(std.testing.allocator, 2);
    defer m.deinit();
    m.set(0, 1, 0.5); // сумма 0.5 != 1
    m.set(1, 1, 1.0);
    try std.testing.expect(!m.isStochastic());
}
