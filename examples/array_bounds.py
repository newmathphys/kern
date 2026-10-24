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


# ДЕФЕКТ #322: ГАРД В УСЛОВНОМ ВЫРАЖЕНИИ. Тернарник — это гард СВОЕЙ ветви:
# `xs[0]` выполняется только когда `xs` непуст, поэтому обвинять нельзя.
def get_ifexp_guard(xs):
    return xs[0] if xs else 0


# ДЕФЕКТ #322: РАННИЙ ВЫХОД `continue` — тоже гард. До правки `_block_exits`
# не считал `continue` выходом, и `src[lineno - 1]` обвинялся контрпримером
# `lineno = 0`, который этот самый гард и исключает.
def get_continue_guard(src, pairs):
    out = []
    for lineno, _p in pairs:
        if not (1 <= lineno <= len(src)):
            continue
        out.append(src[lineno - 1])
    return out


# ДЕФЕКТ #322 (в связке с #315): индекс зависит от переменной, изменённой в
# ЦИКЛЕ, — инвариант не моделируется, поэтому вердикт обязан быть честным
# `[BOUNDS UNKNOWN]`, а НЕ обвинением с недостижимым свидетелем (`i = -1`).
def get_loop_index(lines):
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    return lines[i] if i < len(lines) else ""
