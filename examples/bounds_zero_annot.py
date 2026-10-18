# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ПУНКТ 21 (Zero-Annotation): НИ ОДНОЙ директивы KERN в этом файле!
# Длина массива берётся из САМОГО КОДА: литерал списка либо `len(arr)` в условиях.


def get_literal(i):
    data = [10, 20, 30, 40]     # длина 4 видна прямо из AST
    return data[i]


def get_symbolic_safe(data, i):
    if i < 0:
        return 0
    if i >= len(data):          # символическая длина kern_len_data >= 0
        return 0
    return data[i]


def get_symbolic_bad(data, i):
    if i >= len(data):
        return 0
    return data[i]              # нет проверки i < 0
