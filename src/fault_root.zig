// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md

// Корень тестов ИНЪЕКЦИИ СБОЕВ ПАМЯТИ (SIGBUS/SIGSEGV).
//
// ОТДЕЛЬНО от src/test_root.zig: этот набор требует libc
// (sigsetjmp/siglongjmp) и намеренно ВЫЗЫВАЕТ аппаратные сбои памяти.
// Поэтому он собирается отдельной целью `zig build test-fault`.
test {
    _ = @import("tests/fault_injection_test.zig");
}
