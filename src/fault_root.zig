// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

// Корень тестов ИНЪЕКЦИИ СБОЕВ ПАМЯТИ (SIGBUS/SIGSEGV).
//
// ОТДЕЛЬНО от src/test_root.zig: этот набор требует libc
// (sigsetjmp/siglongjmp) и намеренно ВЫЗЫВАЕТ аппаратные сбои памяти.
// Поэтому он собирается отдельной целью `zig build test-fault`.
test {
    _ = @import("tests/fault_injection_test.zig");
}
