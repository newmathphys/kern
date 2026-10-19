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

// =============================================================================
// ЭШЕЛОН 2, ПУНКТ 10 — EVIDENCE DECAY / STALE GATE.
//
// ЗАЧЕМ. Свидетельство `T (1,0)` получено на КОНКРЕТНОЙ версии файла. Если файл
// с тех пор изменился, старое свидетельство БОЛЬШЕ НЕ ОПИСЫВАЕТ то, что лежит на
// диске, и не имеет права держать Врата открытыми.
//
// ПРАВИЛО (монотонно безопасное): при несовпадении отпечатков сбрасывается
// ТОЛЬКО положительный бит `p`. Тогда `T (1,0) -> N (0,0)` (`e = 0`), а
// опровержение `F (0,1)` СОХРАНЯЕТСЯ: старый провал не «лечится» сам собой,
// потому что это лишь оставляет Врата ЗАКРЫТЫМИ (консервативно).
//
// Сравнение отпечатков — КОНСТАНТНО-ВРЕМЕННОЕ (`timing_safe.eql`): иначе
// время сравнения выдавало бы число совпавших байт (сторонний канал).
// =============================================================================

/// Допуск `e` из кванта Белнапа: `1` только при `T` (есть подтверждение, нет
/// опровержения). `N`/`F`/`B` -> `0`.
pub fn allowance(b: Bit) u1 {
    return if (b.p and !b.n) 1 else 0;
}

/// BLAKE3-отпечаток содержимого (привязка свидетельства к версии файла).
pub fn digestOf(data: []const u8) [32]u8 {
    var d: [32]u8 = undefined;
    std.crypto.hash.Blake3.hash(data, &d, .{});
    return d;
}

/// СВЕЖЕСТЬ СВИДЕТЕЛЬСТВА. `recorded` — отпечаток В МОМЕНТ получения вердикта,
/// `current` — отпечаток ФАЙЛА СЕЙЧАС.
///
/// Совпали -> вердикт без изменений. Не совпали -> `p` сбрасывается
/// (`stale evidence -> e = 0`), `n` сохраняется.
pub fn evaluateWithFreshness(verdict: Bit, recorded: [32]u8, current: [32]u8) Bit {
    if (std.crypto.timing_safe.eql([32]u8, recorded, current)) return verdict;
    return .{ .p = false, .n = verdict.n };
}

/// ПУНКТ 7 ПЛАНА v2.5 — АППАРАТНО-УСТОЙЧИВОЕ КОДИРОВАНИЕ ДОПУСКА.
///
/// ЧТО ЭТО. Допуск Врат (`e = 1` пропущено / `e = 0` закрыто) хранится не как
/// один бит, а как 64-битное слово-константа. Две константы —
/// **точные поразрядные дополнения** друг друга, поэтому расстояние Хэмминга
/// между ними равно ровно 64 битам.
///
/// ЧТО ЭТО ДАЁТ (и что это ДАЁТ ПРОВЕРЯЕМО): при допуске до `TOLERANCE` =
/// 8 инвертированных бит решение НЕ может перевернуться. Формально: слово,
/// отстоящее от `DENY_CODE` на d ≤ 8 бит, отстоит от `ALLOW_CODE` на 64 − d ≥ 56
/// бит, то есть остаётся `DENY`. Одно искажённое бит-поле не превращает
/// «закрыто» в «пропущено» — это свойство закреплено тестами ниже.
///
/// ЧЕГО ЭТО НЕ ДЕЛАЕТ (честно, чтобы не было самообмана):
///   * это **НЕ** доказанное свойство ядра и **НЕ** «защита от космических
///     лучей»: реальную частоту SEU мы измерить не можем, а DO-178C такого
///     кодирования не требует;
///   * это **защитная избыточность**, а не верификация: она снижает
///     вероятность тихого переворота решения при одиночном/кратном сбое
///     памяти, и только;
///   * тип `e` в ядре (`admission_gate.zig`, `u1`) НЕ меняется — примитив
///     изолирован, чтобы не тянуть 64-битное представление через все вызовы.
///
/// ПОВЕДЕНИЕ ПРИ НЕОПОЗНАВАЕМОМ СЛОВЕ: `decode` возвращает `null`
/// (fail-closed). Вызывающий обязан трактовать `null` как `e = 0`.
pub const AdmissionCode = struct {
    /// Допуск: до стольких инвертированных бит решение обязано сохраниться.
    /// Должно быть строго меньше 32, иначе константы станут неразличимы.
    pub const TOLERANCE: u6 = 8;

    /// `e = 1` — пропущено в прод.
    pub const ALLOW_CODE: u64 = 0xA55A_3C3C_C3C3_5AA5;
    /// `e = 0` — Врата закрыты. Точное дополнение `ALLOW_CODE`.
    pub const DENY_CODE: u64 = 0x5AA5_C3C3_3C3C_A55A;

    comptime {
        // Инвариант кодирования: константы — дополнения, расстояние ровно 64.
        if (ALLOW_CODE ^ DENY_CODE != ~@as(u64, 0)) {
            @compileError("AdmissionCode: константы обязаны быть поразрядными дополнениями");
        }
        if (TOLERANCE >= 32) {
            @compileError("AdmissionCode: TOLERANCE >= 32 делает константы неразличимыми");
        }
    }

    /// Сколько бит различаются.
    pub fn distance(a: u64, b: u64) u7 {
        return @popCount(a ^ b);
    }

    /// Закодировать допуск: `e` — это `u1` (0 или 1), как в ядре.
    pub fn encode(e: u1) u64 {
        return if (e == 1) ALLOW_CODE else DENY_CODE;
    }

    /// Раскодировать допуск. `null` = слово повреждено сверх допуска
    /// (fail-closed: вызывающий обязан закрыть Врата).
    pub fn decode(word: u64) ?u1 {
        const d_allow = distance(word, ALLOW_CODE);
        const d_deny = distance(word, DENY_CODE);
        if (d_allow <= TOLERANCE) return 1;
        if (d_deny <= TOLERANCE) return 0;
        return null;
    }

    /// Раскодировать с ЗАКРЫТИЕМ по умолчанию: любое сомнение -> `e = 0`.
    /// Это и есть «fail-closed» на границе: неопознанное слово не пропускает.
    pub fn decodeOrDeny(word: u64) u1 {
        return decode(word) orelse 0;
    }
};

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

// ПУНКТ 7 ПЛАНА v2.5: проверяемое свойство кодирования допуска.
//
// Проверяем ИМЕННО ТО, что обещано в комментарии к `AdmissionCode`:
// константы — дополнения (расстояние 64), до `TOLERANCE` бит решение не
// переворачивается, за порогом решение НЕ выдумывается (`null`), а
// `decodeOrDeny` закрывает Врата. Никаких заявлений о SEU здесь нет.
test "AdmissionCode: дополнение 64 бита, допуск 8 бит, fail-closed за порогом" {
    const A = AdmissionCode;

    // 1. Константы — точные поразрядные дополнения: расстояние ровно 64.
    try std.testing.expectEqual(@as(u7, 64), A.distance(A.ALLOW_CODE, A.DENY_CODE));
    try std.testing.expect(A.ALLOW_CODE != A.DENY_CODE);

    // 2. Круговой прогон кодирования.
    try std.testing.expectEqual(@as(?u1, 1), A.decode(A.encode(1)));
    try std.testing.expectEqual(@as(?u1, 0), A.decode(A.encode(0)));

    // 3. До TOLERANCE инвертированных бит решение НЕ переворачивается.
    var i: u6 = 0;
    while (i < A.TOLERANCE) : (i += 1) {
        const flip = @as(u64, 1) << i;
        try std.testing.expectEqual(@as(?u1, 1), A.decode(A.ALLOW_CODE ^ flip));
        try std.testing.expectEqual(@as(?u1, 0), A.decode(A.DENY_CODE ^ flip));
    }

    // 4. Ровно 9 бит — за порогом: решение не выдумывается, Врата закрываются.
    const nine_off = A.ALLOW_CODE ^ @as(u64, 0x1FF);
    try std.testing.expectEqual(@as(u7, 9), A.distance(nine_off, A.ALLOW_CODE));
    try std.testing.expectEqual(@as(?u1, null), A.decode(nine_off));
    try std.testing.expectEqual(@as(u1, 0), A.decodeOrDeny(nine_off));

    // 5. Середина диапазона (32 бита) — тоже `null`: при TOLERANCE >= 32
    //    константы были бы неразличимы, поэтому порог ограничен comptime-ом.
    const half = A.ALLOW_CODE ^ @as(u64, 0xFFFF_FFFF);
    try std.testing.expectEqual(@as(u7, 32), A.distance(half, A.ALLOW_CODE));
    try std.testing.expectEqual(@as(?u1, null), A.decode(half));
    try std.testing.expectEqual(@as(u1, 0), A.decodeOrDeny(half));

    // 6. Полностью инвертированное слово — это ровно DENY_CODE.
    try std.testing.expectEqual(@as(?u1, 0), A.decode(~A.ALLOW_CODE));
}



test "СВЕЖЕСТЬ: неизменённый файл сохраняет T (e = 1)" {
    const src = "contract: x >= 0";
    const d = digestOf(src);
    const v = Bit{ .p = true }; // T (1,0): проверка прошла
    const fresh = evaluateWithFreshness(v, d, digestOf(src));
    try std.testing.expectEqual(@as(u1, 1), allowance(fresh));
    try std.testing.expectEqual(ast.Status.tested, fresh.status().?);
}

test "СВЕЖЕСТЬ: изменение 1 БАЙТА в файле сбрасывает T -> N (e = 0)" {
    const before = "contract: x >= 0";
    const after = "contract: x >= 1"; // изменён ОДИН байт
    const v = Bit{ .p = true };
    const stale = evaluateWithFreshness(v, digestOf(before), digestOf(after));
    try std.testing.expectEqual(@as(u1, 0), allowance(stale));
    try std.testing.expect(stale.isSkip()); // N (0,0)
    // КОНСЕРВАТИВНОСТЬ: старое опровержение НЕ «лечится» изменением файла.
    const f = Bit{ .n = true };
    const f2 = evaluateWithFreshness(f, digestOf(before), digestOf(after));
    try std.testing.expectEqual(@as(u1, 0), allowance(f2));
    try std.testing.expect(f2.n);
}

// ЭШЕЛОН 6, ПУНКТ 35: МУЛЬТИ-АГЕНТНЫЙ АРБИТРАЖ В РЕШЁТКЕ БЕЛНАПА.
//
// Сценарий: Агент-Кодер заявляет T (1,0), Агент-Аудитор находит уязвимость
// -> F (0,1). Монотонная склейка JOIN_K(T,F) = B (1,1) ЗАКРЫВАЕТ Врата, и
// никакое количество последующих голосов T не перезаписывает B (поглощение).
test "ПУНКТ 35: рой агентов — JOIN_K(T,F)=B, поглощение B, JOIN_K(T,T)=T" {
    const t = Bit{ .p = true, .n = false }; // T
    const f = Bit{ .p = false, .n = true }; // F
    const b = Bit{ .p = true, .n = true }; // B

    // (1) Кодер vs Аудитор -> КОНФЛИКТ: оба бита выставлены, Врата ЗАКРЫТЫ.
    const conflict = Bit.join(t, f);
    try std.testing.expect(conflict.p and conflict.n);
    try std.testing.expectEqual(@as(u1, 0), allowance(conflict));

    // (2) ПОГЛОЩЕНИЕ: 100 голосов T не перезаписывают противоречие.
    var acc = conflict;
    var i: usize = 0;
    while (i < 100) : (i += 1) acc = Bit.join(acc, t);
    try std.testing.expect(acc.p and acc.n);
    try std.testing.expectEqual(@as(u1, 0), allowance(acc));

    // (3) Согласие всех агентов в T -> T, Врата ОТКРЫТЫ.
    const agree = Bit.join(t, Bit.join(t, t));
    try std.testing.expect(!agree.n);
    try std.testing.expectEqual(@as(u1, 1), allowance(agree));

    // (4) Контроль: F (без противоречия) тоже закрывает Врата, но НЕ равен B.
    try std.testing.expect(!f.p and f.n);
    try std.testing.expectEqual(@as(u1, 0), allowance(f));
    // (5) Поглощение в ОБЕ стороны: JOIN_K(B, F) = B (F не «снимает» конфликт).
    const bf = Bit.join(b, f);
    try std.testing.expect(bf.p and bf.n);
    try std.testing.expectEqual(@as(u1, 0), allowance(bf));
}

// ============================================================================
// РАЗДЕЛ 2 ЭНЦИКЛОПЕДИИ: ГЕНЕРАТИВНОЕ Property-Based Testing (PBT).
// 500 псевдослучайных входов по ДЕТЕРМИНИРОВАННОМУ PRNG (xorshift64*),
// поэтому провал воспроизводим: тот же seed -> тот же вход.
// Проверяются ЗАКОНЫ, а не отдельные примеры.
// ============================================================================
const PbtRng = struct {
    s: u64,
    fn next(self: *PbtRng) u64 {
        var x = self.s;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.s = x;
        return x *% 0x2545F4914F6CDD1D;
    }
    fn bit(self: *PbtRng) Bit {
        const v = self.next();
        return .{ .p = (v & 1) != 0, .n = (v & 2) != 0 };
    }
};

test "PBT: законы решётки Белнапа на 500 случайных входах" {
    var rng = PbtRng{ .s = 0xDEADBEEF };
    var i: usize = 0;
    while (i < 500) : (i += 1) {
        const a = rng.bit();
        const b = rng.bit();
        const c = rng.bit();

        // Коммутативность join.
        try std.testing.expectEqual(join2(a, b), join2(b, a));
        // Ассоциативность.
        try std.testing.expectEqual(join2(join2(a, b), c), join2(a, join2(b, c)));
        // Идемпотентность.
        try std.testing.expectEqual(join2(a, a), a);
        // Нейтральный элемент N (0,0) — в Белнапе это «нет свидетельства».
        // ВНИМАНИЕ: N не нейтрален как в max-решётке; проверяем СЛАБОЕ свойство:
        // join(N, N) = N (а не «N нейтрален для всех a» — это было бы ЛОЖЬ).
        try std.testing.expectEqual(join2(Bit{}, Bit{}), Bit{});
        // Монотонность допуска: если e=1, то p=1 и n=0.
        if (allowance(a) == 1) {
            try std.testing.expect(a.p and !a.n);
        }
        // Поглощение противоречием: join(B, x) = B для ЛЮБОГО x.
        const B = Bit{ .p = true, .n = true };
        try std.testing.expectEqual(B, join2(B, a));
    }
}

/// Локальная обёртка, чтобы тест не зависел от порядка объявления методов.
fn join2(a: Bit, b: Bit) Bit {
    return .{ .p = a.p or b.p, .n = a.n or b.n };
}

test "PBT: Хэмминг-код AdmissionCode на 500 случайных искажениях" {
    var rng = PbtRng{ .s = 0x1234_5678 };
    var i: usize = 0;
    while (i < 500) : (i += 1) {
        // Искажаем не более TOLERANCE бит -> решение НЕ должно перевернуться.
        var word = AdmissionCode.ALLOW_CODE;
        const k = rng.next() % (AdmissionCode.TOLERANCE + 1);
        var j: u64 = 0;
        while (j < k) : (j += 1) {
            const pos: u6 = @intCast(rng.next() % 64);
            word ^= @as(u64, 1) << pos;
        }
        try std.testing.expectEqual(@as(?u1, 1), AdmissionCode.decode(word));
    }
}
