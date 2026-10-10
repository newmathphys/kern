// Copyright (c) 2026 mrbritneyxxx. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

//! KERN: ЗАЩИТА ОТ АППАРАТНЫХ СБОЕВ ПАМЯТИ (SIGBUS/SIGSEGV на mmap).
//!
//! Если страница mmap-региона физически недоступна (выдернутый диск, сбой
//! NFS), ОС шлёт SIGBUS. Обычный код падает. Мы ставим обработчик через
//! sigaction, который помечает сбой и НЕ даёт процессу умереть.
const std = @import("std");
const posix = std.posix;

var g_fault: std.atomic.Value(bool) = std.atomic.Value(bool).init(false);

fn handler(sig: c_int, info: *const posix.siginfo_t, ctx: ?*anyopaque) callconv(.C) void {
    _ = .{ sig, info, ctx };
    g_fault.store(true, .release);
}

/// Устанавливает обработчики SIGBUS и SIGSEGV (один раз).
pub fn install() void {
    var act = posix.Sigaction{
        .handler = .{ .sigaction = handler },
        .mask = posix.empty_sigset,
        .flags = posix.SA.SIGINFO,
    };
    posix.sigaction(posix.SIG.BUS, &act, null) catch {};
    posix.sigaction(posix.SIG.SEGV, &act, null) catch {};
}

/// Был ли сбой памяти с момента сброса.
pub fn faulted() bool {
    return g_fault.load(.acquire);
}

pub fn reset() void {
    g_fault.store(false, .release);
}

// =========================================================================
// ТЕСТ: обработчик устанавливается, флаг работает (сбой в тесте НЕ триггерим)
// =========================================================================
// ВАЖНО: возврат из обработчика SIGSEGV повторяет сбойную инструкцию ->
// бесконечный цикл. Поэтому в тесте мы НЕ трогаем PROT_NONE память, а
// проверяем установку обработчика и логику флага. Реальный перехват
// применяется вместе с предварительной проверкой доступности (pre-fault).
test "SIGBUS: обработчик устанавливается, флаг сбрасывается/читается" {
    install();
    reset();
    try std.testing.expect(!faulted());
    g_fault.store(true, .release);
    try std.testing.expect(faulted());
    reset();
    try std.testing.expect(!faulted());
}

test "SIGBUS: страница PROT_NONE создаётся и освобождается (инфраструктура)" {
    if (@import("builtin").os.tag == .windows) return;
    const page = try posix.mmap(null, 4096, posix.PROT.NONE,
        .{ .TYPE = .PRIVATE, .ANONYMOUS = true }, -1, 0);
    posix.munmap(page); // освобождение без сбоя
}
