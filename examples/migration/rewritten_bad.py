# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ПЕРЕПИСКА, КОТОРАЯ МОЛЧА ЛОМАЕТ ПОВЕДЕНИЕ (так делает агент).

Поменяли порядок проверок и границы: при lo > hi старая версия
возвращала lo (первое сработавшее условие), новая — hi.
Юнит-тесты на «нормальных» входах (lo < hi) этого не видят.
"""


def clamp_value(x: int, lo: int, hi: int) -> int:
    if x > hi:
        return hi
    if x < lo:
        return lo
    return x
