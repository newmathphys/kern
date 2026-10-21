// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

const std = @import("std");

/// KERN-EQ2: двухбитовый квант Белнапа-Данна (B4).
///
/// ЭТОТ ФАЙЛ НЕ БЫЛ ПРЕДОСТАВЛЕН в спецификации — импортируется из
/// `kernfs_router.zig`, `admission_gate.zig` и `main.zig`, но его текста не было.
/// Написан по кодировке из спецификации: `code = p | (n << 1)`
///   0 = N (ничего не известно)
///   1 = T (доказано)
///   2 = F (опровергнуто)
///   3 = B (конфликт: и доказано, и опровергнуто)
pub const Eq2 = enum(u2) {
    N = 0,
    T = 1,
    F = 2,
    B = 3,

    /// 🔴 СВЕРКА СО СПЕКОЙ: в спецификации есть `Eq2.encode(pos, neg)` —
    /// каноническое КОДИРОВАНИЕ кванта `code = p | (n << 1)`. У нас функция
    /// отсутствовала (никто не вызывал, но публичный API спеки был неполон).
    pub fn encode(pos: u1, neg: u1) Eq2 {
        return @enumFromInt(@as(u2, pos) | (@as(u2, neg) << 1));
    }

    /// Псевдонимы имён из спецификации: `p()` и `n()`.
    pub fn p(self: Eq2) u1 {
        return self.positive();
    }
    pub fn n(self: Eq2) u1 {
        return self.negative();
    }

    /// Слияние по порядку знаний: JOIN_K(a,b) = (p_a|p_b, n_a|n_b).
    /// Реализовано через побитовое OR — как и требует спецификация (1 такт).
    pub fn joinKnowledge(a: Eq2, b: Eq2) Eq2 {
        return @enumFromInt(@intFromEnum(a) | @intFromEnum(b));
    }

    /// Псевдоним, которого требует тест-сьют (`joinK`).
    pub fn joinK(a: Eq2, b: Eq2) Eq2 {
        return joinKnowledge(a, b);
    }

    /// Пересечение по порядку знаний (наибольшая нижняя грань).
    /// Для кодировки p|(n<<1) это побитовое AND.
    pub fn meetK(a: Eq2, b: Eq2) Eq2 {
        return @enumFromInt(@intFromEnum(a) & @intFromEnum(b));
    }

    pub fn positive(self: Eq2) u1 {
        return @truncate(@intFromEnum(self) & 0b01);
    }

    pub fn negative(self: Eq2) u1 {
        return @truncate((@intFromEnum(self) >> 1) & 0b01);
    }

    pub fn symbol(self: Eq2) []const u8 {
        return switch (self) {
            .N => "N",
            .T => "T",
            .F => "F",
            .B => "B",
        };
    }
};

/// Отрицание Белнапа (NOT_B): меняет местами p и n.
///   NOT(N)=N, NOT(T)=F, NOT(F)=T, NOT(B)=B
pub fn notB(a: Eq2) Eq2 {
    const p = @intFromEnum(a) & 0b01;
    const n = (@intFromEnum(a) >> 1) & 0b01;
    return @enumFromInt((p << 1) | n);
}

/// Конфляция Белнапа-Фиттинга (~): информационная инверсия.
///
/// Переворачивает порядок знаний, сохраняя порядок истины:
///   ~N = B,  ~B = N,  ~T = T,  ~F = F
/// В терминах пары (t, f) = (p, n):  ~(t,f) = (1-f, 1-t).
///
/// ЗАЧЕМ (Фаза 1): полный набор связок B4 — это `⟨∧,∨,⊗,⊕,¬,~⟩`.
/// Без `~` KERN реализовывал 5 из 6 операций, и «полная алгебра» в
/// документации была неполной.
pub fn conflate(a: Eq2) Eq2 {
    const p = @intFromEnum(a) & 0b01;
    const n = (@intFromEnum(a) >> 1) & 0b01;
    // p' = 1 - n, n' = 1 - p, код = p' | (n' << 1)
    return @enumFromInt(((1 - n) & 0b01) | (((1 - p) & 0b01) << 1));
}

/// Конъюнкция в порядке истинности (AND_T) = inf по <=t.
///
/// ДЕФЕКТ #279 (найден конформанс-экзаменом Фазы 5): табличная реализация
/// ошибалась ровно на парах (N,B) и (B,N): возвращала N вместо F. То есть
/// `N ∧ B` — «нет данных И противоречие» — не давало `F`, хотя F <=t оба
/// значения. Комментарий обещал `N∧B=F`, код возвращал `N`.
///
/// Теперь операция выводится из twist-представления, где ошибка невозможна
/// по построению: inf_t((p1,n1),(p2,n2)) = (p1∧p2, n1∨n2).
pub fn andT(a: Eq2, b: Eq2) Eq2 {
    return Eq2.encode(a.p() & b.p(), a.n() | b.n());
}

/// Дизъюнкция в порядке истинности (OR_T) = sup по <=t.
///
/// ДЕФЕКТ #279: та же ошибка — `B ∨ N` давало `N` вместо `T`.
/// sup_t((p1,n1),(p2,n2)) = (p1∨p2, n1∧n2).
pub fn orT(a: Eq2, b: Eq2) Eq2 {
    return Eq2.encode(a.p() | b.p(), a.n() & b.n());
}

test "EQ2: кодировка p | (n << 1)" {
    try std.testing.expectEqual(@as(u2, 0), @intFromEnum(Eq2.N));
    try std.testing.expectEqual(@as(u2, 1), @intFromEnum(Eq2.T));
    try std.testing.expectEqual(@as(u2, 2), @intFromEnum(Eq2.F));
    try std.testing.expectEqual(@as(u2, 3), @intFromEnum(Eq2.B));
}

test "🔴 СПЕКА: Eq2.encode(p,n) и псевдонимы p()/n() (полный API спеки)" {
    // Из спецификации (16.1.7): code = p | (n << 1).
    try std.testing.expectEqual(Eq2.N, Eq2.encode(0, 0));
    try std.testing.expectEqual(Eq2.T, Eq2.encode(1, 0));
    try std.testing.expectEqual(Eq2.F, Eq2.encode(0, 1));
    try std.testing.expectEqual(Eq2.B, Eq2.encode(1, 1));

    // Псевдонимы p()/n() из спеки совпадают с positive()/negative().
    for ([_]Eq2{ .N, .T, .F, .B }) |v| {
        try std.testing.expectEqual(v.positive(), v.p());
        try std.testing.expectEqual(v.negative(), v.n());
    }
    try std.testing.expectEqual(@as(u1, 1), Eq2.F.n());
    try std.testing.expectEqual(@as(u1, 0), Eq2.F.p());

    // encode/разбор взаимно обратны (полный перебор).
    // ВНИМАНИЕ: счётчик — u2, а НЕ u1: `pos += 1` при pos=1 переполнил бы u1.
    for ([_]u1{ 0, 1 }) |pos| {
        for ([_]u1{ 0, 1 }) |neg| {
            const e = Eq2.encode(pos, neg);
            try std.testing.expectEqual(pos, e.p());
            try std.testing.expectEqual(neg, e.n());
        }
    }
}

test "EQ2: T JOIN F = B (изоляция противоречий)" {
    try std.testing.expectEqual(Eq2.B, Eq2.joinKnowledge(.T, .F));
    try std.testing.expectEqual(Eq2.T, Eq2.joinKnowledge(.T, .N));
    try std.testing.expectEqual(Eq2.F, Eq2.joinKnowledge(.F, .N));
    try std.testing.expectEqual(Eq2.N, Eq2.joinKnowledge(.N, .N));
}

test "EQ2: биты p и n независимы" {
    try std.testing.expectEqual(@as(u1, 1), Eq2.T.positive());
    try std.testing.expectEqual(@as(u1, 0), Eq2.T.negative());
    try std.testing.expectEqual(@as(u1, 0), Eq2.F.positive());
    try std.testing.expectEqual(@as(u1, 1), Eq2.F.negative());
    try std.testing.expectEqual(@as(u1, 1), Eq2.B.positive());
    try std.testing.expectEqual(@as(u1, 1), Eq2.B.negative());
}

test "MATH: де Моргана для порядка истинности (полный перебор)" {
    const all = [_]Eq2{ .N, .T, .F, .B };
    for (all) |a| {
        for (all) |b| {
            // NOT(A AND_T B) == NOT(A) OR_T NOT(B)
            try std.testing.expectEqual(notB(andT(a, b)), orT(notB(a), notB(b)));
            // NOT(A OR_T B) == NOT(A) AND_T NOT(B)
            try std.testing.expectEqual(notB(orT(a, b)), andT(notB(a), notB(b)));
        }
    }
}

test "MATH: таблица отрицания notB (закрывает выживший мутант |->&)" {
    try std.testing.expectEqual(Eq2.N, notB(.N));
    try std.testing.expectEqual(Eq2.F, notB(.T));
    try std.testing.expectEqual(Eq2.T, notB(.F));
    try std.testing.expectEqual(Eq2.B, notB(.B));
}

test "EQ2: конфляция ~ переворачивает порядок знаний" {
    try std.testing.expectEqual(Eq2.B, conflate(.N));
    try std.testing.expectEqual(Eq2.N, conflate(.B));
    try std.testing.expectEqual(Eq2.T, conflate(.T));
    try std.testing.expectEqual(Eq2.F, conflate(.F));
}

test "EQ2: конфляция инволютивна (~~a = a)" {
    for ([_]Eq2{ .N, .T, .F, .B }) |v| {
        try std.testing.expectEqual(v, conflate(conflate(v)));
    }
}

test "EQ2: конфляция и отрицание коммутируют" {
    // ¬ переставляет p/n, ~ дополняет оба бита: операции действуют по разным
    // осям и потому коммутируют (проверяется полным перебором).
    for ([_]Eq2{ .N, .T, .F, .B }) |v| {
        try std.testing.expectEqual(notB(conflate(v)), conflate(notB(v)));
    }
}
