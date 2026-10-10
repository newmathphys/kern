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