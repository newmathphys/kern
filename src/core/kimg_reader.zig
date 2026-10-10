const std = @import("std");

pub const KimgError = error{
    BadMagic,
    TooSmall,
    BadHeaderSize,
    TableOutOfBounds,
    PayloadOutOfBounds,
    /// Переполнение при сложении offset+size.
    ///
    /// БЕЗ безопасной арифметики `offset + size` переполняется и даёт МАЛОЕ
    /// число — тогда проверка границ проходит, и парсер принимает вредоносный
    /// образ. Именно эту атаку ловит тест SEC-01 (подтверждено в ReleaseFast:
    /// образ с offset = MAX_U64−10 ПРИНИМАЛСЯ).
    OutOfBoundsOffset,
};

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
    schema_version: u32,        // 20
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

    /// Безопасный разбор заголовка БЕЗ @ptrCast.
    ///
    /// `main.zig` вызывает именно этот метод: `KimgHeader.parse(&header_bytes, file_size)`.
    /// В спецификации метода не было — написан здесь. Проверяет magic, размер
    /// заголовка, границы таблицы объектов и payload БЕЗОПАСНОЙ арифметикой.
    pub fn parse(bytes: *const [128]u8, file_size: u64) !KimgHeader {
        if (!std.mem.eql(u8, bytes[0..8], "KIMG\r\n\x1a\n")) {
            return KimgError.BadMagic;
        }

        var h: KimgHeader = undefined;
        @memcpy(&h.magic, bytes[0..8]);
        h.version_major = std.mem.readInt(u16, bytes[8..10], .little);
        h.version_minor = std.mem.readInt(u16, bytes[10..12], .little);
        h.header_size = std.mem.readInt(u32, bytes[12..16], .little);
        h.flags = std.mem.readInt(u32, bytes[16..20], .little);
        h.schema_version = std.mem.readInt(u32, bytes[20..24], .little);
        h.block_size = std.mem.readInt(u64, bytes[24..32], .little);
        h.object_table_offset = std.mem.readInt(u64, bytes[32..40], .little);
        h.object_table_size = std.mem.readInt(u64, bytes[40..48], .little);
        h.object_count = std.mem.readInt(u64, bytes[48..56], .little);
        h.data_payload_offset = std.mem.readInt(u64, bytes[56..64], .little);
        @memcpy(&h.root_digest, bytes[64..96]);
        @memcpy(&h.header_checksum, bytes[96..128]);

        if (h.header_size != 128) return KimgError.BadHeaderSize;
        if (file_size < h.header_size) return KimgError.TooSmall;

        // БЕЗОПАСНАЯ АРИФМЕТИКА: ловим переполнение явно.
        const t_end = std.math.add(u64, h.object_table_offset,
                                  h.object_table_size) catch
            return KimgError.OutOfBoundsOffset;
        if (t_end > file_size) return KimgError.TableOutOfBounds;

        const p_end = std.math.add(u64, h.data_payload_offset,
                                   @as(u64, 0)) catch
            return KimgError.OutOfBoundsOffset;
        if (p_end > file_size) return KimgError.PayloadOutOfBounds;

        return h;
    }
};

test "KimgHeader.parse: валидный заголовок" {
    var b: [128]u8 = [_]u8{0} ** 128;
    @memcpy(b[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, b[8..10], 1, .little);
    std.mem.writeInt(u32, b[12..16], 128, .little);
    std.mem.writeInt(u64, b[32..40], 128, .little);
    std.mem.writeInt(u64, b[40..48], 96, .little);
    std.mem.writeInt(u64, b[48..56], 1, .little);
    std.mem.writeInt(u64, b[56..64], 224, .little);

    const h = try KimgHeader.parse(&b, 280);
    try std.testing.expectEqual(@as(u16, 1), h.version_major);
    try std.testing.expectEqual(@as(u64, 1), h.object_count);
}

test "KimgHeader.parse: битый magic отвергается" {
    var b: [128]u8 = [_]u8{0} ** 128;
    @memcpy(b[0..8], "XXXXXXXX");
    try std.testing.expectError(KimgError.BadMagic, KimgHeader.parse(&b, 280));
}

test "KimgHeader.parse: таблица за пределами файла отвергается" {
    var b: [128]u8 = [_]u8{0} ** 128;
    @memcpy(b[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u32, b[12..16], 128, .little);
    std.mem.writeInt(u64, b[32..40], 128, .little);
    std.mem.writeInt(u64, b[40..48], 96, .little);
    std.mem.writeInt(u64, b[48..56], 1, .little);
    std.mem.writeInt(u64, b[56..64], 224, .little);
    // file_size = 200 > 128, иначе сработал бы TooSmall, а не TableOutOfBounds
    try std.testing.expectError(KimgError.TableOutOfBounds, KimgHeader.parse(&b, 200));
}

test "KimgHeader.parse: слишком короткий файл отвергается" {
    var b: [128]u8 = [_]u8{0} ** 128;
    @memcpy(b[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u32, b[12..16], 128, .little);
    try std.testing.expectError(KimgError.TooSmall, KimgHeader.parse(&b, 100));
}

test "SEC-01: переполнение offset+size отвергается (не паника, не приём)" {
    var b: [128]u8 = [_]u8{0} ** 128;
    @memcpy(b[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u32, b[12..16], 128, .little);
    std.mem.writeInt(u64, b[32..40], std.math.maxInt(u64) - 10, .little);
    std.mem.writeInt(u64, b[40..48], 100, .little);
    try std.testing.expectError(KimgError.OutOfBoundsOffset,
                               KimgHeader.parse(&b, 1024));
}
