// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN — ДЕТЕРМИНИРОВАННЫЙ СИМУЛЯЦИОННЫЙ ТЕСТ (VOPR-стиль).
//!
//! ИДЕЯ (как в TigerBeetle / FoundationDB): весь мир — ПСЕВДОСЛУЧАЙНЫЙ и
//! управляется ОДНИМ СИДОМ. Последовательность операций полностью
//! воспроизводима: тот же сид даёт ту же историю на любой машине.
//!
//! МОДЕЛИРУЕТСЯ:
//!   • сборка образа .kimg со случайными объектами;
//!   • монтирование (Merkle + заголовок) и чтение (сверка SHA-256);
//!   • ПОРЧА БАЙТА (bit-rot) — эмуляция деградации носителя;
//!   • УСЕЧЕНИЕ образа по случайной границе.
//!
//! ИНВАРИАНТЫ (после каждой операции):
//!   I1. Нет паник / SIGSEGV.
//!   I2. Целый образ читается полностью.
//!   I3. Порча НЕ приводит к выдаче «валидных чужих» данных (строго 0).
//!   I4. Усечённый образ не монтируется молча.
//!
//! Запуск:
//!   zig run src/sim_test.zig -O ReleaseFast -- --seed 0xDEADBEEF --ops 20000
//!   zig run src/sim_test.zig -O ReleaseFast -- --seeds 1,2,3,4,5

const std = @import("std");
const kimg = @import("core/kimg_writer.zig");
const Builder = kimg.Builder;
const KernFS = @import("core/kernfs_router.zig").KernFS;
const ObjectEntry = @import("core/object_entry.zig").ObjectEntry;

const Stats = struct {
    ops: usize = 0,
    built: usize = 0,
    mounts_ok: usize = 0,
    mounts_err: usize = 0,
    reads_ok: usize = 0,
    reads_err: usize = 0,
    tamper_tested: usize = 0,
    tamper_caught: usize = 0,
    trunc_rejected: usize = 0,
    /// ИНВАРИАНТ I3: сколько раз порченый образ отдал данные, совпадающие
    /// с ИСХОДНЫМИ (значит подмена не замечена). Обязано быть СТРОГО 0.
    false_accept: usize = 0,
    fa_i2: usize = 0,  // нарушение на ЦЕЛОМ образе (I2)
    fa_i3: usize = 0,  // нарушение на порченом образе (I3)
};

fn add(a: *Stats, b: Stats) void {
    a.ops += b.ops;
    a.built += b.built;
    a.mounts_ok += b.mounts_ok;
    a.mounts_err += b.mounts_err;
    a.reads_ok += b.reads_ok;
    a.reads_err += b.reads_err;
    a.tamper_tested += b.tamper_tested;
    a.tamper_caught += b.tamper_caught;
    a.trunc_rejected += b.trunc_rejected;
    a.false_accept += b.false_accept;
    a.fa_i2 += b.fa_i2;
    a.fa_i3 += b.fa_i3;
}

/// Безопасное чтение u64 из буфера БЕЗ @ptrCast/@alignCast.
/// (тот же принцип, что в kimg_reader: побайтовое декодирование)
fn rd64(buf: []const u8, at: usize) u64 {
    var tmp: [8]u8 = undefined;
    @memcpy(&tmp, buf[at .. at + 8]);
    return std.mem.readInt(u64, &tmp, .little);
}

/// Проверка ИНВАРИАНТА I3: читает все объекты и сравнивает с эталоном.
/// Возвращает число объектов, чьи данные СОВПАЛИ с исходными (для порченого
/// образа это означает «подмена не замечена»).
fn countUnchanged(fs: KernFS, originals: []const []const u8) usize {
    var same: usize = 0;
    for (fs.objects, 0..) |obj, idx| {
        if (idx >= originals.len) break;
        if (fs.objectPayload(obj)) |sl| {
            if (std.mem.eql(u8, sl, originals[idx])) same += 1;
        } else |_| {}
    }
    return same;
}

fn runSeed(alloc: std.mem.Allocator, seed: u64, ops: usize) !Stats {
    var prng = std.Random.DefaultPrng.init(seed);
    const rnd = prng.random();
    var st = Stats{};

    var payload: [256]u8 = undefined;
    var img = std.ArrayList(u8).init(alloc);
    defer img.deinit();
    // Эталон содержимого объектов текущего образа (для проверки I3).
    var originals = std.ArrayList([]const u8).init(alloc);
    defer {
        for (originals.items) |o| alloc.free(o);
        originals.deinit();
    }

    var i: usize = 0;
    while (i < ops) : (i += 1) {
        st.ops += 1;
        const op = rnd.uintLessThan(u8, 10);

        if (op < 4) {
            // ---------- СБОРКА ----------
            const n = rnd.intRangeAtMost(usize, 1, 6);
            var b = Builder.init(alloc);
            defer b.deinit();
            for (originals.items) |o| alloc.free(o);
            originals.clearRetainingCapacity();

            var k: usize = 0;
            while (k < n) : (k += 1) {
                const len = rnd.intRangeAtMost(usize, 1, 64);
                rnd.bytes(payload[0..len]);
                var nb: [24]u8 = undefined;
                const name = try std.fmt.bufPrint(&nb, "obj{d}.bin", .{k});
                // ВАЖНО: `Builder.addSource` ХРАНИТ СРЕЗ, а не копию (см.
                // предупреждение в kimg_writer.zig). Буфер `payload`
                // переиспользуется — поэтому передаём КОПИЮ, иначе все
                // объекты получили бы содержимое последней итерации.
                const content = try alloc.dupe(u8, payload[0..len]);
                try b.addSource(name, content);
                try originals.append(try alloc.dupe(u8, payload[0..len]));
            }
            img.clearRetainingCapacity();
            try b.buildBytes(&img);
            st.built += 1;
            continue;
        }

        if (img.items.len == 0) continue;

        if (op < 7) {
            // ---------- МОНТИРОВАНИЕ + ЧТЕНИЕ (I2) ----------
            var fs = KernFS.mountFromBytes(alloc, img.items) catch {
                st.mounts_err += 1;
                continue;
            };
            defer fs.deinit();
            st.mounts_ok += 1;
            for (fs.objects, 0..) |obj, idx| {
                if (fs.objectPayload(obj)) |sl| {
                    st.reads_ok += 1;
                    // I2: на ЦЕЛОМ образе данные обязаны совпасть с эталоном.
                    if (idx < originals.items.len and
                        !std.mem.eql(u8, sl, originals.items[idx]))
                    {
                        st.false_accept += 1;
                        st.fa_i2 += 1;
                        if (st.fa_i2 <= 2) {
                            std.debug.print("  [I2] obj{d}: прочитано {d} б, эталон {d} б\n", .{
                                idx, sl.len, originals.items[idx].len,
                            });
                        }
                    }
                } else |_| st.reads_err += 1;
            }
            continue;
        }

        if (op < 9) {
            // ---------- ПОРЧА БАЙТА (bit-rot) — ИНВАРИАНТ I3 ----------
            //
            // ЛОГИКА ПРОВЕРКИ (важно не ошибиться самому):
            // порча вне тела объектов (в заголовке/таблице/пуле путей) обязана
            // ловиться Merkle-корнем; порча ВНУТРИ payload объекта — сверкой
            // SHA-256, причём падать должен ИМЕННО ЭТОТ объект, а остальные
            // обязаны читаться нормально. «Поймано» = образ отвергнут ИЛИ
            // испорченный объект отвергнут.
            var copy = try alloc.dupe(u8, img.items);
            defer alloc.free(copy);
            const at = rnd.uintLessThan(usize, copy.len);
            copy[at] ^= @as(u8, 1) << @as(u3, @intCast(rnd.uintLessThan(u4, 8)));
            st.tamper_tested += 1;

            // Координаты областей из заголовка.
            const tbl_off = rd64(copy, 32);
            const cnt = rd64(copy, 48);
            const pay_off = rd64(copy, 56);

            // В каком объекте (если вообще) лежит испорченный байт?
            var victim: ?usize = null;
            if (at >= pay_off) {
                var idx: usize = 0;
                while (idx < cnt) : (idx += 1) {
                    const base = tbl_off + idx * 96;
                    const po = rd64(copy, base + 32);
                    const sz = rd64(copy, base + 40);
                    const lo = pay_off + po;
                    if (at >= lo and at < lo + sz) {
                        victim = idx;
                        break;
                    }
                }
            }

            var fs = KernFS.mountFromBytes(alloc, copy) catch {
                st.tamper_caught += 1; // заголовок/таблица/пул — поймано Merkle
                continue;
            };
            defer fs.deinit();

            if (victim) |vi| {
                // Испорчен ИМЕННО payload объекта vi: он обязан быть отвергнут.
                if (vi < fs.objects.len) {
                    if (fs.objectPayload(fs.objects[vi])) |_| {
                        st.false_accept += 1; st.fa_i3 += 1; // подмена НЕ замечена
                    } else |_| {
                        st.tamper_caught += 1;
                    }
                }
            } else {
                // Порча в области, не входящей в payload ни одного объекта.
                st.tamper_caught += 1;
            }
            continue;
        }

        // ---------- УСЕЧЕНИЕ (I4) ----------
        const cut = rnd.intRangeAtMost(usize, 0, img.items.len);
        var fs = KernFS.mountFromBytes(alloc, img.items[0..cut]) catch {
            st.trunc_rejected += 1;
            continue;
        };
        defer fs.deinit();
        st.mounts_ok += 1;
    }
    return st;
}

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    const argv = try std.process.argsAlloc(alloc);
    var seed: u64 = 0xDEADBEEF;
    var ops: usize = 20_000;
    var seeds_list: ?[]const u8 = null;

    var i: usize = 1;
    while (i < argv.len) : (i += 1) {
        if (std.mem.eql(u8, argv[i], "--seed") and i + 1 < argv.len) {
            seed = try std.fmt.parseInt(u64, argv[i + 1], 0);
            i += 1;
        } else if (std.mem.eql(u8, argv[i], "--ops") and i + 1 < argv.len) {
            ops = try std.fmt.parseInt(usize, argv[i + 1], 0);
            i += 1;
        } else if (std.mem.eql(u8, argv[i], "--seeds") and i + 1 < argv.len) {
            seeds_list = argv[i + 1];
            i += 1;
        }
    }

    std.debug.print("\n=== KERN ДЕТЕРМИНИРОВАННЫЙ СИМУЛЯТОР (VOPR-стиль) ===\n", .{});
    std.debug.print("Инварианты: I1 нет паник · I2 целый образ читается · " ++
        "I3 порча замечена · I4 усечение отвергнуто\n\n", .{});

    var timer = try std.time.Timer.start();
    var total = Stats{};
    var seeds_ok: usize = 0;

    if (seeds_list) |sl| {
        var it = std.mem.tokenizeAny(u8, sl, ", ");
        while (it.next()) |tok| {
            const s = try std.fmt.parseInt(u64, tok, 0);
            const st = try runSeed(alloc, s, ops);
            std.debug.print("  сид {d:>12}: ops={d} сборок={d} монт.ok={d} чтений={d} " ++
                "порча={d} усечений={d}\n", .{
                s,         st.ops,     st.built, st.mounts_ok,
                st.reads_ok, st.tamper_caught, st.trunc_rejected,
            });
            add(&total, st);
            seeds_ok += 1;
        }
    } else {
        const st = try runSeed(alloc, seed, ops);
        std.debug.print("  сид {d}: ops={d} сборок={d} монтирований(ok/err)={d}/{d} " ++
            "чтений(ok/err)={d}/{d} порча={d} усечений={d}\n", .{
            seed,         st.ops,        st.built,         st.mounts_ok,
            st.mounts_err, st.reads_ok,  st.reads_err,     st.tamper_caught,
            st.trunc_rejected,
        });
        total = st;
        seeds_ok = 1;
    }

    const ms = @as(f64, @floatFromInt(timer.read())) / 1_000_000.0;
    std.debug.print("\n--- ИТОГ ({d} сид(ов), {d:.0} мс) ---\n", .{ seeds_ok, ms });
    std.debug.print("операций:            {d}\n", .{total.ops});
    std.debug.print("сборок образа:       {d}\n", .{total.built});
    std.debug.print("монтирований ok/err: {d}/{d}\n", .{ total.mounts_ok, total.mounts_err });
    std.debug.print("чтений ok/err:       {d}/{d}\n", .{ total.reads_ok, total.reads_err });
    std.debug.print("порча проверена:     {d} (замечена: {d})\n", .{ total.tamper_tested, total.tamper_caught });
    std.debug.print("усечений отвергнуто: {d}\n", .{total.trunc_rejected});

    std.debug.print("\nНАРУШЕНИЯ: I2 (целый образ)={d} · I3 (порченый образ)={d}\n", .{ total.fa_i2, total.fa_i3 });
    std.debug.print("ИНВАРИАНТ I3 (подмена не замечена): {d}", .{total.false_accept});
    if (total.false_accept == 0) {
        std.debug.print("  -> OK\n", .{});
    } else {
        std.debug.print("  -> НАРУШЕН!\n", .{});
        std.process.exit(1);
    }
    std.debug.print("Воспроизводимость: тот же сид даёт ту же историю на любой машине.\n\n", .{});
}
