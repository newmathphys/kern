# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 5, ПУНКТ 31: тарифные матрицы. Цель `make pricing-matrix-check`.
# Ожидания: price_gap -> PRICING GAP (цена-признак «не обработано» = -1),
#           price_conflict -> PRICING CONFLICT (правила с разными ценами пересекаются),
#           price_safe -> PROVEN COMPLETE & DISJOINT.


# @kern:pricing(age)
def price_gap(age):
    if age < 18:
        return 10
    if age >= 65:
        return 5
    return -1


# @kern:pricing(tier)
def price_conflict(tier):
    if tier <= 3:
        return 100
    if tier >= 2:
        return 200
    return 0


# @kern:pricing(age)
def price_safe(age):
    if age < 18:
        return 10
    if age >= 18 and age < 65:
        return 20
    return 5
