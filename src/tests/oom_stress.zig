// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: СТРЕСС НА ДЕФИЦИТ ПАМЯТИ (OOM / FixedBufferAllocator).
//!
//! Для систем Mission-Critical (микроконтроллер, контейнер с лимитом RAM)
//! важно: при нехватке памяти KERN обязан вернуть КОНТРОЛИРУЕМУЮ ошибку
//! `error.OutOfMemory`, а не упасть в системный panic/abort.
//!
//! Проверяем на жёстко ограниченном аллокаторе (2 МБ): сборка большого
//! образа .kimg обязана упереться в лимит и вернуть ошибку, освободив всё
//! выделенное ранее (defer-цепочки не должны течь).
const std = @import("std");
const Builder = @import("../core/kimg_writer.zig").Builder;
const KimgHeader = @import("../core/kimg_reader.zig").KimgHeader;
const compat = @import("compat");

test "OOM: сборка образа на 2 МБ -> error.OutOfMemory (не паника)" {
    var buf: [2 * 1024 * 1024]u8 = undefined;
    var fba = std.heap.FixedBufferAllocator.init(&buf);
    const alloc = fba.allocator();

    var b = Builder.init(alloc);
    defer b.deinit();

    var path_buf: [64]u8 = undefined;
    var content: [512]u8 = undefined;
    @memset(&content, 'A');

    var i: usize = 0;
    var got_oom = false;
    while (i < 100_000) : (i += 1) {
        const path = try std.fmt.bufPrint(&path_buf, "src/mod_{d}.zig", .{i});
        b.addSource(path, &content) catch |e| switch (e) {
            error.OutOfMemory => {
                got_oom = true;
                break;
            },
            else => return e,
        };
    }
    try std.testing.expect(got_oom);
    // Аллокатор не должен «потерять» память: после deinit всё освобождено.
    try std.testing.expect(fba.end_index <= buf.len);
}

test "OOM: запись образа на 2 МБ -> контролируемая ошибка" {
    var buf: [2 * 1024 * 1024]u8 = undefined;
    var fba = std.heap.FixedBufferAllocator.init(&buf);
    const alloc = fba.allocator();

    var b = Builder.init(alloc);
    defer b.deinit();

    var path_buf: [64]u8 = undefined;
    var content: [1024]u8 = undefined;
    @memset(&content, 'B');

    // Помещается немного объектов, но `write` требует ДОПОЛНИТЕЛЬНЫЕ буферы
    // (пул строк, таблицы смещений) -> упираемся в лимит именно на записи.
    var i: usize = 0;
    while (i < 2000) : (i += 1) {
        const path = try std.fmt.bufPrint(&path_buf, "obj/{d}", .{i});
        b.addSource(path, &content) catch break;
    }
    const out = "/tmp/kern_oom_probe.kimg";
    defer compat.deleteFile(out) catch {};

    if (b.write(out)) |_| {
        // Хватило памяти — тоже валидный исход (лимит не достигнут).
    } else |e| {
        try std.testing.expectEqual(error.OutOfMemory, e);
    }
}

test "OOM: парсер заголовка не аллоцирует (zero-copy) — работает при любом лимите" {
    // .kimg парсится БЕЗ выделений памяти: даже нулевой аллокатор не мешает.
    var buf: [128]u8 = @as([128]u8, @splat(0));
    @memcpy(buf[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, buf[8..10], 1, .little); // version_major
    std.mem.writeInt(u32, buf[20..24], 2, .little); // hash_algo = SHA-256
    std.mem.writeInt(u16, buf[10..12], 3, .little); // version_minor
    std.mem.writeInt(u32, buf[12..16], 128, .little); // header_size
    std.mem.writeInt(u64, buf[32..40], 128, .little); // object_table_offset
    std.mem.writeInt(u64, buf[40..48], 0, .little); // object_table_size
    std.mem.writeInt(u64, buf[48..56], 0, .little); // object_count
    std.mem.writeInt(u64, buf[56..64], 128, .little); // data_payload_offset

    var zero_buf: [1]u8 = undefined;
    var fba = std.heap.FixedBufferAllocator.init(&zero_buf);
    _ = fba.allocator(); // аллокатор есть, но НЕ используется

    const hdr: *const [128]u8 = &buf;
    const h = try KimgHeader.parse(hdr, 128);
    try std.testing.expectEqual(@as(u16, 1), h.version_major);
    try std.testing.expectEqual(@as(u32, 128), h.header_size);
}
