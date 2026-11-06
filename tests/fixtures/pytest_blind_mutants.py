# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
#
# ИСПЫТАНИЕ 3: «ВЫЖИВШИЕ МУТАНТЫ ЗА СПИНОЙ pytest» (Mutation Kill Delta).
#
# ЗАЧЕМ ЭТОТ ФАЙЛ. Тезис проекта — «зелёный pytest != верный код» — до сих
# пор был подтверждён только на СИНТАКСИЧЕСКИХ читах (anti_cheat_demo.py), а не
# на ЛОГИЧЕСКИХ ошибках. Здесь каждая функция несёт ЯВНЫЙ контракт `@kern:` и
# пару обычных тестов, которые проходят на «типичных» входах и НЕ покрывают
# границу. Гейт `tools/pytest_blind_check.py` подменяет в теле одну строку
# (мутацию), убеждается, что pytest остаётся ЗЕЛЁНЫМ, а kern — КРАСНЫМ.
#
# ВАЖНО: тесты написаны СЛАБЫМИ НАМЕРЕННО (только «нормальные» значения) —
# это и есть модель реального проекта, где тестов «на счастливый путь»
# достаточно для зелёного CI, но недостаточно для вердикта «код верен».

import pytest  # noqa: F401  (нужен, чтобы файл был pytest-совместимым)


# --- M1: СДВИГ ГРАНИЦЫ `<` -> `<=` -----------------------------------------
# @kern:requires 0 <= x and x <= 100
# @kern:ensures result == (0 if x < 50 else 1)
def grade(x):
    if x < 50:
        return 0
    return 1


def test_grade_typical():
    assert grade(10) == 0
    assert grade(90) == 1


# --- M2: ПОТЕРЯ ГАРДА ДЕЛЕНИЯ НА НОЛЬ --------------------------------------
# @kern:requires -1000 <= a and a <= 1000 and -1000 <= b and b <= 1000
# @kern:ensures result == (0 if b == 0 else a // b)
def safe_div(a, b):
    if b == 0:
        return 0
    return a // b


def test_safe_div_typical():
    assert safe_div(10, 2) == 5
    assert safe_div(100, 10) == 10


# --- M3: ОШИБКА ОКРУГЛЕНИЯ КОМИССИИ ----------------------------------------
# @kern:requires 0 <= amount and amount <= 1000000
# @kern:ensures result == (amount + 50) // 100
def commission(amount):
    return (amount + 50) // 100


def test_commission_typical():
    assert commission(100) == 1
    assert commission(1000) == 10


# --- M4: ОШИБКА ГРАНИЦЫ КЛАМПА (ПЕРЕПОЛНЕНИЕ НА БОЛЬШИХ ВХОДАХ) -------------
# @kern:requires 0 <= x and x <= 100000
# @kern:ensures result == (x if x < 1000 else 1000)
def clamp(x):
    if x < 1000:
        return x
    return 1000


def test_clamp_typical():
    assert clamp(5) == 5
    assert clamp(999) == 999


# --- M5: ПОТЕРЯ ПРОВЕРКИ НА ОТРИЦАТЕЛЬНЫЙ ВХОД -----------------------------
# @kern:requires -100 <= x and x <= 100
# @kern:ensures result == (0 - x if x < 0 else x)
def magnitude(x):
    if x < 0:
        return 0 - x
    return x


def test_magnitude_typical():
    assert magnitude(7) == 7
    assert magnitude(0) == 0
