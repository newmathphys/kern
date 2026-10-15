// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: АТОМАРНАЯ ЗАПИСЬ ФАЙЛА (crash-consistency, POSIX-семантика).
//!
//! ПРОБЛЕМА: `createFile(path)` + `writeAll` — НЕ атомарно. Если процесс
//! убьют (SIGKILL) или пропадёт питание посреди записи, на диске останется
//! ОБРЕЗАННЫЙ файл. Для кэша инкрементальной сборки это фатально: битый
//! кэш приведёт к неверному решению «файл не изменился».
//!
//! РЕШЕНИЕ (стандарт SQLite/PostgreSQL):
//!   1. пишем во временный файл `<path>.tmp`;
//!   2. `fsync` — данные ФИЗИЧЕСКИ на носителе (иначе rename может обогнать
//!      запись, и после сбоя файл окажется пустым);
//!   3. `rename` — атомарная подмена (POSIX гарантирует);
//!   4. `fsync` каталога — долговечность самой записи каталога.
//!
//! Итог: целевой файл ВСЕГДА либо старый целый, либо новый целый.
const std = @import("std");
const compat = @import("compat");

pub fn writeFileAtomic(allocator: std.mem.Allocator, path: []const u8, data: []const u8) !void {
    const tmp = try std.fmt.allocPrint(allocator, "{s}.tmp", .{path});
    defer allocator.free(tmp);

    {
        const f = try compat.createFile(tmp, .{});
        errdefer compat.deleteFile(tmp) catch {};
        defer compat.fileClose(f);
        try compat.fileWriteAll(f, data);
        try compat.fileSync(f); // данные на носителе ДО подмены
    }

    errdefer compat.deleteFile(tmp) catch {};
    try compat.rename(tmp, path);

    // Долговечность записи в каталоге.
    // Zig 0.17: `std.posix.open/close/fsync` удалены → `openat` + `Io.File`.
    const dfd = std.posix.openat(std.posix.AT.FDCWD, ".", .{ .ACCMODE = .RDONLY, .DIRECTORY = true }, 0) catch -1;
    if (dfd >= 0) {
        defer compat.fileClose(.{ .handle = dfd, .flags = .{ .nonblocking = false } });
        std.posix.fdatasync(dfd) catch {};
    }
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "ATOMIC: файл записан целиком, .tmp не остаётся" {
    const path = "/tmp/kern_atomic_test.txt";
    defer compat.deleteFile(path) catch {};
    try writeFileAtomic(std.testing.allocator, path, "hello atomic");

    const data = try compat.readFileAlloc(std.testing.allocator, path, 4096);
    defer std.testing.allocator.free(data);
    try std.testing.expectEqualStrings("hello atomic", data);

    var tb: [64]u8 = undefined;
    const tmp = try std.fmt.bufPrint(&tb, "{s}.tmp", .{path});
    try std.testing.expectError(error.FileNotFound, compat.access(tmp, .{}));
}

test "ATOMIC: перезапись поверх — старое содержимое не смешивается с новым" {
    const path = "/tmp/kern_atomic_test2.txt";
    defer compat.deleteFile(path) catch {};
    try writeFileAtomic(std.testing.allocator, path, "AAAAAAAAAAAAAAAAAAAA");
    try writeFileAtomic(std.testing.allocator, path, "BB");
    const data = try compat.readFileAlloc(std.testing.allocator, path, 4096);
    defer std.testing.allocator.free(data);
    // Без атомарности здесь могло остаться "BBAAAAAAAAAAAAAAAAAA".
    try std.testing.expectEqualStrings("BB", data);
}

test "ATOMIC: пустые данные — валидный пустой файл" {
    const path = "/tmp/kern_atomic_test3.txt";
    defer compat.deleteFile(path) catch {};
    try writeFileAtomic(std.testing.allocator, path, "");
    const data = try compat.readFileAlloc(std.testing.allocator, path, 4096);
    defer std.testing.allocator.free(data);
    try std.testing.expectEqual(@as(usize, 0), data.len);
}
