// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
//! KERN: слой совместимости Zig 0.13 -> 0.17 (`std.Io`).
//!
//! В Zig 0.17 файловый ввод-вывод переведён на интерфейс `std.Io`:
//! каждая операция требует явный параметр `io`, а `std.fs.cwd()` и
//! `std.io` удалены. Чтобы не пробрасывать `io` через сотни сигнатур,
//! KERN держит один процесс-глобальный `Io`, который устанавливается
//! в `main` (или берётся из `std.testing.io` в тестах).
//!
//! Контракт: `setIo()` ОБЯЗАН быть вызван в `main` до любого файлового
//! вызова. В тестах вызов не нужен — используется `std.testing.io`.

const std = @import("std");
const builtin = @import("builtin");

var g_io: ?std.Io = null;

/// Установить процесс-глобальный `Io` (вызывается из `main`).
pub fn setIo(io_val: std.Io) void {
    g_io = io_val;
}

/// Текущий `Io`: в CLI — установленный из `main(init)`, в тестах —
/// `std.testing.io`. Паникует, если ни то, ни другое не доступно.
pub fn io() std.Io {
    if (g_io) |v| return v;
    if (builtin.is_test) return std.testing.io;
    @panic("KERN: compat.setIo() не вызван в main до файлового вызова");
}

pub fn cwd() std.Io.Dir {
    return std.Io.Dir.cwd();
}

// ===== Файловые операции (замена старых `std.fs.cwd()`-вызовов) =====

pub fn readFileAlloc(alloc: std.mem.Allocator, path: []const u8, limit: usize) ![]u8 {
    return cwd().readFileAlloc(io(), path, alloc, .limited(limit));
}

pub fn writeFile(path: []const u8, data: []const u8) !void {
    return cwd().writeFile(io(), .{ .sub_path = path, .data = data });
}

pub fn deleteFile(path: []const u8) !void {
    return cwd().deleteFile(io(), path);
}

pub fn access(path: []const u8, options: std.Io.Dir.AccessOptions) !void {
    return cwd().access(io(), path, options);
}

pub fn createFile(path: []const u8, flags: std.Io.Dir.CreateFileOptions) !std.Io.File {
    return cwd().createFile(io(), path, flags);
}

pub fn rename(old_path: []const u8, new_path: []const u8) !void {
    return std.Io.Dir.rename(cwd(), old_path, cwd(), new_path, io());
}

/// Замена `compat.makePath()` — в 0.17 называется `createDirPath`.
pub fn makePath(path: []const u8) !void {
    return cwd().createDirPath(io(), path);
}

pub fn deleteTree(path: []const u8) !void {
    return cwd().deleteTree(io(), path);
}

pub fn openDir(path: []const u8, options: std.Io.Dir.OpenOptions) !std.Io.Dir {
    return cwd().openDir(io(), path, options);
}

// ===== Операции над открытым файлом =====

pub fn fileWriteAll(file: std.Io.File, bytes: []const u8) !void {
    return file.writeStreamingAll(io(), bytes);
}

pub fn fileClose(file: std.Io.File) void {
    file.close(io());
}

pub fn fileSync(file: std.Io.File) !void {
    return file.sync(io());
}

pub fn dirClose(dir: std.Io.Dir) void {
    dir.close(io());
}

/// Читает весь файл из уже открытого дескриптора (замена
/// `File.readToEndAlloc` из 0.13).
pub fn fileReadToEndAlloc(file: std.Io.File, alloc: std.mem.Allocator, limit: usize) ![]u8 {
    var buf: [64 * 1024]u8 = undefined;
    var list = std.array_list.Managed(u8).init(alloc);
    errdefer list.deinit();
    var offset: u64 = 0;
    while (true) {
        const n = try file.readPositionalAll(&buf, offset);
        if (n == 0) break;
        if (list.items.len + n > limit) return error.StreamTooLong;
        try list.appendSlice(buf[0..n]);
        offset += n;
    }
    return list.toOwnedSlice();
}

test "COMPAT: io доступен в тестах" {
    // В тестах io() обязан возвращать std.testing.io без setIo().
    const v = io();
    _ = v;
    try std.testing.expect(true);
}
