# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
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


# ДЕФЕКТ #469b: НЕОПРЕДЕЛЁННОСТЬ ВНУТРИ ТЕЛА `while` — ТОЖЕ ЗАМЕТКА.
# ИЗМЕРЕНО на `deepseek-ai/DeepJIT` (`tests/test_ascend.py:162`, `worker`):
# `progress[0]` стоит внутри `while not finished.is_set():` и печаталось как
# НАХОДКА, хотя текст тот же — «длины НЕ известны». Причина: рекурсивный вызов
# `_walk_bounds` для ТЕЛА `while` НЕ передавал `notes`, поэтому `notes=None`,
# и ветка `#454` падала в `found`. Форма ровно как в DeepJIT — держим её
# фикстурой, чтобы «заметка против находки» проверялась И НА ЭТОМ пути.
def drain(progress, barrier):
    while not barrier.done():
        progress[0] += 1

