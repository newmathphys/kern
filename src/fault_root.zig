// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

// Корень тестов ИНЪЕКЦИИ СБОЕВ ПАМЯТИ (SIGBUS/SIGSEGV).
//
// ОТДЕЛЬНО от src/test_root.zig: этот набор требует libc
// (sigsetjmp/siglongjmp) и намеренно ВЫЗЫВАЕТ аппаратные сбои памяти.
// Поэтому он собирается отдельной целью `zig build test-fault`.
test {
    _ = @import("tests/fault_injection_test.zig");
}
