# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# @kern:expect-violations — ДЕМО-ФИКСТУРА: краш НАМЕРЕННЫЙ (`make ai-demo`).
"""«ИИ-ассистент» посчитал средний чек — без защиты от пустой корзины."""


def average_check(total: int, count: int) -> int:
    """ДЫРА: при count == 0 — ZeroDivisionError в рантайме."""
    return total // count
