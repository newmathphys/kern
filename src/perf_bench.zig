// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: замер производительности конвейера .kimg (build / mount / read / Merkle).
//! Запуск: zig run src/perf_bench.zig -O ReleaseFast
const std = @import("std");
const Builder = @import("core/kimg_writer.zig").Builder;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const compat = @import("compat");

pub fn main() !void {
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    const N: usize = 10_000; // объектов
    const content = @as([200]u8, @splat('x')); // 200 байт на объект

    std.debug.print("📈 KERN perf: {d} объектов по {d} байт\n\n", .{ N, content.len });

    // --- 1. СБОРКА образа ---
    var t = try std.time.Timer.start();
    var b = Builder.init(alloc);
    defer b.deinit();
    var name_buf: [64]u8 = undefined;
    var i: usize = 0;
    while (i < N) : (i += 1) {
        const nm = try std.fmt.bufPrint(&name_buf, "src/file_{d}.zig", .{i});
        try b.addSource(try alloc.dupe(u8, nm), content);
    }
    const t_build_b = t.read();

    t.reset();
    try b.write("/tmp/perf_bench.kimg");
    const t_write = t.read();

    const data = try compat.readFileAlloc(alloc, "/tmp/perf_bench.kimg", 1 << 28);
    defer alloc.free(data);
    defer compat.deleteFile("/tmp/perf_bench.kimg") catch {};

    // --- 2. ПАРСИНГ заголовка ---
    t.reset();
    var hb: [128]u8 = undefined;
    @memcpy(&hb, data[0..128]);
    const h = try KimgHeader.parse(&hb, data.len);
    const t_parse = t.read();

    // --- 3. MERKLE ---
    t.reset();
    try KimgHeader.verifyMerkleRoot(data, h);
    const t_merkle = t.read();

    // --- 4. МОНТИРОВАНИЕ + ЧТЕНИЕ ВСЕХ объектов (zero-copy) ---
    t.reset();
    var fs = try KernFS.mountFromBytes(alloc, data);
    defer fs.deinit();
    const t_mount = t.read();

    t.reset();
    var bytes: usize = 0;
    for (fs.objects) |obj| {
        const sl = try fs.objectPayloadRaw(obj); // чистый zero-copy, без хеша
        bytes += sl.len;
    }
    const t_read = t.read();

    const ms = struct {
        fn f(ns: u64) f64 {
            return @as(f64, @floatFromInt(ns)) / 1_000_000.0;
        }
    }.f;

    std.debug.print("{s:<40} | {s}\n", .{ "Операция", "время" });
    std.debug.print("{s:-<40}-+-{s:-<14}\n", .{ "", "" });
    std.debug.print("{s:<40} | {d:.2} ms\n", .{ "сборка объектов (в память)", ms(t_build_b) });
    std.debug.print("{s:<40} | {d:.2} ms\n", .{ "запись образа на диск", ms(t_write) });
    std.debug.print("{s:<40} | {d:.3} ms\n", .{ "парсинг 128-байт заголовка", ms(t_parse) });
    std.debug.print("{s:<40} | {d:.3} ms\n", .{ "Merkle-корень (10000 листьев)", ms(t_merkle) });
    std.debug.print("{s:<40} | {d:.3} ms\n", .{ "монтирование (разбор таблицы)", ms(t_mount) });
    std.debug.print("{s:<40} | {d:.3} ms\n", .{ "чтение ВСЕХ объектов (raw-срез)", ms(t_read) });

    // ЗАЧЕМ ДВА ЗАМЕРА: `objectPayload` теперь СВЕРЯЕТ SHA-256 содержимого с
    // digest дескриптора (защита от подмены payload — ФИКС безопасности).
    // Поэтому честный путь чтения включает хеш. Замеряем ОБА:
    //   • raw-срез   — стоимость адресации без проверки (теоретический максимум);
    //   • с проверкой — реальная стоимость безопасного чтения.
    // Раньше в отчётах фигурировало только число из RAW-замера, из-за чего
    // заявлялось «51 ГБ/с», а фактическое безопасное чтение шло со скоростью
    // порядка сотен МБ/с (SHA-256 ~1.5 ГБ/с на этом CPU). Расхождение
    // устранено: документируются ОБА числа.
    var timer2 = try std.time.Timer.start();
    var ver_bytes: usize = 0;
    var mismatches: usize = 0;
    for (fs.objects) |obj| {
        const sl = fs.objectPayload(obj) catch {
            mismatches += 1;
            continue;
        };
        ver_bytes += sl.len;
    }
    const t_ver = timer2.read();

    std.debug.print("{s:<40} | {d:.3} ms\n", .{ "чтение + сверка SHA-256 (безопасное)", ms(t_ver) });

    std.debug.print("\nОбраз: {d} байт; прочитано payload: {d} байт; несовпадений: {d}\n", .{ data.len, bytes, mismatches });
    if (t_read > 0) {
        const mbps = (@as(f64, @floatFromInt(bytes)) / (1 << 20)) / (ms(t_read) / 1000.0);
        std.debug.print("RAW zero-copy (адресация без проверки): {d:.1} МБ/с\n", .{mbps});
    }
    if (t_ver > 0) {
        const mbps = (@as(f64, @floatFromInt(ver_bytes)) / (1 << 20)) / (ms(t_ver) / 1000.0);
        std.debug.print("Безопасное чтение (+SHA-256):           {d:.1} МБ/с\n", .{mbps});
    }
}
