// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! Корень для `make axes-check` (Фаза 1): семь осей + привязка типа запроса.
//!
//! Почему отдельный корень, а не `zig test src/next/state_axes.zig`:
//! `admission_gate.zig` импортирует `../core/eq2.zig` и `../cov.zig`, а Zig
//! запрещает импорт вне корня модуля. Корень здесь — `src/`, поэтому оба
//! файла собираются штатно.
test {
    _ = @import("next/state_axes.zig");
    _ = @import("verifier/admission_gate.zig");
}
