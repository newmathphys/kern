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

/// Конъюнкция в порядке истинности (AND_T).
///
/// Таблица Белнапа-Данна (наибольшая нижняя грань в порядке F ≤ N ≤ T, F ≤ B ≤ T):
///   T∧T=T  T∧F=F  T∧N=N  T∧B=B
///   F∧x=F
///   N∧N=N  N∧B=F
///   B∧B=B
pub fn andT(a: Eq2, b: Eq2) Eq2 {
    return switch (a) {
        .F => .F,
        else => switch (b) {
            .F => .F,
            .T => a,
            .N => .N,
            .B => if (a == .T) .B else .N,
        },
    };
}

/// Дизъюнкция в порядке истинности (OR_T) — нужна для проверки де Моргана.
pub fn orT(a: Eq2, b: Eq2) Eq2 {
    return switch (a) {
        .T => .T,
        else => switch (b) {
            .T => .T,
            .F => a,
            .N => .N,
            .B => if (a == .F) .B else .N,
        },
    };
}

test "EQ2: кодировка p | (n << 1)" {
    try std.testing.expectEqual(@as(u2, 0), @intFromEnum(Eq2.N));
    try std.testing.expectEqual(@as(u2, 1), @intFromEnum(Eq2.T));
    try std.testing.expectEqual(@as(u2, 2), @intFromEnum(Eq2.F));
    try std.testing.expectEqual(@as(u2, 3), @intFromEnum(Eq2.B));
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
