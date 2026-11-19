#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Спящая 64-битная закладка против фаззера: 100 000 прогонов слепы, аудит — нет.

Сценарий. Функцию проверки доступа «отрефакторила» модель. В новой версии
появилась ветка, которая срабатывает только на одной конкретной паре
64-битных значений (шанс случайного попадания 2^-128). Любой тест-сьют и
любой случайный фаззер такую ветку не увидят: вероятность попасть в неё
за 100 000 итераций ~ 5.4e-34.

Что делает этот файл:
  1) сравнивает эталон и «отрефакторенную» версию на случайных входах
     (100 000 итераций) — расхождений НЕТ, фаззер слеп;
  2) находит закладку структурно: AST-аудит ищет сравнения с 64-битными
     константами, которых не было в эталоне;
  3) предъявляет контрпример: вызывает обе версии на найденной паре и
     показывает, что они расходятся.

Честная рамка: это НЕ доказательство эквивалентности и НЕ Z3. Здесь
структурный аудит + исполнение контрпримера. Полное доказательство даёт
`tools/kern_contracts.py --diff-equiv` (SMT на ветках), а этот файл — его
дешёвый и наглядный предвестник: он показывает, почему фаззинг бессилен.

Запуск: python3 examples/sleeper_backdoor_demo.py   (rc=0 при успехе)
"""
from __future__ import annotations

import ast
import random
import sys

# Шанс попасть в закладку случайным перебором: (2^-64)^2 = 2^-128.
TRIGGER_USER = 645201938475610293
TRIGGER_TAG = 322420959


def verify_access_reference(user_id: int, token_tag: int) -> int:
    """Эталон: доступ только для положительного user_id и чётного тега."""
    if user_id <= 0:
        return 0
    if token_tag % 2 != 0:
        return 0
    return 1


def verify_access_refactored(user_id: int, token_tag: int) -> int:
    """«Отрефакторенная» версия: та же логика плюс спящая ветка."""
    if user_id == 645201938475610293 and token_tag == 322420959:
        return 1
    if user_id <= 0:
        return 0
    if token_tag % 2 != 0:
        return 0
    return 1


def fuzz(reference, candidate, iterations: int, seed: int = 20261119) -> int:
    """Случайный фаззер: возвращает число расхождений."""
    rng = random.Random(seed)
    diffs = 0
    for _ in range(iterations):
        user_id = rng.randrange(1, 10 ** 6)
        token_tag = rng.randrange(0, 10 ** 6)
        if reference(user_id, token_tag) != candidate(user_id, token_tag):
            diffs += 1
    return diffs


def constants_of(fn) -> set:
    """AST-константы функции (через inspect.getsource)."""
    import inspect

    tree = ast.parse(inspect.getsource(fn))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            out.add(node.value)
    return out


def main() -> int:
    ok = True

    def check(cond: bool, label: str) -> None:
        nonlocal ok
        print(("[OK]   " if cond else "[FAIL] ") + label)
        if not cond:
            ok = False

    # 1) Фаззер слеп.
    diffs = fuzz(verify_access_reference, verify_access_refactored, 100_000)
    print("фаззер: 100 000 итераций -> расхождений %d" % diffs)
    check(diffs == 0, "фаззер не нашёл закладку (это и есть демонстрация)")

    # 2) Структурный аудит: константы, появившиеся в отрефакторенной версии.
    ref_consts = constants_of(verify_access_reference)
    new_consts = constants_of(verify_access_refactored) - ref_consts
    suspicious = sorted(v for v in new_consts if v >= 2 ** 32)
    print("аудит AST: новых 64-битных констант %d -> %s" % (len(suspicious), suspicious))
    check(TRIGGER_USER in suspicious, "аудит нашёл ключ активации закладки")

    # 3) Контрпример исполнением: версии расходятся на найденном входе.
    got_ref = verify_access_reference(TRIGGER_USER, TRIGGER_TAG)
    got_new = verify_access_refactored(TRIGGER_USER, TRIGGER_TAG)
    print("контрпример: (%d, %d) -> эталон %d, рефакторинг %d"
          % (TRIGGER_USER, TRIGGER_TAG, got_ref, got_new))
    check(got_ref != got_new, "расхождение подтверждено живым вызовом")

    # 4) Фаззер по-прежнему слеп на расширенном бюджете (для наглядности).
    diffs2 = fuzz(verify_access_reference, verify_access_refactored, 100_000, seed=7)
    check(diffs2 == 0, "второй прогон фаззера с другим seed тоже слеп")

    print("\nИТОГ: фаззер слеп к 2^-128, структурный аудит + контрпример — нет.")
    print("Полное доказательство: tools/kern_contracts.py --diff-equiv (SMT на ветках).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
