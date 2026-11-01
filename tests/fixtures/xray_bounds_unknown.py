# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
# ФИКСТУРА ДЛЯ ДЕФЕКТА #454: индекс в список НЕИЗВЕСТНОЙ длины.
#
# Ожидание: это НЕОПРЕДЕЛЁННОСТЬ (Белнап N) -> ЗАМЕТКА `note: [BOUNDS?]`,
# а НЕ находка. До #454 маркер `[BOUNDS]` шёл в находки, и на чистом корпусе
# QuixBugs это давало 81 «находку» против 80 на багованном — сигнала не было.


def tally(arr, k):
    counts = [0] * k
    for x in arr:
        counts[x] += 1
    return counts
