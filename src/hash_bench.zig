// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

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
    std.debug.print(
        \\
        \\ВЫВОД: SHA-NI недоступен на Kaby Lake (появился в Ice Lake / Zen),
        \\поэтому замена на BLAKE3 — ЕДИНСТВЕННЫЙ доступный здесь рычаг.
        \\BLAKE3 уже заявлен в спецификации KERN как hash_algo = 0x0001.
        \\
    , .{});
}
