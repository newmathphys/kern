// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ЗАЩИТА АВТОРСТВА (Ownership & Attestation).
//!
//! Три независимых механизма закрепления авторства:
//!   1. comptime-ТОКЕН — впечатывается в секцию .rodata готового бинарника;
//!   2. КЛЮЧ-ЗАМОК (Ed25519) — публичный ключ автора вшит; подпись фразы
//!      доказывает авторство (приватный ключ только у автора);
//!   3. .kimg-ТОКЕН — образы доказательств можно аттестовать (`kernx status --auth`).
//!
//! Проверка «кражи» бинарника: `strings kernc | grep ed53cd2f` найдёт токен.
const std = @import("std");
const Ed25519 = std.crypto.sign.Ed25519;

/// Имя автора (для --version и аттестации).
pub const AUTHOR = "Vital Kalinousky";

/// Год копирайта.
pub const YEAR = "2026";

/// Публичный токен автора (SHA-256 от секретной фразы).
/// base64: 7VPNLxyo/7jJuj5IjxFt5BNLn6O1r6kOGgQP/96e76o
/// ВПЕЧАТЫВАЕТСЯ в .rodata: он не используется логикой, но физически
/// присутствует в теле бинарника — удалить, не сломав файл, нельзя.
pub const OWNER_TOKEN: [32]u8 = .{
    0xed, 0x53, 0xcd, 0x2f, 0x1c, 0xa8, 0xff, 0xb8,
    0xc9, 0xba, 0x3e, 0x48, 0x8f, 0x11, 0x6d, 0xe4,
    0x13, 0x4b, 0x9f, 0xa3, 0xb5, 0xaf, 0xa9, 0x0e,
    0x1a, 0x04, 0x0f, 0xff, 0xde, 0x9e, 0xef, 0xaa,
};

/// HEX-строка токена (comptime) — чтобы `strings kernc | grep <hex>` находил её
/// напрямую в секции .rodata готового бинарника.
pub const OWNER_TOKEN_HEX = "ed53cd2f1ca8ffb8c9ba3e488f116de4134b9fa3b5afa90e1a040fffde9eefaa";

/// Фраза, доказывающая авторство («Я — создатель KERN»).
pub const OWNERSHIP_STATEMENT = "I am the creator of KERN";

/// Публичный ключ автора (Ed25519) — «ЗАМОК». Приватный ключ — только у автора.
pub const OWNER_PUBLIC_KEY: [32]u8 = .{
    0x81, 0xe2, 0x30, 0xf7, 0x4f, 0xe0, 0xaa, 0x81,
    0xee, 0x01, 0x1a, 0x43, 0x0a, 0x1a, 0xe5, 0x37,
    0xd4, 0xb8, 0xf7, 0xb6, 0x03, 0xd6, 0x2a, 0x8c,
    0x6f, 0xf2, 0xf2, 0xd4, 0x5d, 0xdd, 0x6e, 0xc3,
};

/// Подпись OWNERSHIP_STATEMENT приватным ключом — «КЛЮЧ».
pub const OWNERSHIP_SIGNATURE: [64]u8 = .{
    0x47, 0x32, 0x56, 0xe6, 0x2b, 0xfe, 0x02, 0x28,
    0x95, 0x8a, 0xad, 0x1d, 0x55, 0x28, 0xbb, 0x9a,
    0xc9, 0x40, 0xea, 0xce, 0x88, 0x22, 0x1c, 0xdc,
    0x63, 0xfa, 0x48, 0xc3, 0x94, 0xd4, 0x8c, 0x35,
    0xbe, 0x2a, 0xd3, 0xd7, 0x82, 0x87, 0x51, 0xb9,
    0xb3, 0xd9, 0xbe, 0x7b, 0x67, 0x5e, 0x28, 0x76,
    0xfe, 0xb6, 0xb6, 0x33, 0x45, 0xc4, 0x12, 0xce,
    0xb0, 0x7f, 0x07, 0xfd, 0xcf, 0xd2, 0xb5, 0x09,
};

/// Проверка «замка»: подпись соответствует вшитому публичному ключу.
pub fn verifyOwnership() bool {
    const pk = Ed25519.PublicKey.fromBytes(OWNER_PUBLIC_KEY) catch return false;
    const sig = Ed25519.Signature.fromBytes(OWNERSHIP_SIGNATURE);
    sig.verify(OWNERSHIP_STATEMENT, pk) catch return false;
    return true;
}

/// HEX-представление токена (для `strings`-проверки).
pub fn tokenHex(buf: *[64]u8) []const u8 {
    const hex = "0123456789abcdef";
    for (OWNER_TOKEN, 0..) |b, i| {
        buf[i * 2] = hex[b >> 4];
        buf[i * 2 + 1] = hex[b & 0x0f];
    }
    return buf[0..64];
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "АВТОРСТВО: ключ-замок валиден (подпись соответствует публичному ключу)" {
    try std.testing.expect(verifyOwnership());
}

test "АВТОРСТВО: подмена подписи отвергается" {
    var sig = OWNERSHIP_SIGNATURE;
    sig[0] ^= 0xFF;
    const pk = try Ed25519.PublicKey.fromBytes(OWNER_PUBLIC_KEY);
    const s = Ed25519.Signature.fromBytes(sig);
    // Любая ошибка (неверная подпись ИЛИ невалидная кодировка) — подделка отвергнута.
    if (s.verify(OWNERSHIP_STATEMENT, pk)) |_| {
        return error.ShouldHaveFailed;
    } else |_| {}
}

test "АВТОРСТВО: tokenHex даёт ожидаемую строку" {
    var buf: [64]u8 = undefined;
    const h = tokenHex(&buf);
    try std.testing.expectEqualStrings("ed53cd2f1ca8ffb8c9ba3e488f116de4134b9fa3b5afa90e1a040fffde9eefaa", h);
}
