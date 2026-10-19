# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 5, ПУНКТ 27: финансовый анти-арбитраж (`@kern:no_arbitrage`).
# Обязательство: `fee(a1) + fee(a2) >= fee(a1 + a2)` для всех a1 > 0, a2 > 0 —
# то есть дробление платежа НЕ должно быть выгоднее целого (кража копеек на
# округлении или обход порога).
# Ожидания приёмки (`make arbitrage-check`):
#   REFUTED: fee_threshold (фиксированная комиссия выше порога -> дробим),
#            fee_floor_capped (потолок + floor -> обход),
#   PROVEN : fee_proportional (линейная комиссия).


# @kern:no_arbitrage
def fee_threshold(amount):
    if amount > 100:
        return 1
    return 0


# @kern:no_arbitrage
def fee_floor_capped(amount):
    if amount > 1000:
        return 30
    return amount // 100


# @kern:no_arbitrage
def fee_proportional(amount):
    return amount * 3
