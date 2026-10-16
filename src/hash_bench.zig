// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: ЗАМЕР ХЕШ-ФУНКЦИЙ (узкое место безопасного чтения).
//!
//! ПОВОД. Профиль чтения `.kimg`:
//!   * RAW zero-copy  : ~83 000 МБ/с (чистая адресация памяти);
//!   * безопасное чтение: ~212 МБ/с (адресация + SHA-256 на каждом байте).
//! Разрыв ~393× — и он целиком создаётся ПРОГРАММНЫМ SHA-256.
//!
//! ВОПРОС: чем заменить, чтобы сохранить безопасность и поднять скорость?
//!   * SHA-NI (аппаратные инструкции) — недоступен на Kaby Lake (i7-7700) и
//!     вообще появился только в Ice Lake / Zen; на целевых серверах может быть.
//!   * BLAKE3 — есть в Zig std (`std.crypto.hash.Blake3`), SIMD-дружественный,
//!     и УЖЕ заявлен в спецификации KERN как `hash_algo = 0x0001`.
//!
//! ЧТО МЕРЯЕТ. Пропускную способность обеих функций на реальных размерах
//! payload KERN (1 КБ … 4 МБ), а также стоимость «маленького» объекта (96 Б),
//! где важна не пропускная, а задержка на вызов.
//!
//! Запуск: zig build bench-hash

const std = @import("std");
const compat = @import("compat");
const simd8 = @import("core/blake3_simd8.zig");

/// Обёртки приводят РАЗНЫЕ сигнатуры std к одному виду `(data, out: []u8)`.
fn sha256Wrap(data: []const u8, out: []u8) void {
    std.crypto.hash.sha2.Sha256.hash(data, out[0..32], .{});
}

fn blake3Wrap(data: []const u8, out: []u8) void {
    std.crypto.hash.Blake3.hash(data, out[0..32], .{});
}

fn benchHash(
    comptime hashFn: fn ([]const u8, []u8) void,
    data: []const u8,
    iters: usize,
) u64 {
    var out: [32]u8 = undefined;
    // Прогрев (страницы, ветвление предиктора).
    hashFn(data, &out);
    var t = compat.Timer.start();
    var i: usize = 0;
    while (i < iters) : (i += 1) {
        hashFn(data, &out);
        std.mem.doNotOptimizeAway(&out);
    }
    return t.read();
}

/// Пакетный замер: 8 объектов за один векторный проход.
fn benchBatch8(data: []const u8, obj_len: usize, iters: usize) u64 {
    var slices: [8][]const u8 = undefined;
    for (&slices, 0..) |*s, i| s.* = data[i * obj_len ..][0..obj_len];
    var outs: [8][32]u8 = undefined;
    simd8.hash8SmallObjects(slices, &outs); // прогрев
    var t = compat.Timer.start();
    var i: usize = 0;
    while (i < iters) : (i += 1) {
        simd8.hash8SmallObjects(slices, &outs);
        std.mem.doNotOptimizeAway(&outs);
    }
    return t.read();
}

/// Поштучный замер тех же 8 объектов (для честного сравнения).
fn benchOneByOne(data: []const u8, obj_len: usize, iters: usize) u64 {
    var out: [32]u8 = undefined;
    std.crypto.hash.Blake3.hash(data[0..obj_len], &out, .{});
    var t = compat.Timer.start();
    var i: usize = 0;
    while (i < iters) : (i += 1) {
        inline for (0..8) |k| {
            std.crypto.hash.Blake3.hash(data[k * obj_len ..][0..obj_len], &out, .{});
        }
        std.mem.doNotOptimizeAway(&out);
    }
    return t.read();
}

pub fn main() !void {
    var gpa = std.heap.DebugAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    const sizes = [_]usize{ 96, 1024, 64 * 1024, 1024 * 1024, 4 * 1024 * 1024 };
    const iters = [_]usize{ 200_000, 50_000, 2_000, 200, 50 };

    std.debug.print(
        \\KERN: SHA-256 vs BLAKE3 — замер узкого места безопасного чтения
        \\---------------------------------------------------------------------------
        \\{s:>10} | {s:>14} | {s:>14} | {s:>8}
        \\
    , .{ "размер", "SHA-256, МБ/с", "BLAKE3, МБ/с", "выигрыш" });

    var total_sha: f64 = 0;
    var total_blake: f64 = 0;
    var n: f64 = 0;

    for (sizes, iters) |size, it| {
        const buf = try alloc.alloc(u8, size);
        defer alloc.free(buf);
        // Детерминированное содержимое (не нули: важно для реалистичного
        // ветвления внутри раундовых функций).
        for (buf, 0..) |*b, i| b.* = @truncate((i *% 131 +% 7) & 0xFF);

        const sha_ns = benchHash(sha256Wrap, buf, it);
        const blake_ns = benchHash(blake3Wrap, buf, it);

        const mb = @as(f64, @floatFromInt(size)) / (1024.0 * 1024.0);
        const sha_mbs = if (sha_ns == 0) 0 else mb * @as(f64, @floatFromInt(it)) / (@as(f64, @floatFromInt(sha_ns)) / 1e9);
        const blake_mbs = if (blake_ns == 0) 0 else mb * @as(f64, @floatFromInt(it)) / (@as(f64, @floatFromInt(blake_ns)) / 1e9);
        const gain = if (sha_mbs == 0) 0 else blake_mbs / sha_mbs;

        std.debug.print("{d:>10} | {d:>14.1} | {d:>14.1} | {d:>7.2}x\n", .{ size, sha_mbs, blake_mbs, gain });

        total_sha += sha_mbs;
        total_blake += blake_mbs;
        n += 1;
    }

    std.debug.print("---------------------------------------------------------------------------\n", .{});
    std.debug.print("среднее: SHA-256 {d:.1} МБ/с · BLAKE3 {d:.1} МБ/с · выигрыш {d:.2}x\n", .{
        total_sha / n, total_blake / n, (total_blake / total_sha),
    });

    // Проекция на конвейер чтения .kimg: RAW ~83 000 МБ/с.
    const raw_mbs: f64 = 83_392.0;
    const sha_safe = total_sha / n;
    const blake_safe = total_blake / n;
    std.debug.print("\nКОНВЕЙЕР ЧТЕНИЯ .kimg (RAW = {d:.0} МБ/с):\n", .{raw_mbs});
    std.debug.print("  сейчас (SHA-256): {d:.0} МБ/с  ->  разрыв {d:.0}x от RAW\n", .{ sha_safe, raw_mbs / sha_safe });
    std.debug.print("  с BLAKE3:         {d:.0} МБ/с  ->  разрыв {d:.0}x от RAW\n", .{ blake_safe, raw_mbs / blake_safe });
    // ---- ЗАМЕР №1: пакетный SIMD-8 против поштучного BLAKE3 ----
    std.debug.print("\nпакетный SIMD-8 BLAKE3 (@Vector(8,u32)) против поштучного:\n", .{});
    std.debug.print("---------------------------------------------------------------------------\n", .{});
    std.debug.print("{s:>10} | {s:>16} | {s:>16} | {s:>8}\n", .{ "объект", "поштучно МБ/с", "пакетно МБ/с", "выигрыш" });
    const OBJ_N = 10000;
    for ([_]usize{ 96, 200, 512, 1024 }) |obj_len| {
        const total = OBJ_N * obj_len;
        const buf = try alloc.alloc(u8, total);
        defer alloc.free(buf);
        for (buf, 0..) |*b, i| b.* = @truncate((i * 31 + 7) & 0xFF);

        const groups = OBJ_N / 8;
        const one_ns = benchOneByOne(buf, obj_len, groups) + 1;
        const bat_ns = benchBatch8(buf, obj_len, groups) + 1;
        const one_mbs = @as(f64, @floatFromInt(groups * 8 * obj_len)) / @as(f64, @floatFromInt(one_ns)) * 1000.0;
        const bat_mbs = @as(f64, @floatFromInt(groups * 8 * obj_len)) / @as(f64, @floatFromInt(bat_ns)) * 1000.0;
        std.debug.print("{d:>10} | {d:>16.1} | {d:>16.1} | {d:>7.2}x\n", .{ obj_len, one_mbs, bat_mbs, bat_mbs / one_mbs });
    }

    std.debug.print(
        \\
        \\ВЫВОД: SHA-NI недоступен на Kaby Lake (появился в Ice Lake / Zen),
        \\поэтому замена на BLAKE3 — ЕДИНСТВЕННЫЙ доступный здесь рычаг.
        \\BLAKE3 уже заявлен в спецификации KERN как hash_algo = 0x0001.
        \\
    , .{});
}
