# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ГЕРМЕТИЧНЫЙ НЕГАТИВНЫЙ КОНТРОЛЬ (#475): ЗДЕСЬ ВСЁ ЗАЩИЩЕНО — находок быть НЕ ДОЛЖНО.

Каждая функция — тот или иной ЛОЖНЫЙ класс, который KERN уже исправлял
(`#471a/b/c`, `#472`, `#473`, `#454`, `#179`). Гейт `make xray-precision`
требует: `находок 0`. Любая находка здесь — регресс: анализатор снова обвиняет
корректный код, а это худший класс исхода (ложное обвинение хуже пропуска).
"""


def div_if_return(a, b):
    """#471a: возврат в ветви THEN — путь ниже сужается к `b != 0`."""
    if b == 0:
        return 0
    return a // b


def div_if_else(a, b):
    """#471a: `else` обязан получать ОТРИЦАНИЕ условия `if`."""
    if b == 0:
        return 0
    else:
        return a // b


def div_while(a, b):
    """#471b: условие `while` — гард для тела."""
    while b != 0:
        return a // b
    return 0


def div_assert(a, b):
    """#179: `assert` — ИСТИННОЕ условие всего дальнейшего кода."""
    assert b != 0
    return a // b


def idx_assert_len(data):
    """#468: `assert len(x) == 1` — путевой гард для индексации."""
    assert len(data) == 1
    return data[0]


def idx_range_check(i):
    """#454: индекс под явной проверкой диапазона — не находка и не N."""
    data = [10, 20, 30]
    if 0 <= i < 3:
        return data[i]
    return 0


def idx_literal_guard(i):
    """#476: перенесено в `precision_known_fp/` — там функция в ПОЛНОМ виде.

    ⚠️ `--xray` обвиняет её ЛОЖНО: `len(data)` в гарде не связывается с
    литеральной длиной (дефект `#476`). Гейт `xray-precision` требует там РОВНО
    1 находку и обяжет перенести функцию сюда, когда дефект будет исправлен.
    Здесь — указатель, чтобы читатель `precision_clean` не искал пропажу.
    """
    return -1
