// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! Корень для `make storage-check` (Ф3): KIMG, KERNFS, кэш доказательств.
//! Модуль-корень здесь `src/`, поэтому `../cov.zig` внутри core/*.zig
//! резолвится штатно (Zig запрещает импорт вне корня модуля).
test {
    _ = @import("core/kimg_reader.zig");
    _ = @import("core/kernfs_router.zig");
    _ = @import("proof_cache.zig");
    _ = @import("runtime/kern_x.zig");
}
