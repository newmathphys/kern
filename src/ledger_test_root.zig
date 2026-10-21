// Copyright (c) 2026 Vital Kalinousky. All rights reserved.
// Licensed under the PolyForm Noncommercial License 1.0.0.
// Commercial use requires a license from the copyright holder. See LICENSE.

//! Корень для `make ledger-check` (Фаза 2): журнал свидетельств + три графа.
test {
    _ = @import("next/evidence_ledger.zig");
    _ = @import("next/provenance.zig");
    _ = @import("next/truth.zig");
}
