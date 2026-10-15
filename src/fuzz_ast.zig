// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: ФАЗЗИНГ НА 1 000 000 МУТАЦИЙ (долгоживущая кампания).
//!
//! 3000 итераций в юнит-тесте — это предварительная проверка. Здесь —
//! полноценная кампания: случайные байты, нуль-байты, битые смещения,
//! невалидный UTF-8 и усечения по всем структурам ядра.
//!
//! Критерий: **0 паник / 0 SIGSEGV**. Любой исход, кроме паники, приемлем:
//! парсер ОБЯЗАН вернуть ошибку валидации, а не упасть.
//!
//! Запуск: `zig run src/fuzz_ast.zig -O ReleaseFast` (или `make fuzz-1m`).
const std = @import("std");
const compat = @import("compat");
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const ObjectEntry = @import("core/object_entry.zig").ObjectEntry;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const parser = @import("next/parser.zig");

const ITERATIONS: usize = 1_000_000;

/// Строит эталонный образ .kimg v1.3 (как tools/golden_v1_3.py).
fn buildValidImage(alloc: std.mem.Allocator) ![]u8 {
    const content = "hello fuzz";
    const pool = "a.zig\x00" ++ content;

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

    var root: [32]u8 = undefined;
    ObjectEntry.computeRootHash(&[_][96]u8{obj}, &root);

    var header: [128]u8 = @as([128]u8, @splat(0));
    @memcpy(header[0..8], "KIMG\r\n\x1a\n");
    std.mem.writeInt(u16, header[8..10], 1, .little);
    std.mem.writeInt(u32, header[20..24], 1, .little); // hash_algo = SHA-256
    std.mem.writeInt(u16, header[10..12], 3, .little);
    std.mem.writeInt(u32, header[12..16], 128, .little);
    std.mem.writeInt(u64, header[32..40], 128, .little);
    std.mem.writeInt(u64, header[40..48], 96, .little);
    std.mem.writeInt(u64, header[48..56], 1, .little);
    std.mem.writeInt(u64, header[56..64], 224, .little);
    @memcpy(header[64..96], &root);

    var out = std.array_list.Managed(u8).init(alloc);
    try out.appendSlice(&header);
    try out.appendSlice(&obj);
    try out.appendSlice(pool);
    return out.toOwnedSlice();
}

pub fn main(init: std.process.Init) !void {
    // Zig 0.17: файловый I/O требует setIo() до первого вызова.
    compat.setIo(init.io);
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    const golden = try buildValidImage(alloc);
    defer alloc.free(golden);

    var prng = std.Random.DefaultPrng.init(0xC0FFEE);
    const rnd = prng.random();

    var buf = try alloc.alloc(u8, golden.len);
    defer alloc.free(buf);

    std.debug.print("=== KERN ФАЗЗИНГ: {d} мутаций (образ + парсер) ===\n\n", .{ITERATIONS});

    var timer = compat.Timer.start();
    var parse_errors: usize = 0;
    var mount_ok: usize = 0;
    var mount_err: usize = 0;
    var i: usize = 0;
    while (i < ITERATIONS) : (i += 1) {
        @memcpy(buf, golden);

        // 1. Случайные мутации: 1..8 байт в случайных позициях.
        const n_mut = 1 + rnd.uintLessThan(usize, 8);
        var m: usize = 0;
        while (m < n_mut) : (m += 1) {
            const pos = rnd.uintLessThan(usize, buf.len);
            buf[pos] = rnd.int(u8);
        }
        // 2. Иногда — усечение (обрыв файла).
        var len = buf.len;
        if (rnd.uintLessThan(u8, 4) == 0) len = rnd.uintLessThan(usize, buf.len);

        const slice = buf[0..len];

        // --- Заголовок: НИКОГДА не паникует ---
        if (len >= 128) {
            const hdr: *const [128]u8 = @ptrCast(slice.ptr);
            if (KimgHeader.parse(hdr, len)) |h| {
                KimgHeader.verifyMerkleRoot(slice, h) catch {
                    parse_errors += 1;
                };
            } else |_| {
                parse_errors += 1;
            }
        } else {
            parse_errors += 1;
        }

        // --- Монтирование KERNFS (каждые 10 итераций — дорого) ---
        if (i % 10 == 0) {
            if (KernFS.mountFromBytes(alloc, slice)) |fs_v| {
                var fs = fs_v;
                defer fs.deinit();
                mount_ok += 1;
                _ = fs.read("/raw/a.zig") catch {};
                _ = fs.read("/../../etc/passwd") catch {};
                _ = fs.read("/claims/x/status") catch {};
            } else |_| {
                mount_err += 1;
            }
        }

        // --- Парсер .kern (каждые 100 итераций) ---
        if (i % 100 == 0) {
            _ = parser.parse(alloc, slice) catch continue;
        }
    }

    const ms = timer.read() / std.time.ns_per_ms;
    std.debug.print("=== РЕЗУЛЬТАТЫ (0 паник — процесс жив) ===\n", .{});
    std.debug.print("  итераций:            {d}\n", .{ITERATIONS});
    std.debug.print("  время:               {d} мс ({d:.0} тыс. мутаций/сек)\n", .{
        ms, @as(f64, @floatFromInt(ITERATIONS)) / @as(f64, @floatFromInt(ms)),
    });
    std.debug.print("  отвергнуто парсером: {d}\n", .{parse_errors});
    std.debug.print("  монтирований OK:     {d}\n", .{mount_ok});
    std.debug.print("  монтирований err:    {d}\n", .{mount_err});
    std.debug.print("  ПАНИК/SIGSEGV:       0\n", .{});
}
