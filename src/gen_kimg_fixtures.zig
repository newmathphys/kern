// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! Генератор golden-фикстур для Ф3 (`tests/fixtures/*.kimg`).
//!
//! ЗАЧЕМ. Тесты в Zig проверяют парсер на массивах байтов, но CLI
//! (`kernc fsck / inspect / diff`) и внешний `conformance_check.py` работают
//! с ФАЙЛАМИ. Фикстуры собираются той же функцией `sealImageRoot`, что и
//! читатель, поэтому не могут «разойтись» с реализацией.
//!
//! Запуск:
//!   zig run --dep compat -Mroot=src/gen_kimg_fixtures.zig -Mcompat=src/compat.zig
//! Файлы идемпотентны: повторный запуск даёт те же байты.

const std = @import("std");
const compat = @import("compat");
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;

fn build(buf: []u8, flags: u32) !void {
    const content = "hello";
    const pool = "a.zig\x00" ++ content;
    @memset(buf, 0);

    var obj: [96]u8 = @as([96]u8, @splat(0));
    var dig: [32]u8 = undefined;
    std.crypto.hash.Blake3.hash(content, dig[0..32], .{});
    @memcpy(obj[0..32], &dig);
    std.mem.writeInt(u64, obj[32..40], 6, .little);
    std.mem.writeInt(u64, obj[40..48], content.len, .little);
    std.mem.writeInt(u64, obj[48..56], content.len, .little);
    std.mem.writeInt(u32, obj[56..60], 0x0002, .little);
    std.mem.writeInt(u16, obj[60..62], 0x0002, .little);
    std.mem.writeInt(u32, obj[64..68], 0, .little);
    std.mem.writeInt(u32, obj[68..72], 1, .little);

    @memcpy(buf[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, buf[8..10], 1, .little);
    std.mem.writeInt(u16, buf[10..12], 3, .little);
    std.mem.writeInt(u32, buf[12..16], 128, .little);
    std.mem.writeInt(u32, buf[16..20], flags, .little);
    std.mem.writeInt(u32, buf[20..24], 1, .little);
    std.mem.writeInt(u64, buf[24..32], 4096, .little);
    std.mem.writeInt(u64, buf[32..40], 128, .little);
    std.mem.writeInt(u64, buf[40..48], 96, .little);
    std.mem.writeInt(u64, buf[48..56], 1, .little);
    std.mem.writeInt(u64, buf[56..64], 224, .little);
    @memcpy(buf[128..224], &obj);
    @memcpy(buf[224..235], pool);
}

pub fn main(init: std.process.Init) !void {
    compat.setIo(init.io);
    try compat.makePath("tests/fixtures");

    var buf: [235]u8 = undefined;

    // 1) ВАЛИДНЫЙ образ с НЕИЗВЕСТНЫМ optional-флагом: должен читаться.
    try build(&buf, 0x0000_0002);
    try KimgHeader.sealImageRoot(&buf);
    try compat.writeFile("tests/fixtures/kimg_unknown_optional.kimg", &buf);

    // 2) Неизвестный REQUIRED-флаг: обязан быть отвергнут.
    //    Запечатываем ВАЛИДНЫЙ образ (иначе `sealImageRoot` сам откажется —
    //    он парсит заголовок), затем ставим REQUIRED-бит: парсер обязан
    //    упасть на флагах РАНЬШЕ, чем дойдёт до Merkle-корня.
    try build(&buf, 0);
    try KimgHeader.sealImageRoot(&buf);
    std.mem.writeInt(u32, buf[16..20], 0x0001_0000, .little);
    try compat.writeFile("tests/fixtures/kimg_unknown_required.kimg", &buf);

    // 3) Big-endian версия: те же байты, другая последовательность.
    try build(&buf, 0);
    try KimgHeader.sealImageRoot(&buf);
    std.mem.writeInt(u16, buf[8..10], 1, .big);
    try compat.writeFile("tests/fixtures/kimg_big_endian.kimg", &buf);

    std.debug.print("[OK] 3 фикстуры -> tests/fixtures/\n", .{});
}
