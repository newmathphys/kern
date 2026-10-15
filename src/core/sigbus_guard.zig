// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! KERN: РЕАЛЬНЫЙ ПЕРЕХВАТ SIGBUS/SIGSEGV на mmap (siglongjmp).
//!
//! ПРОБЛЕМА: если страница mmap-региона физически недоступна (выдернутый
//! носитель, сбой NFS, обрезанный файл), ОС шлёт SIGBUS. Обычный код падает.
//! Простой обработчик НЕ решает задачу: возврат из обработчика ПОВТОРЯЕТ
//! сбойную инструкцию → бесконечный цикл.
//!
//! РЕШЕНИЕ: `siglongjmp` из обработчика — не возвращаемся, а прыгаем назад
//! к точке `setJump()`. Это стандартная техника обработки аппаратных сбоев
//! памяти. Требует libc (`sigsetjmp`/`siglongjmp`), поэтому этот модуль
//! НЕ входит в базовый набор тестов ядра (см. цель `make test-fault`).
//!
//! Использование:
//!     sigbus.install();
//!     if (sigbus.setJump()) {
//!         _ = risky_ptr[0];      // может сбоить
//!         sigbus.clearJump();    // сбоя не было
//!     } else {
//!         // сбой ПЕРЕХВАЧЕН: процесс жив, состояние откатано
//!     }
const std = @import("std");
const posix = std.posix;

/// Буфер `sigjmp_buf`. glibc x86_64: `struct __jmp_buf_tag` = 200 байт.
/// Берём 256 с выравниванием 16 — с запасом и по ABI.
pub const JmpBuf = extern struct { data: [256]u8 align(16) };

// В glibc `sigsetjmp` — МАКРОС; реальный символ называется `__sigsetjmp`.
extern fn __sigsetjmp(env: *JmpBuf, savesigs: c_int) c_int;
extern fn siglongjmp(env: *JmpBuf, val: c_int) noreturn;

var g_jmpbuf: JmpBuf = undefined;
var g_jmp: ?*JmpBuf = null;
var g_faults: std.atomic.Value(u32) = std.atomic.Value(u32).init(0);

fn handler(sig: posix.SIG, info: *const posix.siginfo_t, ctx: ?*anyopaque) callconv(.c) void {
    _ = .{ sig, info, ctx };
    _ = g_faults.fetchAdd(1, .monotonic);
    if (g_jmp) |j| {
        // Прыжок назад: НЕ возвращаемся (иначе повторим сбойную инструкцию).
        siglongjmp(j, 1);
    }
    // Нет точки возврата — ничего не делаем (процесс получит сбой повторно).
}

/// Устанавливает обработчики SIGBUS и SIGSEGV (один раз на процесс).
pub fn install() void {
    var act = posix.Sigaction{
        .handler = .{ .sigaction = handler },
        .mask = posix.sigemptyset(),
        .flags = posix.SA.SIGINFO,
    };
    posix.sigaction(posix.SIG.BUS, &act, null);
    posix.sigaction(posix.SIG.SEGV, &act, null);
}

/// Установить точку возврата. `true` — обычный ход; `false` — вернулись из сбоя.
pub fn setJump() bool {
    g_jmp = &g_jmpbuf;
    return __sigsetjmp(&g_jmpbuf, 1) == 0;
}

/// Снять точку возврата (после успешного прохода).
pub fn clearJump() void {
    g_jmp = null;
}

/// Сколько сбоев памяти перехвачено за время жизни процесса.
pub fn faultCount() u32 {
    return g_faults.load(.acquire);
}
