# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# @kern:expect-violations — ДЕМО-ФИКСТУРА: арбитраж НАМЕРЕННЫЙ (`make ai-demo`).
"""Комиссии, «сгенерированные ИИ»: пороговая дыра и линейный эталон.

`@kern:no_arbitrage` требует субаддитивности: `fee(a1) + fee(a2) >= fee(a1+a2)`.
Пороговая комиссия это нарушает — клиент дробит платёж 98 на 49 + 49 и
платит 0 вместо 1. Линейная комиссия субаддитивна и доказуема.
"""


# @kern:no_arbitrage
def fee_threshold(amount):
    """ДЫРА: фиксированная комиссия выше порога -> выгодно дробить."""
    if amount > 100:
        return 1
    return 0


# @kern:no_arbitrage
def fee_proportional(amount):
    """Эталон: линейная комиссия (субаддитивна по построению)."""
    return amount * 3
