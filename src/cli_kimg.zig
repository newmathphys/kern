// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! CLI-слой над готовым парсером KIMG (Ф3.2): `fsck`, `inspect`, `diff`.
//!
//! ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Тесты в Zig проверяют парсер на массивах байтов,
//! но внешний `conformance_check.py` (Фаза 5, раздел 10) работает только с
//! ФАЙЛАМИ и командами. Без CLI конформанс был бы фиктивным.
//!
//! Коды возврата: 0 — всё хорошо / файлы идентичны; 1 — найдены проблемы /
//! файлы различаются; 2 — файл не читается.

const std = @import("std");
const compat = @import("compat");
const KimgHeader = @import("core/kimg_reader.zig").KimgHeader;
const KernFS = @import("core/kernfs_router.zig").KernFS;

fn load(alloc: std.mem.Allocator, path: []const u8) ?[]u8 {
    return compat.readFileAlloc(alloc, path, 1 << 26) catch |e| {
        std.debug.print("[!] не читается '{s}': {s}\n", .{ path, @errorName(e) });
        return null;
    };
}

fn headerOf(data: []const u8) ?KimgHeader {
    if (data.len < 128) {
        std.debug.print("[!] файл короче заголовка (128 байт)\n", .{});
        return null;
    }
    var hb: [128]u8 = undefined;
    @memcpy(&hb, data[0..128]);
    return KimgHeader.parse(&hb, data.len) catch |e| {
        std.debug.print("[FAIL] заголовок: {s}\n", .{@errorName(e)});
        return null;
    };
}

/// Полная проверка: заголовок, Merkle-корень, каждый объект (хеш + границы).
pub fn fsck(alloc: std.mem.Allocator, path: []const u8) u8 {
    const data = load(alloc, path) orelse return 2;
    const h = headerOf(data) orelse return 1;

    var m = KernFS.mountFromBytesOwned(alloc, data) catch |e| {
        std.debug.print("[FAIL] монтирование: {s}\n", .{@errorName(e)});
        return 1;
    };
    defer m.deinit(alloc);

    var ok: usize = 0;
    var bad: usize = 0;
    for (m.fs.objects) |obj| {
        if (m.fs.objectPayload(obj)) |_| {
            ok += 1;
        } else |err| {
            std.debug.print("  [BAD] {s}: {s}\n", .{ m.fs.objectPath(obj), @errorName(err) });
            bad += 1;
        }
    }

    std.debug.print(
        "[fsck] {s}\n  версия {d}.{d} · hash_algo {d} · флаги 0x{X:0>8} · объектов {d}\n" ++
            "  проверено {d}, ошибок {d}\n",
        .{ path, h.version_major, h.version_minor, h.hash_algo, h.flags,
           m.fs.objects.len, ok, bad },
    );
    return if (bad == 0) 0 else 1;
}

fn printDigest(w: *std.Io.Writer, dig: [32]u8) !void {
    const hex = "0123456789abcdef";
    for (dig) |b| {
        try w.writeByte(hex[b >> 4]);
        try w.writeByte(hex[b & 0x0f]);
    }
}

/// JSON-манифест: заголовок + все объекты (путь, тип, размер, дайджест).
pub fn inspect(alloc: std.mem.Allocator, path: []const u8) u8 {
    const data = load(alloc, path) orelse return 2;
    const h = headerOf(data) orelse return 1;

    var m = KernFS.mountFromBytesOwned(alloc, data) catch |e| {
        std.debug.print("[FAIL] монтирование: {s}\n", .{@errorName(e)});
        return 1;
    };
    defer m.deinit(alloc);

    var buf = compat.BufWriter.init(alloc);
    defer buf.deinit();
    const w = buf.writer();

    w.print("{{\"file\":\"{s}\",\"version\":\"{d}.{d}\",\"hash_algo\":{d}," ++
        "\"flags\":{d},\"object_count\":{d},\"objects\":[", .{
        path, h.version_major, h.version_minor, h.hash_algo, h.flags, m.fs.objects.len,
    }) catch return 2;

    for (m.fs.objects, 0..) |obj, i| {
        if (i > 0) w.writeAll(",") catch return 2;
        w.print("{{\"path\":\"{s}\",\"type\":{d},\"uncompressed_size\":{d}," ++
            "\"compressed_size\":{d},\"digest\":\"", .{
            m.fs.objectPath(obj), obj.type_id, obj.uncompressed_size, obj.compressed_size,
        }) catch return 2;
        printDigest(w, obj.digest) catch return 2;
        w.writeAll("\"}") catch return 2;
    }
    w.writeAll("]}\n") catch return 2;

    compat.fileWriteAll(std.Io.File.stdout(), buf.items()) catch return 2;
    return 0;
}

/// Посекционное сравнение двух образов: заголовок + объекты по путям.
pub fn diff(alloc: std.mem.Allocator, a_path: []const u8, b_path: []const u8) u8 {
    const a = load(alloc, a_path) orelse return 2;
    const b = load(alloc, b_path) orelse return 2;

    if (std.mem.eql(u8, a, b)) {
        std.debug.print("[SAME] {s} == {s} (побайтово)\n", .{ a_path, b_path });
        return 0;
    }

    const ha = headerOf(a) orelse return 1;
    const hb = headerOf(b) orelse return 1;
    std.debug.print("[DIFF] {s} vs {s}\n", .{ a_path, b_path });

    var same = true;
    if (ha.version_major != hb.version_major or ha.version_minor != hb.version_minor) {
        std.debug.print("  версия: {d}.{d} -> {d}.{d}\n", .{
            ha.version_major, ha.version_minor, hb.version_major, hb.version_minor,
        });
        same = false;
    }
    if (ha.flags != hb.flags) {
        std.debug.print("  флаги: 0x{X:0>8} -> 0x{X:0>8}\n", .{ ha.flags, hb.flags });
        same = false;
    }
    if (ha.hash_algo != hb.hash_algo) {
        std.debug.print("  hash_algo: {d} -> {d}\n", .{ ha.hash_algo, hb.hash_algo });
        same = false;
    }
    if (!std.crypto.timing_safe.eql([32]u8, ha.root_digest, hb.root_digest)) {
        std.debug.print("  Merkle-корень различается\n", .{});
        same = false;
    }
    if (ha.object_count != hb.object_count) {
        std.debug.print("  объектов: {d} -> {d}\n", .{ ha.object_count, hb.object_count });
        same = false;
    }

    var ma = KernFS.mountFromBytesOwned(alloc, a) catch |e| {
        std.debug.print("[FAIL] монтирование A: {s}\n", .{@errorName(e)});
        return 1;
    };
    defer ma.deinit(alloc);
    var mb = KernFS.mountFromBytesOwned(alloc, b) catch |e| {
        std.debug.print("[FAIL] монтирование B: {s}\n", .{@errorName(e)});
        return 1;
    };
    defer mb.deinit(alloc);

    for (ma.fs.objects) |oa| {
        var found = false;
        for (mb.fs.objects) |ob| {
            if (!std.mem.eql(u8, ma.fs.objectPath(oa), mb.fs.objectPath(ob))) continue;
            found = true;
            if (!std.crypto.timing_safe.eql([32]u8, oa.digest, ob.digest)) {
                std.debug.print("  объект изменён: {s}\n", .{ma.fs.objectPath(oa)});
                same = false;
            }
        }
        if (!found) {
            std.debug.print("  объект удалён: {s}\n", .{ma.fs.objectPath(oa)});
            same = false;
        }
    }
    for (mb.fs.objects) |ob| {
        var found = false;
        for (ma.fs.objects) |oa| {
            if (std.mem.eql(u8, ma.fs.objectPath(oa), mb.fs.objectPath(ob))) found = true;
        }
        if (!found) {
            std.debug.print("  объект добавлен: {s}\n", .{mb.fs.objectPath(ob)});
            same = false;
        }
    }

    return if (same) 0 else 1;
}
