// Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
// KERN positive control for tools/xray_asi_check.py: a GENUINE dead branch.
// Under `x > 0` the inner `x < 0` is unreachable; the detector MUST still
// report it — otherwise the ASI gate would be vacuous.
int kern_dead_branch_control(int x) {
    if (x > 0) {
        if (x < 0) {
            return 1;
        }
    }
    return 0;
}
