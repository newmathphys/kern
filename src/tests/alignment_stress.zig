// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ЭШЕЛОН 1 — СТРЕСС СТРОГОГО ВЫРАВНИВАНИЯ (Cross-Platform Alignment).
//!
//! Проблема: на x86_64 невыровненный доступ к памяти «молча прощается»
//! (ценой падения скорости), а на ARM64/RISC-V он даёт аппаратный SIGBUS.
//! Zero-copy движок .kimg обязан читать образ ОДИНАКОВО на всех архитектурах.
//!
//! ДОКАЗЫВАЕМ ТРИ СВОЙСТВА:
//!   1) COMPTIME: раскладка структур зафиксирована (размер/смещения/alignment);
//!   2) RUNTIME:  разбор работает при ЛЮБОМ смещении указателя (0,1,2,3,5,7);
//!   3) ENDIAN:   многобайтные поля читаются строго Little-Endian.

const std = @import("std");
const kimg = @import("../core/kimg_reader.zig");
const obj = @import("../core/object_entry.zig");

// =====================================================================
// 1. COMPTIME-ГАРАНТИИ РАСКЛАДКИ
// =====================================================================

test "ALIGN comptime: заголовок .kimg — ровно 128 байт, выравнивание 8" {
    try std.testing.expectEqual(@as(usize, 128), @sizeOf(kimg.KimgHeader));
    try std.testing.expectEqual(@as(usize, 8), @alignOf(kimg.KimgHeader));
    try std.testing.expectEqual(@as(usize, 0), @offsetOf(kimg.KimgHeader, "magic"));
    try std.testing.expectEqual(@as(usize, 24), @offsetOf(kimg.KimgHeader, "block_size"));
    try std.testing.expectEqual(@as(usize, 32), @offsetOf(kimg.KimgHeader, "object_table_offset"));
    try std.testing.expectEqual(@as(usize, 48), @offsetOf(kimg.KimgHeader, "object_count"));
    try std.testing.expectEqual(@as(usize, 64), @offsetOf(kimg.KimgHeader, "root_digest"));
    try std.testing.expectEqual(@as(usize, 96), @offsetOf(kimg.KimgHeader, "header_checksum"));
}

test "ALIGN comptime: записи таблицы читаются как [96]u8 (alignment = 1)" {
    // Именно alignment == 1 делает @ptrCast(file + start) БЕЗОПАСНЫМ
    // на любой архитектуре: требование выравнивания тривиально выполнимо.
    try std.testing.expectEqual(@as(usize, 1), @alignOf([96]u8));
    try std.testing.expectEqual(@as(usize, 96), @sizeOf([96]u8));
}

test "ALIGN comptime: ObjectEntry — ЛОГИЧЕСКАЯ структура (72 байта), НЕ раскладка диска" {
    // 🔴 НАЙДЕНО ЭТИМ ТЕСТОМ: комментарий в object_entry.zig утверждал
    // «строго 96 байт», но @sizeOf(ObjectEntry) == 72 (24 байта — reserved
    // на диске, в структуру не входят). Структура разбирается через
    // std.mem.readInt по СМЕЩЕНИЯМ, а не через @ptrCast — поэтому 72 vs 96
    // безопасно. Но если кто-то однажды сделает @ptrCast к ObjectEntry,
    // это станет переполнением чтения. Тест фиксирует контракт.
    try std.testing.expectEqual(@as(usize, 72), @sizeOf(obj.ObjectEntry));
    try std.testing.expectEqual(@as(usize, 8), @alignOf(obj.ObjectEntry));
    // Размер на диске (96) БОЛЬШЕ размера структуры (72) — за счёт reserved.
    try std.testing.expect(@sizeOf([96]u8) > @sizeOf(obj.ObjectEntry));
}

// =====================================================================
// 2. RUNTIME: разбор при ЛЮБОМ смещении
// =====================================================================

/// Строит корректный 128-байтный заголовок .kimg.
fn makeHeader() [128]u8 {
    var b: [128]u8 = @as([128]u8, @splat(0));
    @memcpy(b[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, b[8..10], 1, .little);   // version_major
    std.mem.writeInt(u32, b[20..24], 2, .little); // hash_algo = SHA-256
    std.mem.writeInt(u16, b[10..12], 3, .little);  // version_minor
    std.mem.writeInt(u32, b[12..16], 128, .little); // header_size
    std.mem.writeInt(u64, b[24..32], 4096, .little); // block_size
    std.mem.writeInt(u64, b[32..40], 128, .little); // table_offset
    std.mem.writeInt(u64, b[40..48], 96, .little);  // table_size
    std.mem.writeInt(u64, b[48..56], 1, .little);   // object_count
    std.mem.writeInt(u64, b[56..64], 224, .little); // payload_offset
    return b;
}

/// Разбирает заголовок, лежащий по НЕвыровненному адресу `shift`.
fn parseAtShift(shift: usize) !kimg.KimgHeader {
    var buf: [128 + 16]u8 = @as([(128 + 16)]u8, @splat(0));
    const hdr = makeHeader();
    @memcpy(buf[shift .. shift + 128], &hdr);
    const p: *const [128]u8 = @ptrCast(buf[shift .. shift + 128].ptr);
    return kimg.KimgHeader.parse(p, 4096);
}

test "ALIGN runtime: разбор при смещениях 0..7 — одинаковый результат" {
    var s: usize = 0;
    while (s <= 7) : (s += 1) {
        const h = try parseAtShift(s);
        try std.testing.expectEqual(@as(u16, 1), h.version_major);
        try std.testing.expectEqual(@as(u16, 3), h.version_minor);
        try std.testing.expectEqual(@as(u32, 128), h.header_size);
        try std.testing.expectEqual(@as(u64, 4096), h.block_size);
        try std.testing.expectEqual(@as(u64, 128), h.object_table_offset);
        try std.testing.expectEqual(@as(u64, 1), h.object_count);
        try std.testing.expectEqual(@as(u64, 224), h.data_payload_offset);
    }
}

test "ALIGN runtime: записи таблицы читаются при смещениях 1,2,3,5,7" {
    var entry_bytes: [96]u8 = @as([96]u8, @splat(0));
    std.mem.writeInt(u64, entry_bytes[32..40], 0x1122334455667788, .little);
    std.mem.writeInt(u32, entry_bytes[56..60], 5, .little);      // type_id
    std.mem.writeInt(u16, entry_bytes[60..62], 0x0003, .little); // flags
    entry_bytes[62] = 1; // compression_codec

    var buf: [96 + 16]u8 = @as([(96 + 16)]u8, @splat(0));
    for ([_]usize{ 1, 2, 3, 5, 7 }) |shift| {
        @memset(&buf, 0);
        @memcpy(buf[shift .. shift + 96], &entry_bytes);
        const p: *const [96]u8 = @ptrCast(buf[shift .. shift + 96].ptr);
        const e = try obj.ObjectEntry.parseSafe(p);
        try std.testing.expectEqual(@as(u64, 0x1122334455667788), e.payload_offset);
        try std.testing.expectEqual(@as(u32, 5), e.type_id);
        try std.testing.expectEqual(@as(u16, 3), e.flags);
        try std.testing.expectEqual(@as(u8, 1), e.compression_codec);
    }
}

test "ALIGN runtime: невыровненная таблица НЕ ломает Merkle (полный образ)" {
    // Собираем образ со СМЕЩЁННОЙ таблицей объектов (offset = 129, не кратно 8)
    // и проверяем, что Merkle-корень всё равно сходится.
    const table_off: u64 = 129;
    var file: [129 + 96]u8 = @as([(129 + 96)]u8, @splat(0));

    var entry: [96]u8 = @as([96]u8, @splat(0));
    std.mem.writeInt(u64, entry[32..40], 225, .little);
    std.mem.writeInt(u64, entry[40..48], 4, .little);
    std.mem.writeInt(u64, entry[48..56], 4, .little);
    std.mem.writeInt(u32, entry[56..60], 1, .little);
    @memcpy(file[table_off .. table_off + 96], &entry);

    var hdr = makeHeader();
    std.mem.writeInt(u64, hdr[32..40], table_off, .little);
    @memcpy(file[0..128], &hdr);

    var root: [32]u8 = undefined;
    obj.ObjectEntry.computeRootHash(&[_][96]u8{entry}, &root);
    std.mem.writeInt(u64, hdr[32..40], table_off, .little);
    @memcpy(hdr[64..96], &root);
    @memcpy(file[0..128], &hdr);

    const hp: *const [128]u8 = @ptrCast(file[0..128].ptr);
    const h = try kimg.KimgHeader.parse(hp, file.len);
    try std.testing.expectEqual(table_off, h.object_table_offset);
    // Невыровненная таблица (129 % 8 == 1) — Merkle всё равно сходится.
    try kimg.KimgHeader.verifyMerkleRoot(&file, h);
}

// =====================================================================
// 3. ENDIANNESS: строгий Little-Endian независимо от платформы
// =====================================================================

test "ENDIAN: многобайтные поля читаются Little-Endian" {
    var b: [128]u8 = undefined;
    kimg.KimgHeader.fillValid(&b, 128, 0, 0, 128);
    // Перезаписываем block_size специальным образцом для проверки LE.
    std.mem.writeInt(u64, b[24..32], 0x0102030405060708, .little);

    // Проверяем, что байты в файле лежат именно в LE-порядке
    try std.testing.expectEqual(@as(u8, 0x08), b[24]);
    try std.testing.expectEqual(@as(u8, 0x01), b[31]);

    const p: *const [128]u8 = @ptrCast(b[0..128].ptr);
    const h = try kimg.KimgHeader.parse(p, 4096);
    try std.testing.expectEqual(@as(u64, 0x0102030405060708), h.block_size);
}

// =====================================================================
// 4. Помощник строгой проверки выравнивания (для конформности спецификации)
// =====================================================================

/// Строгая проверка: таблица объектов обязана начинаться с 8-байтной границы.
/// KERN работает и без этого (см. тесты выше), но спецификация v1.3 требует
/// выравнивания для максимальной скорости на ARM64/RISC-V.
/// Возвращает true, если образ соответствует строгому требованию.
pub fn isStrictlyAligned(h: kimg.KimgHeader) bool {
    return h.object_table_offset % 8 == 0 and h.data_payload_offset % 8 == 0;
}

test "ALIGN strict: isStrictlyAligned различает выровненные и нет" {
    var b = makeHeader();
    std.mem.writeInt(u64, b[32..40], 128, .little);
    std.mem.writeInt(u64, b[56..64], 224, .little);
    const p: *const [128]u8 = @ptrCast(b[0..128].ptr);
    var h = try kimg.KimgHeader.parse(p, 4096);
    try std.testing.expect(isStrictlyAligned(h));

    h.object_table_offset = 129;
    try std.testing.expect(!isStrictlyAligned(h));

    h.object_table_offset = 128;
    h.data_payload_offset = 226;
    try std.testing.expect(!isStrictlyAligned(h));
}
