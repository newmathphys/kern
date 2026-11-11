# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ЧИСТАЯ переписка: то же поведение одной строкой."""


def clamp_value(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else hi if x > hi else x
