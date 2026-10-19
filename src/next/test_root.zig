// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

// Корень модуля для прогона ВСЕХ тестов KERN-Next (src/next/).
// Запуск: zig build test-next  (требует libc + libsqlite3).
test {
    _ = @import("ast.zig");
    _ = @import("parser.zig");
    _ = @import("validate.zig");
    _ = @import("catalog.zig");
    _ = @import("snapshot.zig");
    _ = @import("truth.zig");
    _ = @import("export.zig");
    _ = @import("cache.zig");
    _ = @import("engine.zig");
_ = @import("dst_sim.zig");
}