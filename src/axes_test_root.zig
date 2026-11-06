// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md

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
