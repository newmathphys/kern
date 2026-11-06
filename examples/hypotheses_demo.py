# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# @kern:expect-violations  — демо Ф6.3: контракт нарушен, гипотеза ЕСТЬ
"""Демонстрация read-only объяснений: `requires` не хватает границы.

Здесь у функции нет предусловия, поэтому `result >= 0` нарушается на x = -1.
Гипотеза `x >= 0` отсекает ИМЕННО этот контрпример и (важно) доказывает
контракт САМА, без исходного `requires` — то есть она самодостаточна.
"""


# @kern:ensures result >= 0
def identity_nonneg(x: int) -> int:
    return x
