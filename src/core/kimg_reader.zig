// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

const std = @import("std");
const cov = @import("../cov.zig");
const ObjectEntry = @import("object_entry.zig").ObjectEntry;
const HashAlgo = @import("hash_algo.zig").HashAlgo;

pub const KimgError = error{
    BadMagic,
    TooSmall,
    BadHeaderSize,
    /// 🔴 ДЕФЕКТ (найден сверкой со спецификацией, ИСПРАВЛЕН): спека требует
    /// `if (header.major != 1) return UnsupportedVersion;`. Наш парсер читал
    /// версию, но НЕ проверял её — образ другой мажорной версии (иной
    /// расклад) разбирался по правилам v1 МОЛЧА.
    UnsupportedVersion,
    /// 🔴 ДЕФЕКТ (найден сверкой со спецификацией, ИСПРАВЛЕН): спека требует
    /// `if (hash_algo != 1 and hash_algo != 2) return InvalidHashAlgo;`.
    /// Без этой проверки образ с произвольным алгоритмом хэша принимался, и
    /// диагностика была ЛОЖНОЙ («Merkle не совпал» вместо «алгоритм не тот»).
    InvalidHashAlgo,
    TableOutOfBounds,
    PayloadOutOfBounds,
    /// Переполнение при сложении offset+size.
    ///
    /// БЕЗ безопасной арифметики `offset + size` переполняется и даёт МАЛОЕ
    /// число — тогда проверка границ проходит, и парсер принимает вредоносный
    /// образ. Именно эту атаку ловит тест SEC-01 (подтверждено в ReleaseFast:
    /// образ с offset = MAX_U64−10 ПРИНИМАЛСЯ).
    OutOfBoundsOffset,
    /// Пересчитанный Merkle-корень не совпал с `root_digest` заголовка.
    /// Раньше был объявлен, но НИКОГДА не возвращался (README §6).
    MerkleRootMismatch,
    /// Ф3: образ требует расширения, которого этот парсер не знает.
    /// Неизвестные OPTIONAL-биты ПРОПУСКАЮТСЯ, неизвестные REQUIRED — отказ:
    /// иначе новый образ молча разбирается по старым правилам.
    UnsupportedRequiredFeature,
    /// Ф3: magic совпал, но версия прочиталась как `0x0100` — файл записан
    /// в big-endian. Разбирать его как little-endian нельзя: все поля `u32+`
    /// окажутся мусором.
    WrongEndianness,
};

/// Маски флагов (Ф3). Младшие 16 бит — OPTIONAL (неизвестные игнорируются),
/// старшие 16 — REQUIRED (неизвестные означают отказ).
pub const FLAG_OPTIONAL_MASK: u32 = 0x0000_FFFF;
pub const FLAG_REQUIRED_MASK: u32 = 0xFFFF_0000;
/// Известные OPTIONAL-биты: 0x0001 = payload deflate.
pub const FLAG_KNOWN_OPTIONAL: u32 = 0x0000_0001;
/// Известные REQUIRED-биты: пока ни одного.
pub const FLAG_KNOWN_REQUIRED: u32 = 0x0000_0000;

/// 128-байтный заголовок образа KIMG v1.2.
///
/// Раскладка обязана совпасть с упаковкой Python-билдера БАЙТ В БАЙТ:
///   "<8s H H I I I Q Q Q Q Q 32s 32s"
/// (последние 32 байта в v1.2 используются как чексумма заголовка).
pub const KimgHeader = extern struct {
    magic: [8]u8,               // 0   : "KIMG\r\n\x1a\n"
    version_major: u16,         // 8
    version_minor: u16,         // 10
    header_size: u32,           // 12
    flags: u32,                 // 16
    /// ИМЯ ПО СПЕЦИФИКАЦИИ: `hash_algo` (1 = BLAKE3-256, 2 = SHA-256).
    /// Ранее поле ошибочно называлось `schema_version` — значения совпадали,
    /// но имя расходилось со спецификацией.
    hash_algo: u32,             // 20
    block_size: u64,            // 24
    object_table_offset: u64,   // 32
    object_table_size: u64,     // 40
    object_count: u64,          // 48
    data_payload_offset: u64,   // 56
    root_digest: [32]u8,        // 64
    header_checksum: [32]u8,    // 96

    comptime {
        std.debug.assert(@sizeOf(KimgHeader) == 128);
        std.debug.assert(@offsetOf(KimgHeader, "object_table_offset") == 32);
        std.debug.assert(@offsetOf(KimgHeader, "object_count") == 48);
        std.debug.assert(@offsetOf(KimgHeader, "data_payload_offset") == 56);
    }

    /// Заполняет 128-байтный заголовок ВАЛИДНЫМИ значениями.
    ///
    /// ЗАЧЕМ: раньше каждый тест/генератор собирал заголовок вручную и
    /// забывал то версию, то `hash_algo` — после добавления проверок из
    /// спецификации 18 тестов упали. Единый помощник исключает дрейф.
    /// Тест, который хочет испортить поле, перезаписывает его ПОСЛЕ вызова.
    pub fn fillValid(h: *[128]u8, table_off: u64, table_len: u64, count: u64, payload_off: u64) void {
        @memset(h, 0);
        @memcpy(h[0..8], "KIMG\r\n\x1a\n");
        std.mem.writeInt(u16, h[8..10], 1, .little); // version_major = 1
        std.mem.writeInt(u16, h[10..12], 3, .little); // version_minor = 3
        std.mem.writeInt(u32, h[12..16], 128, .little); // header_size
        std.mem.writeInt(u32, h[16..20], 0, .little); // flags
        std.mem.writeInt(u32, h[20..24], 1, .little); // hash_algo = 1 = BLAKE3-256 (HashAlgo.fromInt(1) == .blake3)
        std.mem.writeInt(u64, h[24..32], 4096, .little); // block_size
        std.mem.writeInt(u64, h[32..40], table_off, .little);
        std.mem.writeInt(u64, h[40..48], table_len, .little);
        std.mem.writeInt(u64, h[48..56], count, .little);
        std.mem.writeInt(u64, h[56..64], payload_off, .little);
    }

    /// Безопасный разбор заголовка БЕЗ @ptrCast.
    ///
    /// `main.zig` вызывает именно этот метод: `KimgHeader.parse(&header_bytes, file_size)`.
    /// В спецификации метода не было — написан здесь. Проверяет magic, размер
    /// заголовка, границы таблицы объектов и payload БЕЗОПАСНОЙ арифметикой.
    pub fn parse(bytes: *const [128]u8, file_size: u64) !KimgHeader {
        if (!std.mem.eql(u8, bytes[0..8], "KIMG\r\n\x1a\n")) {
            cov.hit(.hdr_bad_magic);
            return KimgError.BadMagic;
        }

        var h: KimgHeader = undefined;
        @memcpy(&h.magic, bytes[0..8]);
        h.version_major = std.mem.readInt(u16, bytes[8..10], .little);
        h.version_minor = std.mem.readInt(u16, bytes[10..12], .little);
        h.header_size = std.mem.readInt(u32, bytes[12..16], .little);
        h.flags = std.mem.readInt(u32, bytes[16..20], .little);
        h.hash_algo = std.mem.readInt(u32, bytes[20..24], .little);
        h.block_size = std.mem.readInt(u64, bytes[24..32], .little);
        h.object_table_offset = std.mem.readInt(u64, bytes[32..40], .little);
        h.object_table_size = std.mem.readInt(u64, bytes[40..48], .little);
        h.object_count = std.mem.readInt(u64, bytes[48..56], .little);
        h.data_payload_offset = std.mem.readInt(u64, bytes[56..64], .little);
        @memcpy(&h.root_digest, bytes[64..96]);
        @memcpy(&h.header_checksum, bytes[96..128]);

        // СПЕКА (KimgHeader.parse): версия и алгоритм хэша ОБЯЗАНЫ проверяться.
        // Без этого образ чужой мажорной версии (иной расклад) или с иным
        // алгоритмом хэша разбирался по правилам v1 МОЛЧА.
        if (h.version_major != 1) {
            // Ф3: отличаем «чужая версия» от «файл записан big-endian».
            // Если те же два байта, прочитанные как BE, дают 1 — это не
            // другая версия, а другая ПОСЛЕДОВАТЕЛЬНОСТЬ БАЙТ.
            const as_be = std.mem.readInt(u16, bytes[8..10], .big);
            if (as_be == 1) return KimgError.WrongEndianness;
            return KimgError.UnsupportedVersion;
        }
        if (h.hash_algo != 1 and h.hash_algo != 2) return KimgError.InvalidHashAlgo;
        // Ф3: политика неизвестных флагов.
        //   unknown OPTIONAL -> пропустить (совместимость вперёд);
        //   unknown REQUIRED -> отказ (иначе расклад прочитан неверно).
        _ = FLAG_OPTIONAL_MASK;
        _ = FLAG_KNOWN_OPTIONAL;
        const unknown_required = h.flags & FLAG_REQUIRED_MASK & ~FLAG_KNOWN_REQUIRED;
        if (unknown_required != 0) return KimgError.UnsupportedRequiredFeature;

        if (h.header_size != 128) {
            cov.hit(.hdr_bad_size);
            return KimgError.BadHeaderSize;
        }
        if (file_size < h.header_size) {
            cov.hit(.hdr_too_small);
            return KimgError.TooSmall;
        }

        // БЕЗОПАСНАЯ АРИФМЕТИКА: ловим переполнение явно.
        const t_end = std.math.add(u64, h.object_table_offset,
                                  h.object_table_size) catch
            return KimgError.OutOfBoundsOffset;
        if (t_end > file_size) {
            cov.hit(.hdr_table_oob);
            return KimgError.TableOutOfBounds;
        }

        const p_end = std.math.add(u64, h.data_payload_offset,
                                   @as(u64, 0)) catch
            return KimgError.OutOfBoundsOffset;
        if (p_end > file_size) {
            cov.hit(.hdr_payload_oob);
            return KimgError.PayloadOutOfBounds;
        }

        cov.hit(.hdr_ok);
        return h;
    }

    /// Пересчёт Merkle-корня по таблице объектов и сверка с `root_digest`.
    /// Возвращает `MerkleRootMismatch` при несовпадении.
    ///
    /// Раньше `MerkleRootMismatch` был объявлен, но НИКОГДА не возвращался
    /// (README §6). Теперь целостность действительно проверяется.
    /// Merkle-корень образа для КОНКРЕТНОГО алгоритма (comptime-диспетчеризация).
    fn merkleRootImpl(comptime algo: HashAlgo, file_bytes: []const u8, h: KimgHeader) !([32]u8) {
        var hasher = switch (algo) {
            .blake3 => std.crypto.hash.Blake3.init(.{}),
            .sha256 => std.crypto.hash.sha2.Sha256.init(.{}),
        };
        hasher.update(&[_]u8{0x00});
        hasher.update("KIMG-MERKLE-ROOT-V2\x00");
        var i: u64 = 0;
        while (i < h.object_count) : (i += 1) {
            const delta = std.math.mul(u64, i, 96) catch return KimgError.OutOfBoundsOffset;
            const start = std.math.add(u64, h.object_table_offset, delta) catch return KimgError.OutOfBoundsOffset;
            const end = std.math.add(u64, start, 96) catch return KimgError.OutOfBoundsOffset;
            if (end > file_bytes.len) return KimgError.TableOutOfBounds;
            const entry: *const [96]u8 = @ptrCast(file_bytes.ptr + start);
            var leaf: [32]u8 = undefined;
            ObjectEntry.computeLeafHashAlgo(entry, &leaf, algo);
            hasher.update(&leaf);
            // ДЕФЕКТ #128: ИМЯ объекта входит в корень. Формат НЕ меняется
            // (Header 128, ObjectEntry 96): байты имени берутся из пула строк
            // по `logical_path_offset`. Благодаря ЕДИНОЙ функции
            // (`computeImageMerkleRoot`) писатель и читатель считают корень
            // одним кодом по одним байтам.
            hasher.update(&[_]u8{0x01});
            const path_off = std.mem.readInt(u32, entry[64..68], .little);
            const flags = std.mem.readInt(u16, entry[60..62], .little);
            // ВАЖНО: `path_off == 0` — ВАЛИДНОЕ смещение (первая строка пула)!
            // «Нет пути» определяется флагом 0x0002 и сентинелом 0xFFFFFFFF
            // (та же логика, что в `hasPath`). Первая версия пропускала
            // объект с offset 0 — и подмена буквы в ЕГО имени не ловилась.
            if ((flags & 0x0002) != 0 and path_off != 0xFFFFFFFF) {
                const nm_abs = std.math.add(u64, h.data_payload_offset, path_off) catch
                    return KimgError.OutOfBoundsOffset;
                if (nm_abs < file_bytes.len) {
                    const s: usize = @intCast(nm_abs);
                    var j: usize = s;
                    while (j < file_bytes.len and file_bytes[j] != 0 and (j - s) < 512) j += 1;
                    hasher.update(file_bytes[s..j]);
                }
            }
        }
        var root: [32]u8 = undefined;
        hasher.final(&root);
        return root;
    }

    /// ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ (дефект #128): корень по УЖЕ СОБРАННОМУ образу.
    ///
    /// Эту функцию обязан вызывать и ПИСАТЕЛЬ (после того как весь буфер
    /// разложен), и ЧИТАТЕЛЬ при проверке. Тогда они выполняют ОДИН код над
    /// ОДНИМИ байтами, и расхождение корней невозможно по построению.
    pub fn computeImageMerkleRoot(image_bytes: []const u8) ![32]u8 {
        if (image_bytes.len < 128) return KimgError.TableOutOfBounds;
        var hb: [128]u8 = undefined;
        @memcpy(&hb, image_bytes[0..128]);
        const h = KimgHeader.parse(&hb, image_bytes.len) catch
            return KimgError.TableOutOfBounds;
        const algo = HashAlgo.fromInt(h.hash_algo) orelse return KimgError.InvalidHashAlgo;
        return switch (algo) {
            inline else => |a| merkleRootImpl(a, image_bytes, h),
        };
    }

    /// ЗАПЕЧАТАТЬ КОРЕНЬ в ГОТОВОМ буфере: вычислить по буферу и записать
    /// в заголовок (root + контрольная сумма). ЕДИНЫЙ путь для писателя и для
    /// тестов, собирающих образ вручную (дефект #128: раньше тесты считали
    /// корень СТАРОЙ формулой и расходились с читателем).
    pub fn sealImageRoot(image_bytes: []u8) !void {
        if (image_bytes.len < 128) return KimgError.TableOutOfBounds;
        const root = try computeImageMerkleRoot(image_bytes);
        @memcpy(image_bytes[64..96], &root);
        const algo = HashAlgo.fromInt(std.mem.readInt(u32, image_bytes[20..24], .little)) orelse
            return KimgError.InvalidHashAlgo;
        var csum: [32]u8 = undefined;
        algo.hash(image_bytes[0..96], &csum);
        @memcpy(image_bytes[96..128], &csum);
    }

    pub fn verifyMerkleRoot(file_bytes: []const u8, h: KimgHeader) !void {
        // ЗАЩИТА: object_count не может превышать размер таблицы / 96.
        // Иначе `i * 96` переполняется, а цикл превращается в DoS.
        if (h.object_count > h.object_table_size / 96) {
            cov.hit(.merkle_count_guard);
            return KimgError.TableOutOfBounds;
        }

        // ДИСПЕТЧЕРИЗАЦИЯ: алгоритм берём из ЗАГОЛОВКА образа. Так образы на
        // SHA-256 (0x0002) читаются без изменений, а новые (BLAKE3, 0x0001) —
        // своим алгоритмом. `inline else`: типы хешеров разные.
        const algo = HashAlgo.fromInt(h.hash_algo) orelse return KimgError.InvalidHashAlgo;
        const root = switch (algo) {
            inline else => |a| try merkleRootImpl(a, file_bytes, h),
        };
        // КОНСТАНТНО-ВРЕМЕННАЯ СВЕРКА (УЛУЧШЕНИЕ №5, FIPS 140-3).
        // Обычный `std.mem.eql` выходит на ПЕРВОМ несовпавшем байте, поэтому
        // время сравнения выдаёт число совпавших байт — это Timing
        // Side-Channel: подбирая дайджест побайтово, атакующий получает
        // оракул. `timing_safe.eql` сравнивает ВСЕ 32 байта всегда.
        if (!std.crypto.timing_safe.eql([32]u8, root, h.root_digest)) {
            cov.hit(.merkle_mismatch);
            return KimgError.MerkleRootMismatch;
        }
        cov.hit(.merkle_ok);
    }
};

test "KimgHeader.parse: валидный заголовок" {
    var b: [128]u8 = @as([128]u8, @splat(0));
    @memcpy(b[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, b[8..10], 1, .little);
    std.mem.writeInt(u32, b[20..24], 1, .little); // hash_algo = SHA-256
    std.mem.writeInt(u32, b[12..16], 128, .little);
    std.mem.writeInt(u64, b[32..40], 128, .little);
    std.mem.writeInt(u64, b[40..48], 96, .little);
    std.mem.writeInt(u64, b[48..56], 1, .little);
    std.mem.writeInt(u64, b[56..64], 224, .little);

    const h = try KimgHeader.parse(&b, 280);
    try std.testing.expectEqual(@as(u16, 1), h.version_major);
    try std.testing.expectEqual(@as(u64, 1), h.object_count);
}

test "🔴 СПЕКА: мажорная версия != 1 отвергается (UnsupportedVersion)" {
    // Спека: `if (header.major != 1) return UnsupportedVersion;`
    // ДЕФЕКТ (был): версия читалась, но НЕ проверялась — образ иной
    // мажорной версии (другой расклад) разбирался по правилам v1 МОЛЧА.
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 0, 0, 128);

    std.mem.writeInt(u16, b[8..10], 2, .little); // major = 2
    try std.testing.expectError(KimgError.UnsupportedVersion, KimgHeader.parse(&b, 512));

    std.mem.writeInt(u16, b[8..10], 0, .little); // major = 0
    try std.testing.expectError(KimgError.UnsupportedVersion, KimgHeader.parse(&b, 512));

    // minor НЕ проверяется (совместимость внутри мажорной версии)
    std.mem.writeInt(u16, b[8..10], 1, .little);
    std.mem.writeInt(u16, b[10..12], 99, .little); // minor = 99
    _ = try KimgHeader.parse(&b, 512);
}

test "🔴 СПЕКА: hash_algo вне {1,2} отвергается (InvalidHashAlgo)" {
    // Спека: `if (hash_algo != 1 and hash_algo != 2) return InvalidHashAlgo;`
    // ДЕФЕКТ (был): поле не проверялось -> образ с произвольным алгоритмом
    // принимался, а диагностика была ЛОЖНОЙ («Merkle не совпал» вместо
    // «алгоритм не тот»).
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 0, 0, 128);

    std.mem.writeInt(u32, b[20..24], 0, .little);
    try std.testing.expectError(KimgError.InvalidHashAlgo, KimgHeader.parse(&b, 512));

    std.mem.writeInt(u32, b[20..24], 3, .little);
    try std.testing.expectError(KimgError.InvalidHashAlgo, KimgHeader.parse(&b, 512));

    std.mem.writeInt(u32, b[20..24], std.math.maxInt(u32), .little);
    try std.testing.expectError(KimgError.InvalidHashAlgo, KimgHeader.parse(&b, 512));

    // Оба разрешённых значения проходят.
    std.mem.writeInt(u32, b[20..24], 1, .little); // BLAKE3
    _ = try KimgHeader.parse(&b, 512);
    std.mem.writeInt(u32, b[20..24], 1, .little); // SHA-256
    _ = try KimgHeader.parse(&b, 512);
}

test "KimgHeader.parse: битый magic отвергается" {
    var b: [128]u8 = @as([128]u8, @splat(0));
    @memcpy(b[0..8], "XXXXXXXX");
    try std.testing.expectError(KimgError.BadMagic, KimgHeader.parse(&b, 280));
}

test "KimgHeader.parse: таблица за пределами файла отвергается" {
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 96, 1, 224);
    // file_size = 200 > 128, иначе сработал бы TooSmall, а не TableOutOfBounds
    try std.testing.expectError(KimgError.TableOutOfBounds, KimgHeader.parse(&b, 200));
}

test "KimgHeader.parse: слишком короткий файл отвергается" {
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 0, 0, 128);
    try std.testing.expectError(KimgError.TooSmall, KimgHeader.parse(&b, 100));
}

test "SEC-01: переполнение offset+size отвергается (не паника, не приём)" {
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, std.math.maxInt(u64) - 10, 100, 0, 0);
    try std.testing.expectError(KimgError.OutOfBoundsOffset,
                               KimgHeader.parse(&b, 1024));
}

test "MERKLE: пересчёт корня совпадает и ловит подмену" {
    var obj: [96]u8 = @as([96]u8, @splat(0));
    obj[56] = 0x02; // type_id = Source

    var b: [128]u8 = @as([128]u8, @splat(0));
    @memcpy(b[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, b[8..10], 1, .little);
    std.mem.writeInt(u32, b[20..24], 1, .little); // hash_algo = SHA-256
    std.mem.writeInt(u32, b[12..16], 128, .little);
    std.mem.writeInt(u64, b[32..40], 128, .little);
    std.mem.writeInt(u64, b[40..48], 96, .little);
    std.mem.writeInt(u64, b[48..56], 1, .little);
    std.mem.writeInt(u64, b[56..64], 224, .little);
    var file: [128 + 96]u8 = undefined;
    @memcpy(file[0..128], &b);
    @memcpy(file[128..224], &obj);
    // Корень считается по ГОТОВОМУ буферу (дефект #128).
    try KimgHeader.sealImageRoot(&file);

    const h = try KimgHeader.parse(file[0..128], file.len);
    try KimgHeader.verifyMerkleRoot(&file, h); // корень совпадает

    file[128 + 56] = 0x05; // подмена type_id в таблице
    try std.testing.expectError(KimgError.MerkleRootMismatch,
        KimgHeader.verifyMerkleRoot(&file, h));
}

test "SEC: гигантский object_count не вешает парсер (DoS-защита)" {
    // Таблица заявляет 96 байт (1 объект), но count = 1e9 -> раньше цикл
    // крутился бы вечность, а i*96 переполнялся.
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 96, 1_000_000_000, 224); // ЛОЖНЫЙ count

    const h = try KimgHeader.parse(&b, 320);
    var file: [320]u8 = @as([320]u8, @splat(0));
    @memcpy(file[0..128], &b);
    try std.testing.expectError(KimgError.TableOutOfBounds,
        KimgHeader.verifyMerkleRoot(&file, h));
}

test "KimgHeader.parse: неверный размер заголовка отвергается (BadHeaderSize)" {
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 0, 0, 128);
    std.mem.writeInt(u32, b[12..16], 256, .little); // header_size != 128
    try std.testing.expectError(KimgError.BadHeaderSize, KimgHeader.parse(&b, 512));
}

test "KimgHeader.parse: payload за границей файла отвергается (PayloadOutOfBounds)" {
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 0, 0, 9999); // payload ЗА файлом
    try std.testing.expectError(KimgError.PayloadOutOfBounds, KimgHeader.parse(&b, 256));
}

test "Ф3: неизвестный REQUIRED-флаг отвергается" {
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 0, 0, 128);
    std.mem.writeInt(u32, b[16..20], 0x0001_0000, .little); // старшие 16 = required
    try std.testing.expectError(KimgError.UnsupportedRequiredFeature,
        KimgHeader.parse(&b, 512));
}

test "Ф3: неизвестный OPTIONAL-флаг пропускается (совместимость вперёд)" {
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 0, 0, 128);
    std.mem.writeInt(u32, b[16..20], 0x0000_0002, .little); // младшие 16 = optional
    _ = try KimgHeader.parse(&b, 512); // не должно быть отказа
}

test "Ф3: big-endian образ -> WrongEndianness, а не «другая версия»" {
    var b: [128]u8 = undefined;
    KimgHeader.fillValid(&b, 128, 0, 0, 128);
    std.mem.writeInt(u16, b[8..10], 1, .big); // те же «1», но в BE
    try std.testing.expectError(KimgError.WrongEndianness, KimgHeader.parse(&b, 512));
}
