// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: СТРЕСС .kimg на 1 000 000 объектов (Merkle + случайный доступ).
//! Запуск: zig run src/kimg_stress.zig -O ReleaseFast
const std = @import("std");
const Builder = @import("core/kimg_writer.zig").Builder;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const compat = @import("compat");

pub fn main() !void {
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    const N: usize = 1_000_000;
    std.debug.print("🗄️  Стресс .kimg: {d} объектов\n\n", .{N});

    var t = try std.time.Timer.start();
    var b = Builder.init(alloc);
    defer b.deinit();
    var nb: [32]u8 = undefined;
    var i: usize = 0;
    while (i < N) : (i += 1) {
        const nm = try std.fmt.bufPrint(&nb, "f{d}", .{i});
        try b.addSource(try alloc.dupe(u8, nm), "z");
    }
    const t_build = t.read();

    t.reset();
    try b.write("/tmp/stress_1m.kimg");
    const t_write = t.read();

    const data = try compat.readFileAlloc(alloc, "/tmp/stress_1m.kimg", 1 << 30);
    defer alloc.free(data);
    defer compat.deleteFile("/tmp/stress_1m.kimg") catch {};

    var hb: [128]u8 = undefined;
    @memcpy(&hb, data[0..128]);
    const h = try KimgHeader.parse(&hb, data.len);

    t.reset();
    try KimgHeader.verifyMerkleRoot(data, h);
    const t_merkle = t.read();

    t.reset();
    var fs = try KernFS.mountFromBytes(alloc, data);
    defer fs.deinit();
    const t_mount = t.read();

    // Случайный доступ: 1000 чтений из середины
    var prng = std.Random.DefaultPrng.init(0xC0FFEE);
    const rand = prng.random();
    t.reset();
    var k: usize = 0;
    var total: usize = 0;
    while (k < 1000) : (k += 1) {
        const idx = N / 2 + rand.uintLessThan(usize, N / 4);
        const sl = try fs.objectPayload(fs.objects[idx]);
        total += sl.len;
    }
    const t_rand = t.read();

    const ms = struct {
        fn f(ns: u64) f64 {
            return @as(f64, @floatFromInt(ns)) / 1_000_000.0;
        }
    }.f;

    std.debug.print("{s:<38} | {s}\n", .{ "Операция", "время" });
    std.debug.print("{s:-<38}-+-{s:-<14}\n", .{ "", "" });
    std.debug.print("{s:<38} | {d:.1} ms\n", .{ "сборка 1e6 объектов", ms(t_build) });
    std.debug.print("{s:<38} | {d:.1} ms\n", .{ "запись образа", ms(t_write) });
    std.debug.print("{s:<38} | {d:.1} ms\n", .{ "Merkle (1e6 листьев)", ms(t_merkle) });
    std.debug.print("{s:<38} | {d:.1} ms\n", .{ "монтирование", ms(t_mount) });
    std.debug.print("{s:<38} | {d:.4} ms/чтение\n", .{ "1000 случайных чтений", ms(t_rand) / 1000.0 });
    std.debug.print("\nОбраз: {d} МБ ({d} байт); прочитано {d} байт\n", .{ data.len / (1 << 20), data.len, total });
    const per = ms(t_rand) / 1000.0;
    std.debug.print("Случайный доступ: {d:.4} мс/объект (цель < 0.005) — {s}\n", .{ per, if (per < 0.005) "✅ ЦЕЛЬ ДОСТИГНУТА" else "⚠️ медленнее" });
}
