# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 4, ПУНКТ 20: тотальная корректность циклов (Флойд - Хоар).


# @kern:requires n >= 0
# @kern:ensures result == n
# @kern:invariant i <= n and i >= 0
# @kern:decreases n - i
def count_up(n):
    i = 0
    while i < n:
        i = i + 1
    return i


# @kern:requires n >= 0
# @kern:ensures result == n
# @kern:invariant i <= n - 1
# @kern:decreases n - i
def count_up_bad_inv(n):
    i = 0
    while i < n:
        i = i + 1
    return i


# @kern:requires n >= 0
# @kern:ensures result == n
# @kern:invariant i >= 0
# @kern:decreases n - i
def count_up_no_terminate(n):
    i = 0
    while i < n:
        i = i - 1
    return i
