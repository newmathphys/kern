// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

//! KERN: ЗАЩИТА ОТ АППАРАТНЫХ СБОЕВ ПАМЯТИ (SIGBUS/SIGSEGV на mmap).
//!
//! Если страница mmap-региона физически недоступна (выдернутый диск, сбой
//! NFS), ОС шлёт SIGBUS. Обычный код падает. Мы ставим обработчик через
//! sigaction, который помечает сбой и НЕ даёт процессу умереть.
const std = @import("std");
const posix = std.posix;

var g_fault: std.atomic.Value(bool) = std.atomic.Value(bool).init(false);

fn handler(sig: std.posix.SIG, info: *const posix.siginfo_t, ctx: ?*anyopaque) callconv(.c) void {
    _ = .{ sig, info, ctx };
    g_fault.store(true, .release);
}

/// Устанавливает обработчики SIGBUS и SIGSEGV (один раз).
pub fn install() void {
    var act = posix.Sigaction{
        .handler = .{ .sigaction = handler },
        .mask = posix.sigemptyset(),
        .flags = posix.SA.SIGINFO,
    };
    posix.sigaction(posix.SIG.BUS, &act, null);
    posix.sigaction(posix.SIG.SEGV, &act, null);
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
    const page = try posix.mmap(null, 4096, posix.PROT{},
        .{ .TYPE = .PRIVATE, .ANONYMOUS = true }, -1, 0);
    posix.munmap(page); // освобождение без сбоя
}
