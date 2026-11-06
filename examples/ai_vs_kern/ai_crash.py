# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# @kern:expect-violations — ДЕМО-ФИКСТУРА: краш НАМЕРЕННЫЙ (`make ai-demo`).
"""«ИИ-ассистент» посчитал средний чек — без защиты от пустой корзины."""


def average_check(total: int, count: int) -> int:
    """ДЫРА: при count == 0 — ZeroDivisionError в рантайме."""
    return total // count
