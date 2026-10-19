# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 5, ПУНКТ 26: однословные пресеты — БЕЗ формул, только слово над def.
# Ожидания приёмки (`make presets-check`):
#   PROVEN : clamp_nonneg, discount, clamp_idem, tax_smooth
#   REFUTED: pct_buggy (выход > 100), tax_step (обратная ступенька)
#   SPEC GAP: price (нет верхней границы + открытая отрицательная область)


# @kern:non_negative
def clamp_nonneg(x):
    if x < 0:
        return 0
    return x


# @kern:percentage
def pct_buggy(x):
    return x * 2


# @kern:requires x >= 0
# @kern:bounded(0, x)
def discount(x):
    if x < 0:
        return 0
    return x


# @kern:idempotent
def clamp_idem(x):
    if x < 0:
        return 0
    if x > 100:
        return 100
    return x


# @kern:monotonic
def tax_smooth(income):
    return income


# @kern:monotonic
def tax_step(income):
    if income > 1000:
        return income - 500
    return income


# @kern:non_negative
def price(qty):
    return qty * 10
