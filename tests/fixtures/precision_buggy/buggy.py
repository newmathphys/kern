# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ГЕРМЕТИЧНЫЙ КОНТРОЛЬ ПОЛНОТЫ (#475): здесь НАСТОЯЩИЕ ошибки.

Каждая функция обязана быть найдена: пропуск здесь — потеря сигнала (FN), то есть
«анализатор молчит на багованном коде». Гейт `make xray-precision` требует
`находок N` и присутствия КАЖДОГО имени ниже.
"""


def div_unguarded(a, b):
    """Деление без гарда — обязан быть [CRASH PATH]."""
    return a // b


def idx_unguarded_literal(i):
    """Литеральная длина + свободный индекс — обязан быть [BOUNDS PATH]."""
    data = [10, 20, 30]
    return data[i]


def mod_unguarded(a, b):
    """Остаток без гарда — тот же делитель, отдельная функция для счёта."""
    return a % b
