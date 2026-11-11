# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# Двусторонний контроль --gen-tests: НАСТОЯЩАЯ недостижимость (UNSAT)
def dead_branch(x: int) -> int:
    if x > 0 and x < 0:
        return 1
    return 0
