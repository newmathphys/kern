// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

// Корень тестов ИНЪЕКЦИИ СБОЕВ ПАМЯТИ (SIGBUS/SIGSEGV).
//
// ОТДЕЛЬНО от src/test_root.zig: этот набор требует libc
// (sigsetjmp/siglongjmp) и намеренно ВЫЗЫВАЕТ аппаратные сбои памяти.
// Поэтому он собирается отдельной целью `zig build test-fault`.
test {
    _ = @import("tests/fault_injection_test.zig");
}
