# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""ФИКСТУРА ДЛЯ --xray: ГОЛЫЙ код БЕЗ единой аннотации @kern:.

Здесь намеренно есть: мёртвая ветка, избыточная проверка и краш-путь.
"""


def dead_branch(x: int) -> int:
    if x > 10:
        return 1
    elif x > 10:  # НЕДОСТИЖИМА: перекрыта первым условием
        return 2
    return 3


def redundant_guard(x: int) -> int:
    if x > 10:
        if x > 5:  # ВСЕГДА истинно на пути x > 10
            return 1
    return 0


def crash_path(x: int, y: int) -> int:
    return x // y  # ДЕЛЕНИЕ НА НОЛЬ: y может быть 0


def clean(x: int) -> int:
    if x > 0:
        return x + 1
    return 0
