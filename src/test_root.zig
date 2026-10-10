// Copyright (c) 2026 mrbritneyxxx. All rights reserved.
// Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.

// Корень модуля для прогона ВСЕХ тестов ядра.
//
// ЗАЧЕМ: документированная команда `zig test src/tests/exhaustive_suite.zig`
// НЕ РАБОТАЕТ — корнем модуля становится `src/tests/`, и импорты `../core/...`
// отвергаются как выход за пределы модуля. Обёртка в `src/` делает корнем `src/`.
test {
    _ = @import("core/eq2.zig");
    _ = @import("core/object_entry.zig");
    _ = @import("core/kimg_reader.zig");
    _ = @import("core/kernfs_router.zig");
    _ = @import("core/kimg_writer.zig");
    _ = @import("core/mmap_guard.zig");
    _ = @import("attest.zig");
    _ = @import("verifier/admission_gate.zig");
    _ = @import("verifier/z3_bridge.zig");
    _ = @import("runtime/kern_x.zig");
    _ = @import("proof_cache.zig");
    _ = @import("tests/exhaustive_suite.zig");
}
