# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ЭШЕЛОН 4, ПУНКТ 21: границы массивов `arr[i]` БЕЗ аннотаций @kern:.
#
# Длина массива сообщается метаданными `# @kern:len(data) = 8`; обязательство
# безопасности `0 <= i < 8` выставляется автоматически С УЧЁТОМ путевых условий.

# @kern:len(data) = 8
def get_unsafe(data, i):
    return data[i]          # БЕЗ гарда -> выход за границы ВОЗМОЖЕН


# @kern:len(data) = 8
def get_safe(data, i):
    if i < 0:
        return 0
    if i >= 8:
        return 0
    return data[i]          # под гардами -> безопасно


# @kern:len(data) = 4
def get_unknown_len(other, j):
    return other[j]         # длина other НЕ объявлена -> честное «НЕ проверено»
