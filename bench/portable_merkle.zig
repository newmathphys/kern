// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: ПОРТИРУЕМЫЙ БЕНЧМАРК (одинаковый код на Zig 0.13 и 0.17).
//!
//! ЦЕЛЬ: строго измерить влияние КОМПИЛЯТОРА, а не кода. Поэтому здесь
//! НЕТ импортов KERN (`compat`, `kimg_writer`, ...) — только чистый `std`,
//! который есть в обеих версиях, плюс libc-таймер.
//!
//! ПОЧЕМУ libc clock_gettime: в 0.17 `std.time.Timer`/`nanoTimestamp` удалены
//! (переехали в `std.Io.Clock`), поэтому `std.time` не годится как общий API.
//! `extern fn clock_gettime` работает в ОБЕИХ версиях без изменений.
//!
//! Запуск:
//!   zig run bench/portable_merkle.zig -O ReleaseFast -lc

const std = @import("std");

const TimeSpec = extern struct { sec: i64, nsec: i64 };
extern fn clock_gettime(clk_id: c_int, tp: *TimeSpec) c_int;
const CLOCK_MONOTONIC: c_int = 1;

fn nowNs() i128 {
    var ts: TimeSpec = undefined;
    _ = clock_gettime(CLOCK_MONOTONIC, &ts);
    return @as(i128, ts.sec) * 1_000_000_000 + @as(i128, ts.nsec);
}

/// Размер записи таблицы объектов KERN (как в .kimg).
const REC: usize = 96;
const N: usize = 1_000_000;
const READS: usize = 100_000;

pub fn main() !void {
    const alloc = std.heap.page_allocator;

    const buf = try alloc.alloc(u8, N * REC);
    defer alloc.free(buf);
    @memset(buf, 0);

    // ---------- 1. СБОРКА: N записей по 96 байт ----------
    const t0 = nowNs();
    var i: usize = 0;
    while (i < N) : (i += 1) {
        const off = i * REC;
        const recp: *[REC]u8 = @ptrCast(buf[off .. off + REC].ptr);
        std.mem.writeInt(u64, recp[32..40], off, .little);          // payload_offset
        std.mem.writeInt(u64, recp[40..48], REC, .little);          // uncompressed_size
        std.mem.writeInt(u64, recp[48..56], REC, .little);          // compressed_size
        std.mem.writeInt(u32, recp[56..60], @intCast(i % 7), .little); // type_id
        std.mem.writeInt(u32, recp[64..68], @intCast(i), .little);  // logical_path_offset
    }
    const t_build = nowNs() - t0;

    // ---------- 2. MERKLE: SHA-256 по листьям ----------
    const t1 = nowNs();
    var root_hasher = std.crypto.hash.sha2.Sha256.init(.{});
    root_hasher.update(&[_]u8{0x00});
    root_hasher.update("KIMG-MERKLE-ROOT-V1\x00");
    var leaf: [32]u8 = undefined;
    i = 0;
    while (i < N) : (i += 1) {
        const off = i * REC;
        var lh = std.crypto.hash.sha2.Sha256.init(.{});
        lh.update(&[_]u8{0x00});
        lh.update(buf[off .. off + REC]);
        lh.final(&leaf);
        root_hasher.update(&leaf);
    }
    var root: [32]u8 = undefined;
    root_hasher.final(&root);
    const t_merkle = nowNs() - t1;

    // ---------- 3. СЛУЧАЙНЫЙ ДОСТУП (zero-copy адресация) ----------
    var seed: u64 = 0x1337;
    var acc: u64 = 0;
    const t2 = nowNs();
    var k: usize = 0;
    while (k < READS) : (k += 1) {
        // LCG — без зависимости от std.Random (API менялся между версиями)
        seed = seed *% 6364136223846793005 +% 1442695040888963407;
        const idx = (seed >> 33) % N;
        const off = idx * REC;
        // Читаем НЕнулевой байт (payload_offset) — иначе компилятор вправе
        // выбросить загрузку (в прошлой версии acc всегда был 0 — это
        // маскировало реальную стоимость доступа).
        acc +%= buf[off + 32];
    }
    const t_access = nowNs() - t2;

    // ---------- ВЫВОД ----------
    const ms = struct {
        fn f(ns: i128) f64 {
            return @as(f64, @floatFromInt(ns)) / 1_000_000.0;
        }
    }.f;

    const total_bytes: f64 = @floatFromInt(N * REC);
    const build_mbs = (total_bytes / (1 << 20)) / (ms(t_build) / 1000.0);
    const merkle_mbs = (total_bytes / (1 << 20)) / (ms(t_merkle) / 1000.0);
    const access_us = ms(t_access) * 1000.0 / @as(f64, @floatFromInt(READS));

    std.debug.print("ZIG_VERSION={s}\n", .{@import("builtin").zig_version_string});
    std.debug.print("REC={d} N={d} READS={d}\n", .{ REC, N, READS });
    std.debug.print("build_ms={d:.3}\n", .{ms(t_build)});
    std.debug.print("merkle_ms={d:.3}\n", .{ms(t_merkle)});
    std.debug.print("access_us={d:.4}\n", .{access_us});
    std.debug.print("build_MBps={d:.1}\n", .{build_mbs});
    std.debug.print("merkle_MBps={d:.1}\n", .{merkle_mbs});
    std.debug.print("root0={x:0>2}{x:0>2}\n", .{ root[0], root[1] });
    std.debug.print("acc={d}\n", .{acc});
}
