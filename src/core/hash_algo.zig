// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: МУЛЬТИ-АЛГОРИТМИЧЕСКАЯ ДИСПЕТЧЕРИЗАЦИЯ ХЕША.
//!
//! ЗАЧЕМ. Спецификация (§5.3) объявляет поле `hash_algo` заголовка `.kimg`:
//!     `0x0001 = BLAKE3-256`, `0x0002 = SHA2-256`.
//! До этого модуля реализация считала ТОЛЬКО SHA-256, то есть спецификация и
//! код расходились (дефект #4 в честном статусе: «BLAKE3 заявлен, не реализован»).
//!
//! ЧТО ДАЁТ BLAKE3 (ИЗМЕРЕНО, `make bench-hash`, свидетельство
//! `docs/evidence/hash_bench.log`):
//!     размер | SHA-256  | BLAKE3    | выигрыш
//!        96 Б|  214 МБ/с|  259 МБ/с |  1.21x
//!      64 КБ |  292 МБ/с| 2601 МБ/с |  8.92x
//!       4 МБ |  287 МБ/с| 2092 МБ/с |  7.28x
//!     средний выигрыш 5.79x; конвейер .kimg: 273 -> 1580 МБ/с (разрыв с RAW
//!     падает с 306x до 53x).
//!
//! ПОЧЕМУ НЕ SHA-NI: аппаратные инструкции SHA недоступны на Kaby Lake
//! (i7-7700) — появились только в Ice Lake / Zen. Проверено `/proc/cpuinfo`.
//! BLAKE3 на этом железе — единственный доступный рычаг (AVX2).
//!
//! СОВМЕСТИМОСТЬ. Оба алгоритма поддерживаются ОДНОВРЕМЕННО: читатель берёт
//! алгоритм из заголовка образа, поэтому старые образы (SHA-256) читаются
//! без изменений, а новые собираются на BLAKE3.

const std = @import("std");
const simd8 = @import("blake3_simd8.zig");

pub const HashAlgo = enum(u32) {
    /// 0x0001 — BLAKE3-256 (алгоритм по умолчанию при СБОРКЕ).
    blake3 = 1,
    /// 0x0002 — SHA2-256 (совместимость; читается всегда).
    sha256 = 2,

    /// Разбор значения из заголовка. `null` = неизвестный алгоритм (отвергаем).
    pub fn fromInt(v: u32) ?HashAlgo {
        return switch (v) {
            1 => .blake3,
            2 => .sha256,
            else => null,
        };
    }

    /// Алгоритм по умолчанию для НОВЫХ образов.
    pub const DEFAULT: HashAlgo = .blake3;

    /// Единая точка вычисления хеша: длина выхода всегда 32 байта.
    ///
    /// ВАЖНО: `switch` на runtime-enum даёт РАЗНЫЕ типы хешеров
    /// (Blake3 и Sha2x32), поэтому используем `inline else` — ветвление
    /// становится comptime-известным, и типы разрешаются в каждой ветке.
    pub fn hash(self: HashAlgo, data: []const u8, out: *[32]u8) void {
        switch (self) {
            inline else => |a| hashComptime(a, data, out),
        }
    }

    /// Пакетный хеш 8 объектов произвольной длины (каждый <= 1024 Б).
    ///
    /// Для BLAKE3 используется 8-полосный SIMD (`@Vector(8, u32)`), для
    /// SHA-256 — 8 обычных вызовов. Результат БИТ-В-БИТ совпадает с
    /// поштучным хешированием тем же алгоритмом (проверено тестами).
    pub fn hashBatch8(self: HashAlgo, inputs: [8][]const u8, outputs: *[8][32]u8) void {
        switch (self) {
            .blake3 => simd8.hash8SmallObjects(inputs, outputs),
            inline else => |a| for (inputs, 0..) |in, lane| {
                a.hash(in, &outputs[lane]);
            },
        }
    }

    /// Максимальная длина объекта, для которой пакетный путь применим.
    pub fn batchMaxLen() usize {
        return simd8.MAX_SMALL_LEN;
    }


    fn hashComptime(comptime algo: HashAlgo, data: []const u8, out: *[32]u8) void {
        switch (algo) {
            .blake3 => std.crypto.hash.Blake3.hash(data, out[0..32], .{}),
            .sha256 => std.crypto.hash.sha2.Sha256.hash(data, out, .{}),
        }
    }

    /// Имя для диагностики и для строкового префикса в `.kern` (`hash "blake3:…"`).
    pub fn name(self: HashAlgo) []const u8 {
        return switch (self) {
            .blake3 => "blake3",
            .sha256 => "sha256",
        };
    }

    /// Число для поля заголовка.
    pub fn toInt(self: HashAlgo) u32 {
        return @intFromEnum(self);
    }
};

// ===========================================================================
//  ТЕСТЫ
// ===========================================================================

/// Hex-строка из 32 байт (в Zig 0.17 `fmtSliceHexLower` удалён).
fn hexLower(bytes: *const [32]u8) [64]u8 {
    const digits = "0123456789abcdef";
    var out: [64]u8 = undefined;
    for (bytes, 0..) |b, i| {
        out[i * 2] = digits[b >> 4];
        out[i * 2 + 1] = digits[b & 0x0F];
    }
    return out;
}

test "HASH-ALGO: разбор значений заголовка (ровно 1 или 2)" {
    try std.testing.expectEqual(HashAlgo.blake3, HashAlgo.fromInt(1).?);
    try std.testing.expectEqual(HashAlgo.sha256, HashAlgo.fromInt(2).?);
    try std.testing.expectEqual(@as(?HashAlgo, null), HashAlgo.fromInt(0));
    try std.testing.expectEqual(@as(?HashAlgo, null), HashAlgo.fromInt(3));
    try std.testing.expectEqual(@as(?HashAlgo, null), HashAlgo.fromInt(0xFFFFFFFF));
}

test "HASH-ALGO: BLAKE3 и SHA-256 дают РАЗНЫЕ хеши (не подменяют друг друга)" {
    const data = "KERN: проверка диспетчеризации";
    var a: [32]u8 = undefined;
    var b: [32]u8 = undefined;
    HashAlgo.blake3.hash(data, &a);
    HashAlgo.sha256.hash(data, &b);
    try std.testing.expect(!std.mem.eql(u8, &a, &b));
}

test "HASH-ALGO: BLAKE3-256 совпадает с эталонным вектором" {
    // Эталон: BLAKE3("") = af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262
    var out: [32]u8 = undefined;
    HashAlgo.blake3.hash("", &out);
    try std.testing.expectEqualStrings(
        "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262",
        &hexLower(&out),
    );
}

test "HASH-ALGO: SHA-256 совпадает с эталонным вектором" {
    // Эталон: SHA-256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
    var out: [32]u8 = undefined;
    HashAlgo.sha256.hash("", &out);
    try std.testing.expectEqualStrings(
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        &hexLower(&out),
    );
}

test "HASH-ALGO: имена и числовые коды согласованы со спецификацией" {
    try std.testing.expectEqualStrings("blake3", HashAlgo.blake3.name());
    try std.testing.expectEqualStrings("sha256", HashAlgo.sha256.name());
    try std.testing.expectEqual(@as(u32, 1), HashAlgo.blake3.toInt());
    try std.testing.expectEqual(@as(u32, 2), HashAlgo.sha256.toInt());
    try std.testing.expectEqual(HashAlgo.blake3, HashAlgo.DEFAULT);
}

test "HASH-ALGO: SPEC-тест — hash_algo=3 (неизвестный) отвергается" {
    // Спека: `if (hash_algo != 1 and hash_algo != 2) return InvalidHashAlgo;`
    try std.testing.expectEqual(@as(?HashAlgo, null), HashAlgo.fromInt(3));
    try std.testing.expectEqual(@as(?HashAlgo, null), HashAlgo.fromInt(0x0003));
}
