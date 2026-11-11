# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""LEGACY: ограничение значения диапазоном (классика для миграции).

Закон здесь НЕ пишет человек: он универсален —
    ∀x, lo, hi:  f_old(x, lo, hi) == f_new(x, lo, hi)
Именно это проверяет `--diff-equiv`.
Арифметика линейная (сравнения и выбор), поэтому вердикт проверяем.
"""


def clamp_value(x: int, lo: int, hi: int) -> int:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
