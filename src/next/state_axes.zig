// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! СЕМЬ ОСЕЙ СОСТОЯНИЯ (Фаза 1 плана).
//!
//! ЗАЧЕМ. До этой фазы в коде было два грубых состояния: `Bit {p, n}` и
//! `ast.Status` (12 значений), где верификация, жизненный цикл и целостность
//! были перемешаны. Из-за этого «таймаут» и «опровергнуто» неразличимо
//! превращались в `F`, а отсутствие сертификата — в «не доказано».
//!
//! Здесь оси разделены и связаны ОДНОЙ таблицей отображения:
//!   proved              -> T   (есть свидетельство истины)
//!   refuted             -> F   (есть контрпример)
//!   unknown             -> N   (свидетельств нет)
//!   timeout             -> N   (НЕ F: это отсутствие результата, не ложь)
//!   out_of_fuel         -> N   (НЕ B: исчерпание бюджета — не противоречие)
//!   invalid_certificate -> N   (НЕ F: плохой сертификат не опровергает код)
//!   tool_error          -> N   (НЕ F: сломанный инструмент не вердикт)
//!
//! `B` (both) НЕ производится вердиктом вообще: он возникает только при
//! слиянии двух свидетельств (`joinK(T, F)`), то есть в `truth.zig`.
//! Это и есть закон «противоречие нельзя затереть».

const std = @import("std");

/// Ось 1: значение Белнапа-Данна (квант B4).
pub const BelnapValue = enum(u2) { N = 0, T = 1, F = 2, B = 3 };

/// Ось 2: покрытие проверки. `bounded` — доказано только до границы
/// (например, интуиционистский режим с ограничением миров, Ф6.2).
pub const CoverageState = enum { none, bounded, full };

/// Ось 3: вердикт верификатора. Семь исходов, а не два.
pub const VerificationVerdict = enum {
    proved,
    refuted,
    unknown,
    timeout,
    out_of_fuel,
    invalid_certificate,
    tool_error,
};

/// Ось 4: жизненный цикл контракта/утверждения.
pub const Lifecycle = enum { draft, frozen, deprecated, retracted };

/// Ось 5: целостность артефакта.
pub const IntegrityState = enum { unknown, verified, corrupt };

/// Ось 6: доверие к ключу/чекеру.
pub const TrustState = enum { untrusted, trusted, revoked };

/// Ось 7: исход исполнения в песочнице KERN-X.
pub const ExecutionOutcome = enum { ok, runtime_error, non_termination, out_of_fuel, crash };

/// Тип запроса: сертификат обязан соответствовать тому, что доказывали.
pub const QueryKind = enum { refutation, satisfiability, equivalence };

/// ЕДИНСТВЕННАЯ таблица отображения «вердикт -> Белнап».
///
/// Возвращает `null` для `B`: вердикт не может сам по себе дать противоречие.
pub fn toBelnap(v: VerificationVerdict) ?BelnapValue {
    return switch (v) {
        .proved => .T,
        .refuted => .F,
        .unknown, .timeout, .out_of_fuel, .invalid_certificate, .tool_error => .N,
    };
}

/// Является ли исход «отсутствием результата» (а не ложью).
pub fn isInconclusive(v: VerificationVerdict) bool {
    return switch (v) {
        .unknown, .timeout, .out_of_fuel, .invalid_certificate, .tool_error => true,
        .proved, .refuted => false,
    };
}

/// Требует ли исход ручного вмешательства (а не перезапуска).
pub fn needsHuman(v: VerificationVerdict) bool {
    return switch (v) {
        .invalid_certificate, .tool_error => true,
        else => false,
    };
}

/// Отображение исхода исполнения в вердикт: единственное место, где
/// «упало в песочнице» становится вердиктом.
pub fn verdictFromExecution(o: ExecutionOutcome) VerificationVerdict {
    return switch (o) {
        .ok => .proved,
        .runtime_error, .crash => .refuted,
        .non_termination => .timeout,
        .out_of_fuel => .out_of_fuel,
    };
}

test "ОСИ: timeout — это N, а НЕ F" {
    try std.testing.expectEqual(BelnapValue.N, toBelnap(.timeout).?);
    try std.testing.expect(toBelnap(.timeout).? != .F);
    try std.testing.expect(isInconclusive(.timeout));
}

test "ОСИ: out_of_fuel — это N, а НЕ B" {
    try std.testing.expectEqual(BelnapValue.N, toBelnap(.out_of_fuel).?);
    try std.testing.expect(toBelnap(.out_of_fuel).? != .B);
}

test "ОСИ: invalid_certificate — это N, а НЕ F" {
    try std.testing.expectEqual(BelnapValue.N, toBelnap(.invalid_certificate).?);
    try std.testing.expect(toBelnap(.invalid_certificate).? != .F);
    try std.testing.expect(needsHuman(.invalid_certificate));
}

test "ОСИ: ни один вердикт не производит B (только join свидетельств)" {
    for ([_]VerificationVerdict{ .proved, .refuted, .unknown, .timeout,
        .out_of_fuel, .invalid_certificate, .tool_error }) |v|
    {
        const b = toBelnap(v).?;
        try std.testing.expect(b != .B);
    }
}

test "ОСИ: T, F и N достижимы вердиктами" {
    try std.testing.expectEqual(BelnapValue.T, toBelnap(.proved).?);
    try std.testing.expectEqual(BelnapValue.F, toBelnap(.refuted).?);
    try std.testing.expectEqual(BelnapValue.N, toBelnap(.unknown).?);
}

test "ОСИ: покрытие — три состояния, и только full означает полное" {
    try std.testing.expect(CoverageState.bounded != CoverageState.full);
    try std.testing.expect(CoverageState.none != CoverageState.full);
}

test "ОСИ: падение в песочнице — refuted, незавершение — timeout" {
    try std.testing.expectEqual(VerificationVerdict.refuted, verdictFromExecution(.crash));
    try std.testing.expectEqual(VerificationVerdict.timeout, verdictFromExecution(.non_termination));
    try std.testing.expectEqual(VerificationVerdict.out_of_fuel, verdictFromExecution(.out_of_fuel));
}

test "ОСИ: QueryKind различает три типа запроса" {
    try std.testing.expect(QueryKind.refutation != QueryKind.equivalence);
    try std.testing.expect(QueryKind.satisfiability != QueryKind.equivalence);
    try std.testing.expect(@sizeOf(QueryKind) <= 1);
}
