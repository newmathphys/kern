// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

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

pub fn writeFileAtomic(allocator: std.mem.Allocator, path: []const u8, data: []const u8) !void {
    const tmp = try std.fmt.allocPrint(allocator, "{s}.tmp", .{path});
    defer allocator.free(tmp);

    {
        const f = try std.fs.cwd().createFile(tmp, .{});
        errdefer std.fs.cwd().deleteFile(tmp) catch {};
        defer f.close();
        try f.writeAll(data);
        try f.sync(); // данные на носителе ДО подмены
    }

    errdefer std.fs.cwd().deleteFile(tmp) catch {};
    try std.fs.cwd().rename(tmp, path);

    // Долговечность записи в каталоге.
    const dfd = std.posix.open(".", .{ .ACCMODE = .RDONLY, .DIRECTORY = true }, 0) catch -1;
    if (dfd >= 0) {
        defer std.posix.close(dfd);
        std.posix.fsync(dfd) catch {};
    }
}

// =========================================================================
// ТЕСТЫ
// =========================================================================

test "ATOMIC: файл записан целиком, .tmp не остаётся" {
    const path = "/tmp/kern_atomic_test.txt";
    defer std.fs.cwd().deleteFile(path) catch {};
    try writeFileAtomic(std.testing.allocator, path, "hello atomic");

    const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, path, 4096);
    defer std.testing.allocator.free(data);
    try std.testing.expectEqualStrings("hello atomic", data);

    var tb: [64]u8 = undefined;
    const tmp = try std.fmt.bufPrint(&tb, "{s}.tmp", .{path});
    try std.testing.expectError(error.FileNotFound, std.fs.cwd().access(tmp, .{}));
}

test "ATOMIC: перезапись поверх — старое содержимое не смешивается с новым" {
    const path = "/tmp/kern_atomic_test2.txt";
    defer std.fs.cwd().deleteFile(path) catch {};
    try writeFileAtomic(std.testing.allocator, path, "AAAAAAAAAAAAAAAAAAAA");
    try writeFileAtomic(std.testing.allocator, path, "BB");
    const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, path, 4096);
    defer std.testing.allocator.free(data);
    // Без атомарности здесь могло остаться "BBAAAAAAAAAAAAAAAAAA".
    try std.testing.expectEqualStrings("BB", data);
}

test "ATOMIC: пустые данные — валидный пустой файл" {
    const path = "/tmp/kern_atomic_test3.txt";
    defer std.fs.cwd().deleteFile(path) catch {};
    try writeFileAtomic(std.testing.allocator, path, "");
    const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, path, 4096);
    defer std.testing.allocator.free(data);
    try std.testing.expectEqual(@as(usize, 0), data.len);
}
