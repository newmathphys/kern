// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
// (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.

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
}