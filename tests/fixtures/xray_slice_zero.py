# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later.
# РЕГРЕССИЯ #699: открытый срез `items[:n]` НЕ должен ронять --xray
# (`ast.unparse` давал ":n", `ast.parse(mode="eval")` падал SyntaxError).


def head_ratio(items, n):
    # срез + деление: при n == 0 деление на ноль
    head = items[:n]
    return sum(head) // n


def tail_ratio(items, n):
    # срез с двумя границами
    part = items[1:n]
    return sum(part) // (n - 1)
