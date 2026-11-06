// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md

//! Корень для `make ledger-check` (Фаза 2): журнал свидетельств + три графа.
test {
    _ = @import("next/evidence_ledger.zig");
    _ = @import("next/provenance.zig");
    _ = @import("next/truth.zig");
}
