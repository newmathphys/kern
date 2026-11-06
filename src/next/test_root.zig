// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md

// Корень модуля для прогона ВСЕХ тестов KERN-Next (src/next/).
// Запуск: zig build test-next  (требует libc + libsqlite3).
test {
    _ = @import("ast.zig");
    _ = @import("parser.zig");
    _ = @import("validate.zig");
    _ = @import("catalog.zig");
    _ = @import("snapshot.zig");
    _ = @import("truth.zig");
    _ = @import("state_axes.zig");
    _ = @import("export.zig");
    _ = @import("cache.zig");
    _ = @import("engine.zig");
_ = @import("dst_sim.zig");
}