// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ИНЪЕКЦИЯ АППАРАТНЫХ СБОЕВ ПАМЯТИ (реальный SIGBUS/SIGSEGV).
//!
//! Проверяем, что KERN НЕ умирает, когда mmap-регион физически недоступен:
//!   1) страница с PROT_NONE;
//!   2) файл, обрезанный ПОСЛЕ mmap (симуляция выдернутого носителя).
//!
//! Требует libc (sigsetjmp/siglongjmp) — отдельная цель сборки: `make test-fault`.
const std = @import("std");
const posix = std.posix;
const sigbus = @import("../core/sigbus_guard.zig");
const compat = @import("compat");

test "SIGBUS РЕАЛЬНЫЙ: чтение PROT_NONE перехвачено, процесс жив" {
    if (@import("builtin").os.tag != .linux) return;
    sigbus.install();
    const before = sigbus.faultCount();

    const page = try posix.mmap(null, 4096, posix.PROT.NONE,
        .{ .TYPE = .PRIVATE, .ANONYMOUS = true }, -1, 0);
    defer posix.munmap(page);

    const bytes: [*]const u8 = @ptrCast(page.ptr);
    var caught = false;
    if (sigbus.setJump()) {
        const v: *volatile const u8 = @ptrCast(bytes);
        _ = v.*; // АППАРАТНЫЙ СБОЙ
        sigbus.clearJump();
    } else {
        caught = true;
        sigbus.clearJump();
    }
    try std.testing.expect(caught);
    try std.testing.expect(sigbus.faultCount() > before);

    // Процесс жив и память работает: обычный доступ не пострадал.
    var ok: [64]u8 = undefined;
    @memset(&ok, 0xAB);
    try std.testing.expectEqual(@as(u8, 0xAB), ok[63]);
}

test "SIGBUS РЕАЛЬНЫЙ: файл, обрезанный после mmap (выдернутый носитель)" {
    if (@import("builtin").os.tag != .linux) return;
    sigbus.install();
    const before = sigbus.faultCount();

    // 1. Создаём файл на 2 страницы и отображаем его в память.
    const path = "/tmp/kern_sigbus_probe.bin";
    var f = try compat.createFile(path, .{ .read = true, .truncate = true });
    defer compat.fileClose(f);
    defer compat.deleteFile(path) catch {};
    try f.setEndPos(8192);
    try compat.fileWriteAll(f, &(@as([8192]u8, @splat(0x5A))));

    const mapped = try posix.mmap(null, 8192, posix.PROT.READ, .{ .TYPE = .SHARED }, f.handle, 0);
    defer posix.munmap(mapped);

    // 2. «Выдёргиваем носитель»: обрезаем файл до нуля при живом отображении.
    try posix.ftruncate(f.handle, 0);

    // 3. Чтение второй страницы обязано дать SIGBUS — и быть перехваченным.
    const base: [*]const u8 = @ptrCast(mapped.ptr);
    var caught = false;
    if (sigbus.setJump()) {
        const far: *volatile const u8 = @ptrCast(base + 4096);
        _ = far.*;
        sigbus.clearJump();
    } else {
        caught = true;
        sigbus.clearJump();
    }
    try std.testing.expect(caught);
    try std.testing.expect(sigbus.faultCount() > before);
}
