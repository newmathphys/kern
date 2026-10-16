// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: замер производительности конвейера .kimg (build / mount / read / Merkle).
//! Запуск: zig run src/perf_bench.zig -O ReleaseFast
const std = @import("std");
const Builder = @import("core/kimg_writer.zig").Builder;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const compat = @import("compat");

pub fn main(init: std.process.Init) !void {
    // БАГ-ФИКС 0.17: файловый I/O требует setIo() до первого вызова,
    // иначе compat паникует (этот бенчмарк читает /tmp/perf_bench.kimg).
    compat.setIo(init.io);
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    const N: usize = 10_000; // объектов
    const content = @as([200]u8, @splat('x')); // 200 байт на объект

    std.debug.print("📈 KERN perf: {d} объектов по {d} байт\n\n", .{ N, content.len });

    // --- 1. СБОРКА образа ---
    var t = compat.Timer.start();
    var b = Builder.init(alloc);
    defer b.deinit();
    var name_buf: [64]u8 = undefined;
    var i: usize = 0;
    while (i < N) : (i += 1) {
        const nm = try std.fmt.bufPrint(&name_buf, "src/file_{d}.zig", .{i});
        try b.addSource(try alloc.dupe(u8, nm), &content);
    }
    const t_build_b = t.read();

    t = compat.Timer.start();
    try b.write("/tmp/perf_bench.kimg");
    const t_write = t.read();

    const data = try compat.readFileAlloc(alloc, "/tmp/perf_bench.kimg", 1 << 28);
    defer alloc.free(data);
    defer compat.deleteFile("/tmp/perf_bench.kimg") catch {};

    // --- 2. ПАРСИНГ заголовка ---
    t = compat.Timer.start();
    var hb: [128]u8 = undefined;
    @memcpy(&hb, data[0..128]);
    const h = try KimgHeader.parse(&hb, data.len);
    const t_parse = t.read();

    // --- 3. MERKLE ---
    t = compat.Timer.start();
    try KimgHeader.verifyMerkleRoot(data, h);
    const t_merkle = t.read();

    // --- 4. МОНТИРОВАНИЕ + ЧТЕНИЕ ВСЕХ объектов (zero-copy) ---
    t = compat.Timer.start();
    var fs = try KernFS.mountFromBytes(alloc, data);
    defer fs.deinit();
    const t_mount = t.read();

    t = compat.Timer.start();
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

    // ЗАЧЕМ ДВА ЗАМЕРА: `objectPayload` СВЕРЯЕТ хеш содержимого с digest
    // дескриптора (защита от подмены payload — ФИКС безопасности). Поэтому
    // честный путь чтения включает хеш. Замеряем ОБА:
    //   • raw-срез   — стоимость адресации без проверки (теоретический максимум);
    //   • с проверкой — реальная стоимость безопасного чтения.
    // Раньше в отчётах фигурировало только число из RAW-замера, из-за чего
    // заявлялось «51 ГБ/с», а фактическое безопасное чтение шло со скоростью
    // порядка сотен МБ/с. Расхождение устранено: документируются ОБА числа.
    //
    // 🔴 ДЕФЕКТ #66 (найден при сверке документации): метка ниже была жёстко
    // зашита как «SHA-256», хотя алгоритм по умолчанию с v2.1.0 — BLAKE3
    // (спецификация §5.3, `hash_algo = 0x0001`). Отчёт печатал неверное имя
    // алгоритма. Теперь имя берётся ИЗ ЗАГОЛОВКА ОБРАЗА — метка не может
    // разойтись с тем, что реально проверялось.
    var timer2 = compat.Timer.start();
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

    const algo_name: []const u8 = switch (h.hash_algo) {
        1 => "BLAKE3",
        2 => "SHA-256",
        else => "неизвестный",
    };
    std.debug.print("{s:<40} | {d:.3} ms\n", .{ "чтение + сверка хеша (безопасное)", ms(t_ver) });
    std.debug.print("{s:<40} | {s} (hash_algo = {d})\n", .{ "  алгоритм сверки", algo_name, h.hash_algo });

    std.debug.print("\nОбраз: {d} байт; прочитано payload: {d} байт; несовпадений: {d}\n", .{ data.len, bytes, mismatches });
    if (t_read > 0) {
        const mbps = (@as(f64, @floatFromInt(bytes)) / (1 << 20)) / (ms(t_read) / 1000.0);
        std.debug.print("RAW zero-copy (адресация без проверки): {d:.1} МБ/с\n", .{mbps});
    }
    if (t_ver > 0) {
        const mbps = (@as(f64, @floatFromInt(ver_bytes)) / (1 << 20)) / (ms(t_ver) / 1000.0);
        // Имя алгоритма берётся из заголовка образа (дефект #66): раньше здесь
        // была жёстко зашита строка «SHA-256», хотя по умолчанию уже BLAKE3.
        std.debug.print("Безопасное чтение (+{s}):{s}{d:.1} МБ/с\n", .{ algo_name, "           ", mbps });
        // ЗАМЕР №2: та же проверка, но ПАКЕТНО (группы по 8 объектов за один
        // векторный проход @Vector(8,u32)). Проверяются те же объекты, поэтому
        // сравнивать МБ/с корректно.
        var timer3 = compat.Timer.start();
        const bat_ok = fs.verifyAllBatch() catch 0;
        const t_bat = timer3.read();
        if (t_bat > 0 and bat_ok > 0 and ver_bytes > 0) {
            const bm = (@as(f64, @floatFromInt(ver_bytes)) / (1 << 20)) / (ms(t_bat) / 1000.0);
            std.debug.print("Безопасное чтение ПАКЕТНО (SIMD-8):{s}{d:.1} МБ/с  (объектов {d})\n", .{ "  ", bm, bat_ok });
        }
    }

    // ---- K2: ПОРОГИ. Без них цель «печатает» и не может упасть -------------
    // Значения выбраны с запасом: замеры дают ~50-90 ГБ/с RAW и ~250-370 МБ/с
    // безопасного чтения (BLAKE3, объекты 200 Б). Порог должен ловить
    // ДЕГРАДАЦИЮ (регрессию), а не колебания стенда.
    //
    // ВАЖНО О ЧИСЛАХ (чтобы не завышать): 369 МБ/с — это end-to-end на объектах
    // 200 Б. На крупных блоках (64 КБ) BLAKE3 даёт 2601 МБ/с против 292 МБ/с у
    // SHA-256 (`make bench-hash`, docs/evidence/hash_bench.log). Прежние
    // заявления о «1.5 ГБ/с на конвейере» были ПРОЕКЦИЕЙ с крупных блоков на
    // мелкие объекты и не подтверждаются замером.
    const RAW_MIN_MBPS: f64 = 30_000.0; // 30 ГБ/с
    const SAFE_MIN_MBPS: f64 = 100.0;   // 100 МБ/с
    var violated = false;
    if (t_read > 0) {
        const raw_mbps = (@as(f64, @floatFromInt(bytes)) / (1 << 20)) / (ms(t_read) / 1000.0);
        if (raw_mbps < RAW_MIN_MBPS) {
            std.debug.print("[!] ПОРОГ RAW НЕ ВЫПОЛНЕН: {d:.1} < {d:.0} МБ/с\n", .{ raw_mbps, RAW_MIN_MBPS });
            violated = true;
        }
    }
    if (t_ver > 0) {
        const ver_mbps = (@as(f64, @floatFromInt(ver_bytes)) / (1 << 20)) / (ms(t_ver) / 1000.0);
        if (ver_mbps < SAFE_MIN_MBPS) {
            std.debug.print("[!] ПОРОГ БЕЗОПАСНОГО ЧТЕНИЯ НЕ ВЫПОЛНЕН: {d:.1} < {d:.0} МБ/с\n", .{ ver_mbps, SAFE_MIN_MBPS });
            violated = true;
        }
    }
    if (violated) std.process.exit(2);
}
