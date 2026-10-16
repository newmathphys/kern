// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN-Next: РЕЗОЛЮЦИЯ СТАТУСОВ по машинным свидетельствам исполнения.
//!
//! Закрывает эпистемический разрыв `empirical → N` → `tested → T (e=1)`.
//!
//! ГЛАВНОЕ (Белнап-аккумулятор): статус НЕ перезаписывается, а НАКАПЛИВАЕТСЯ
//! через joinK. Если один тест зелёный (p=1), а другой красный (n=1), то
//! joinK(T,F) = B (КОНФЛИКТ) → e=0. Перезапись «последним тестом» — уязвимость.
const std = @import("std");
const ast = @import("ast.zig");

/// Двухбитовый квант Белнапа (p = подтверждение, n = опровержение).
pub const Bit = struct {
    p: bool = false,
    n: bool = false,

    pub fn join(a: Bit, b: Bit) Bit {
        return .{ .p = a.p or b.p, .n = a.n or b.n };
    }

    /// Код возврата проверки -> двухбитовый квант Белнапа.
    ///
    /// ТРИ исхода, а не два:
    ///   `0`  -> подтверждение (p) -> T (tested, e = 1);
    ///   `2`  -> КОНВЕНЦИЯ SKIP/NO_EVIDENCE -> НИ p, НИ n -> N (нет свидетельства,
    ///          Врата остаются ЗАКРЫТЫМИ, e = 0);
    ///   иное -> опровержение (n) -> F (refuted, e = 0).
    ///
    /// ДЕФЕКТ #96 (боевой фидбек со второго проекта, где работает kernx):
    /// раньше ЛЮБОЙ ненулевой код давал `n = true`, поэтому ПРОПУЩЕННАЯ по
    /// сети проверка (`exit 2`, SKIP) выглядела как ОПРОВЕРГНУТАЯ (F), а тест
    /// с `assert`, ушедший в SKIP-ветку, мог получить `T` — оба варианта
    /// неверны по Белнапу: пропуск не является ни доказательством, ни
    /// опровержением. Правильный статус — `N (0,0)`.
    pub const skip_exit_code: i64 = 2;

    pub fn ofExit(exit_code: i64) Bit {
        if (exit_code == 0) return .{ .p = true };
        if (exit_code == skip_exit_code) return .{}; // N: нет свидетельства
        return .{ .n = true };
    }

    /// Пропуск ли это (SKIP / нет свидетельства).
    pub fn isSkip(self: Bit) bool {
        return !self.p and !self.n;
    }

    pub fn status(self: Bit) ?ast.Status {
        if (self.p and !self.n) return .tested; // T
        if (!self.p and self.n) return .refuted; // F
        if (self.p and self.n) return .conflicted; // B
        return null; // N — нет свидетельств, статус не трогаем
    }
};

/// Итог резолюции: сколько утверждений переведено и как.
pub const Resolution = struct {
    to_tested: usize = 0,
    to_refuted: usize = 0,
    to_conflicted: usize = 0,
};

/// Возвращает НОВЫЙ массив утверждений с обновлёнными статусами.
/// Исполнения ищутся по связи `link <claim> -> <exec-claim> { supported_by }`,
/// где exec-claim несёт метрику `exit_code`.
pub fn resolve(allocator: std.mem.Allocator, p: ast.Project) !struct { claims: []ast.Claim, stats: Resolution } {
    const claims = try allocator.alloc(ast.Claim, p.claims.len);
    @memcpy(claims, p.claims);
    var stats = Resolution{};

    // Карта: id утверждения -> квант исполнения (из метрики exit_code).
    var exec_q = std.StringHashMap(Bit).init(allocator);
    defer exec_q.deinit();
    for (p.claims) |c| {
        for (c.metrics) |m| {
            if (std.mem.eql(u8, m.name, "exit_code")) {
                // БАГ-ФИКС №1: NaN/inf -> @intFromFloat паникует.
                // 🔴 БАГ-ФИКС №2 (найден построчным аудитом): `isFinite`
                // НЕ защищает от ОГРОМНЫХ КОНЕЧНЫХ значений! `1e300` —
                // конечное число, но вне диапазона i64 -> @intFromFloat
                // ПАНИКУЕТ. Битый .kern ронял инструмент (DoS).
                // Теперь: вне диапазона i64 — свидетельством НЕ считается
                // (fail-closed) и о факте сообщается.
                const in_range = std.math.isFinite(m.value) and
                    m.value >= -9.2233720368547758e18 and
                    m.value <= 9.2233720368547758e18;
                if (in_range) {
                    try exec_q.put(c.id, Bit.ofExit(@intFromFloat(m.value)));
                } else {
                    std.debug.print("[!] exit_code вне диапазона i64 ({d}) у '{s}' — свидетельство ИГНОРИРОВАНО\n", .{ m.value, c.id });
                }
            }
        }
    }

    // Для каждого утверждения: собрать кванты всех связанных исполнений.
    for (claims) |*c| {
        var acc: Bit = .{};
        var any = false;
        for (p.links) |l| {
            if (!std.mem.eql(u8, l.from, c.id)) continue;
            if (l.relation != .supported_by) continue;
            if (exec_q.get(l.to)) |q| {
                acc = Bit.join(acc, q);
                any = true;
            }
        }
        if (!any) continue;
        if (acc.status()) |new_status| {
            if (new_status != c.status) {
                switch (new_status) {
                    .tested => stats.to_tested += 1,
                    .refuted => stats.to_refuted += 1,
                    .conflicted => stats.to_conflicted += 1,
                    else => {},
                }
                c.status = new_status;
            }
        }
    }
    return .{ .claims = claims, .stats = stats };
}

// =========================================================================
// ТЕСТЫ (fail-to-pass: аккумулятор vs перезапись)
// =========================================================================

test "TRUTH: один зелёный тест переводит claim в tested (N -> T)" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const src =
        \\project "P" { version "1" }
        \\claim "feature X" { status empirical }
        \\claim "execution: run X" { status tested metric exit_code = 0 }
        \\link "claim:feature X" -> "claim:execution: run X" { relation "supported_by" }
    ;
    const res = try parser.parse(a, src);
    const r = try resolve(a, res.project);
    try std.testing.expectEqual(@as(usize, 1), r.stats.to_tested);
    for (r.claims) |c| {
        if (std.mem.eql(u8, c.statement, "feature X"))
            try std.testing.expectEqual(ast.Status.tested, c.status);
    }
}

test "TRUTH: один красный тест переводит claim в refuted (n=1)" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const src =
        \\project "P" { version "1" }
        \\claim "feature Y" { status empirical }
        \\claim "execution: run Y" { status refuted metric exit_code = 1 }
        \\link "claim:feature Y" -> "claim:execution: run Y" { relation "supported_by" }
    ;
    const res = try parser.parse(a, src);
    const r = try resolve(a, res.project);
    try std.testing.expectEqual(@as(usize, 1), r.stats.to_refuted);
}

test "TRUTH КЛЮЧЕВОЙ: зелёный + красный = КОНФЛИКТ B (не перезапись!)" {
    // Это ловит уязвимость «статус = последний тест»: T|F = B, e=0.
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const src =
        \\project "P" { version "1" }
        \\claim "feature Z" { status empirical }
        \\claim "execution: light" { status tested metric exit_code = 0 }
        \\claim "execution: heavy" { status refuted metric exit_code = 124 }
        \\link "claim:feature Z" -> "claim:execution: light" { relation "supported_by" }
        \\link "claim:feature Z" -> "claim:execution: heavy" { relation "supported_by" }
    ;
    const res = try parser.parse(a, src);
    const r = try resolve(a, res.project);
    try std.testing.expectEqual(@as(usize, 1), r.stats.to_conflicted);
    for (r.claims) |c| {
        if (std.mem.eql(u8, c.statement, "feature Z"))
            try std.testing.expectEqual(ast.Status.conflicted, c.status);
    }
}

test "ФИКС: NaN/битая метрика exit_code не паникует" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const src =
        \\project "P" { version "1" }
        \\claim "c" { status empirical }
        \\claim "exec nan" { status tested metric exit_code = nan }
        \\claim "exec inf" { status tested metric exit_code = inf }
        \\claim "exec huge" { status tested metric exit_code = 999999999999999999999999999999999999 }
        \\claim "exec big2" { status tested metric exit_code = 99999999999999999999999999 }
        \\link "claim:c" -> "claim:exec nan" { relation "supported_by" }
        \\link "claim:c" -> "claim:exec inf" { relation "supported_by" }
        \\link "claim:c" -> "claim:exec huge" { relation "supported_by" }
        \\link "claim:c" -> "claim:exec big2" { relation "supported_by" }
    ;
    const res = try parser.parse(a, src);
    const r = try resolve(a, res.project);
    // ВСЕ четыре значения негодны как свидетельство -> статус НЕ меняется,
    // паники @intFromFloat нет (раньше `1e300` РОНЯЛ инструмент).
    try std.testing.expectEqual(@as(usize, 0), r.stats.to_tested);
    try std.testing.expectEqual(@as(usize, 0), r.stats.to_refuted);
    try std.testing.expectEqual(@as(usize, 0), r.stats.to_conflicted);
}

test "TRUTH: SKIP (exit 2) -> N (0,0), НЕ F и НЕ T (боевой фидбек #96)" {
    const alloc = std.testing.allocator;
    // Сценарий со второго проекта: тест СОДЕРЖИТ assert (анти-вакуум молчит),
    // но во время исполнения ушёл в SKIP-ветку (нет сети) и вернул код 2.
    // Такой пропуск не является ни доказательством, ни опровержением:
    // по Белнапу это N (0,0), и Врата обязаны остаться ЗАКРЫТЫМИ.
    const src =
        \\project "skip" { version "1" mode "truth" root "." }
        \\claim "execution: run net-test" { status empirical metric exit_code = 2 }
    ;
    var arena = std.heap.ArenaAllocator.init(alloc);
    defer arena.deinit();
    const a = arena.allocator();
    const parsed = try @import("parser.zig").parse(a, src);
    const r = try resolve(a, parsed.project);

    // Главное: НЕ стало tested (T) и НЕ стало refuted (F).
    try std.testing.expectEqual(@as(usize, 0), r.stats.to_tested);
    try std.testing.expectEqual(@as(usize, 0), r.stats.to_refuted);
    // Статус остался «не доказан» (empirical/unknown), e = 0.
    for (r.claims) |c| {
        try std.testing.expect(c.status != .tested);
        try std.testing.expect(c.status != .refuted);
    }

    // Прямая проверка кванта: exit 2 -> пустой квант (N).
    const b2 = Bit.ofExit(2);
    try std.testing.expect(b2.isSkip());
    try std.testing.expect(b2.status() == null); // N: статус не присваивается
    // Контроль: 0 -> T, 1 -> F (поведение не изменилось).
    try std.testing.expect(Bit.ofExit(0).status() == .tested);
    try std.testing.expect(Bit.ofExit(1).status() == .refuted);
}
