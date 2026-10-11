// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

const std = @import("std");
const cov = @import("../cov.zig");

pub const KimgError = error{
    OutOfBounds,
    InvalidReservedBytes,
    MerkleRootMismatch,
};

/// ЛОГИЧЕСКОЕ представление 96-байтной записи таблицы объектов KERN v1.2.
///
/// ⚠️ ВАЖНО (исправлено тестом `alignment_stress`): `@sizeOf(ObjectEntry) == 72`,
/// а НЕ 96. 24 байта (смещения 72..95) — это `reserved`-область на диске,
/// которая проверяется отдельно (`InvalidReservedBytes`) и в структуру не входит.
/// Раньше комментарий утверждал «строго 96 байт» — это было расхождение
/// документации и реальности.
///
/// БЕЗОПАСНОСТЬ: структура НИКОГДА не читается через `@ptrCast` — только через
/// `std.mem.readInt` по смещениям. Поэтому 72 ≠ 96 не является ошибкой.
/// Если однажды появится `@ptrCast(*ObjectEntry)`, это станет переполнением
/// чтения (72 байта из 96) — тест фиксирует контракт против такого изменения.
///
/// Именно разбор по смещениям (а не `extern struct` + `@ptrCast`) даёт работу
/// на ЛЮБОЙ архитектуре без ошибок выравнивания (ARM64/RISC-V: нет SIGBUS).
pub const ObjectEntry = struct {
    digest: [32]u8,
    payload_offset: u64,
    uncompressed_size: u64,
    compressed_size: u64,
    type_id: u32,
    flags: u16,
    compression_codec: u8,
    scope_depth: u8,
    logical_path_offset: u32,
    schema_version: u32,

    /// Парсинг с проверкой Little-Endian и reserved-байтов (CONF-15).
    pub fn parseSafe(bytes: *const [96]u8) !ObjectEntry {
        // CONF-15: reserved-байты (72..95) обязаны быть строго нулевыми.
        // Иначе в них можно спрятать полезную нагрузку — стеганография.
        for (bytes[72..96]) |b| {
            if (b != 0) {
                cov.hit(.obj_bad_reserved);
                return KimgError.InvalidReservedBytes;
            }
        }

        var entry: ObjectEntry = undefined;
        std.mem.copyForwards(u8, &entry.digest, bytes[0..32]);
        entry.payload_offset = std.mem.readInt(u64, bytes[32..40], .little);
        entry.uncompressed_size = std.mem.readInt(u64, bytes[40..48], .little);
        entry.compressed_size = std.mem.readInt(u64, bytes[48..56], .little);
        entry.type_id = std.mem.readInt(u32, bytes[56..60], .little);
        entry.flags = std.mem.readInt(u16, bytes[60..62], .little);
        entry.compression_codec = bytes[62];
        entry.scope_depth = bytes[63];
        entry.logical_path_offset = std.mem.readInt(u32, bytes[64..68], .little);
        entry.schema_version = std.mem.readInt(u32, bytes[68..72], .little);

        cov.hit(.obj_ok);
        return entry;
    }

    /// Спецификация 6.4: Merkle Leaf из точных 96 байт записи.
    ///
    /// 🔴 ВНИМАНИЕ: спецификация называет алгоритм BLAKE3, но и Python-генератор,
    /// и этот код используют **SHA-256**. Замена на BLAKE3 ЛОМАЕТ совместимость
    /// (проверено: сквозная сверка падает). Алгоритм обязан быть зафиксирован
    /// ОДИН — сейчас это SHA-256.
    pub fn computeLeafHash(bytes: *const [96]u8, out_hash: *[32]u8) void {
        var hasher = std.crypto.hash.sha2.Sha256.init(.{});
        hasher.update(&[_]u8{0x00});
        hasher.update("KIMG-ENTRY-LEAF-V1\x00");
        hasher.update(bytes);
        hasher.final(out_hash);
    }

    /// Merkle-корень: H(0x00 || "KIMG-MERKLE-ROOT-V1\0" || leaf_0 || ... || leaf_{n-1}).
    ///
    /// Раньше `MerkleRootMismatch` был объявлен, но НИКОГДА не возвращался
    /// (см. README §6). Теперь корень пересчитывается и сверяется.
    pub fn computeRootHash(entries: []const [96]u8, out_hash: *[32]u8) void {
        var hasher = std.crypto.hash.sha2.Sha256.init(.{});
        hasher.update(&[_]u8{0x00});
        hasher.update("KIMG-MERKLE-ROOT-V1\x00");
        for (entries) |*e| {
            var leaf: [32]u8 = undefined;
            computeLeafHash(e, &leaf);
            hasher.update(&leaf);
        }
        hasher.final(out_hash);
    }
};

test "CONF-15: ObjectEntry разбирается и держит 96-байтную раскладку" {
    var raw_bytes = [_]u8{0} ** 96;
    raw_bytes[56] = 0x05; // type_id = claim
    raw_bytes[64] = 0xFF; // logical_path_offset = 0xFFFFFFFF
    raw_bytes[65] = 0xFF;
    raw_bytes[66] = 0xFF;
    raw_bytes[67] = 0xFF;

    const entry = try ObjectEntry.parseSafe(&raw_bytes);
    try std.testing.expectEqual(@as(u32, 5), entry.type_id);
    try std.testing.expectEqual(@as(u32, 0xFFFFFFFF), entry.logical_path_offset);
}

test "CONF-15: мусор в reserved-байтах отвергается" {
    var raw_bytes = [_]u8{0} ** 96;
    raw_bytes[95] = 0x01;
    try std.testing.expectError(KimgError.InvalidReservedBytes,
                               ObjectEntry.parseSafe(&raw_bytes));
}
