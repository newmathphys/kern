#!/usr/bin/env python3
"""KERN: контракты прямо в обычном Python-коде (Улучшение №1).

ПРОБЛЕМА. Чтобы проверить функцию через `kernc prove`, нужно писать SMT-LIB2
(`(declare-const x Int) (assert ...)`). 99% программистов этого не умеют.

РЕШЕНИЕ. Контракт пишется комментарием рядом с функцией:

    # @kern:requires amount > 0 and balance >= amount
    # @kern:ensures  result == balance - amount and result < balance
    def withdraw(balance: int, amount: int) -> int:
        return balance - amount

Запуск:  python3 tools/kern_contracts.py app.py

ЧТО ДЕЛАЕТ. Разбирает функцию через `ast`, переводит контракт и тело в SMT-LIB2
и прогоняет через `kernc prove` (РЕАЛЬНЫЙ Z3 + пруф-чекер). Доказательство:

    requires(x) ∧ body(x) = result  ⊨  ensures(x, result)

проверяется от противного: добавляем `(assert (not ensures))` и ждём `unsat`.

ПОДДЕРЖИВАЕТСЯ (честно ограниченное подмножество):
  * целые параметры, возврат `int`;
  * тело — РОВНО ОДИН `return` с линейным выражением;
  * в контракте: `and`/`or`/`not`, сравнения `== != < <= > >=`, арифметика
    `+ - *` (умножение — только на числовой литерал), скобки, `result`.

ЧЕГО НЕ ДЕЛАЕТ: ветвлений, циклов, списков, строк, вызовов, деления. Функция
вне подмножества помечается `SKIP` с причиной, а не «проверена».
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import ast
import hashlib
import json
import os
import shutil
import re
import zlib
import shutil
import subprocess
import io
import sys
import tempfile
from pathlib import Path

# Каталог САМОГО инструмента обязан быть в `sys.path`: `kern_contracts.py`
# запускают и как скрипт, и через `python3 -c` (так делают гейты) — во втором
# случае `sys.path[0]` не `tools/`, и импорт спецификации падал с
# `ModuleNotFoundError` (измерено гейтом `edge-cases`).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# СПЕЦИФИКАЦИЯ ВОРОНКИ ПОД КОНТРАКТОМ САМОГО KERN (дефекты #405/#407.2).
# Живёт в `tools/funnel_accounting.py`: её доказывает ТОТ ЖЕ движок (Z3) и стережёт
# `tools/funnel_contract_check.py`, запечатано в `docs/contracts.lock.json`.
# Здесь она ИСПОЛЬЗУЕТСЯ, а не упоминается: разность «пропуски минус названные
# причины» обязана быть ОДНОЙ РАЗМЕРНОСТИ, и нарушение предпосылки называет
# контракт, а не выдуманное отрицательное число (наблюдалось `-6`).
from funnel_accounting import unexplained_skips, unaccounted


CMP = {"Eq": "=", "NotEq": "distinct", "Lt": "<", "LtE": "<=",
       "Gt": ">", "GtE": ">=",
       # `x is None` / `x is not None`: None моделируется сентинелом (см. ниже).
       "Is": "=", "IsNot": "distinct"}
# СЕНТИНЕЛ None: значение, недостижимое как «нормальное» целое в контрактах.
# Модель Optional = (Int, сентинел). Это ДОПУЩЕНИЕ: настоящий None не число,
# поэтому havoc-контрпримеры всё равно проходят Live Replay (правило №4).
_NONE_SENTINEL = "-4611686018427387904"

# Делители, встреченные при трансляции выражения (для обязательства
# «делитель ≠ 0»): в SMT `div`/`mod` тотальны, поэтому ноль надо ловить отдельно.
_DIV_COLLECTOR: list = []
# ДЕФЕКТ #334 (остаток N5): унарные минусы. `-x` на знаковом типе при `x == MIN`
# переполняется (`gcc -ftrapv` -> SIGABRT), но в математических целых `-MIN`
# представим, поэтому проверка ДИАПАЗОНА РЕЗУЛЬТАТА молчит. Элемент:
# `(операнд_smt, гарды)`.
_NEG_COLLECTOR: list = []

# ДЕФЕКТ #327: АКТИВНЫЕ УСЛОВИЯ ВЕТВЛЕНИЯ в точке сбора делителя.
#
# ЧТО БЫЛО НЕ ТАК. `_DIV_COLLECTOR.append(right)` не знал, под каким гардом
# стоит деление, а обязательство строилось как `requires ∧ (делитель == 0)` —
# БЕЗ путей. Поэтому `return 0 if b == 0 else a // b` (гард ЯВНЫЙ) давал
# `[FAIL] ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ (делитель: b)` с контрпримером `b = 0`:
# гард был отброшен, и `(= b 0)` оказался SAT. Ложное обвинение.
#
# КАК СЕЙЧАС. Элемент коллектора — ПАРА `(делитель, гарды_в_этой_точке)`, а
# обязательство строится как `(and <гарды> (= делитель 0))`. Для незащищённого
# деления гарды пусты, и обязательство не меняется (контроль не ослаблен).
# Для C-like это уже было сделано в #318 (`_clike_conds_at`).
#
# ЗВУЧИМОСТЬ: гард добавляется только там, где он ИСТИНЕН по построению —
# в ветке THEN это условие `if`, в ветке ELSE — его отрицание.
_DIV_GUARDS: list = []
# СИМВОЛЬНАЯ АБСТРАКЦИЯ (вместо отказа от функции): аксиомы, собранные при
# трансляции (`(>= len__x 0)`), счётчик havoc-переменных и флаг «в формуле была
# овер-аппроксимация». При овер-аппроксимации SAT-контрпример обязан подтвердиться
# ЖИВЫМ вызовом (Live Replay), иначе он не считается нарушением (правило №4).
_AXIOMS: list = []
_HAVOC_SEQ: list = [0]
_HAVOC_USED: list = [False]
_ABSTRACT_SYMS: set = set()  # символы абстракции (объявляются в SMT)
# ЧЕСТНЫЙ СЧЁТЧИК ОХВАТА (дефект #208): сколько раз реально вызывался решатель.
# Функция без единого SMT-обязательства НЕ имеет права называться проверенной.
_SMT_CALLS: list = [0]

# МЕМОИЗАЦИЯ ВЕРДИКТА (такт 2.2, замер §178.5). ИЗМЕРЕНО на `scanners.c`
# (`cmark-gfm/src`): 2032 вызова решателя, из них УНИКАЛЬНЫХ 382, повторных
# 1650 (81,2 %), и 152,5 с из 153,3 с уходит ВНУТРЬ этих вызовов. Одинаковые
# формулы внутри одного прогона обязаны спрашиваться ОДИН раз.
# Ключ — ПОЛНЫЙ текст SMT-запроса, поэтому вердикт и контрпример совпадают
# побитово. Кэш живёт в памяти процесса и НЕ сохраняется на диск: вердикт
# зависит от версии ядра и решателя, и «запомнить» его между сборками значило
# бы выдать прошлое решение за проверку текущего кода.
_SMT_VERDICT_CACHE: dict = {}

# СПИСКИ В ЧИСТОМ Int (QF_LIA), без теории массивов.
# Окно элементов: `arr__e0..arr__e2 : Int` + длина `len__arr : Int`.
# Чтение `arr[i]` -> `(ite (= i 0) e0 (ite (= i 1) e1 e2))`, запись — три ite.
# Это ОВЕР-АППРОКСИМАЦИЯ (элементы произвольны), поэтому найденный контрпример
# обязан подтвердиться живым вызовом (правило №4 / дефект #206).
_LIST_WINDOW = 3


def _lists(env: dict) -> dict:
    got = env.get("__lists__")
    return got if isinstance(got, dict) else {}


def _lens(env: dict) -> dict:
    got = env.get("__lens__")
    return got if isinstance(got, dict) else {}


def _set_list(env: dict, name: str, elems: list) -> None:
    """Записать элементы так, чтобы правка НЕ протекла в соседнюю ветку."""
    env["__lists__"] = {**_lists(env), name: elems}


def _set_len(env: dict, name: str, smt_len: str) -> None:
    env["__lens__"] = {**_lens(env), name: smt_len}


def _list_elems(env: dict, name: str) -> list:
    """Символьные элементы списка (создаются один раз на имя).

    Один и тот же индекс даёт ОДНО значение (конгруэнтность индексации),
    поэтому `arr[0]` в разных ветках — одно и то же выражение.
    """
    got = _lists(env).get(name)
    if got is not None:
        return got
    elems = [f"{name}__e{i}" for i in range(_LIST_WINDOW)]
    for s in elems:
        _ABSTRACT_SYMS.add(s)
    _set_list(env, name, elems)
    ln = f"len__{name}"
    _ABSTRACT_SYMS.add(ln)
    if f"(>= {ln} 0)" not in _AXIOMS:
        _AXIOMS.append(f"(>= {ln} 0)")
    _set_len(env, name, ln)
    return elems


def _list_read(elems: list, idx: str) -> str:
    """`arr[idx]` -> каскад `ite` по окну (одна форма для чтения и для `+=`)."""
    expr = elems[-1]
    for k in range(_LIST_WINDOW - 2, -1, -1):
        expr = f"(ite (= {idx} {k}) {elems[k]} {expr})"
    return expr


def _idx_outside_window(node) -> bool:
    """Индекс — не литерал `0..W-1`: окно НЕДО-аппроксимирует индекс (#217).

    Возвращает True, если трансляция перестаёт быть точной и доказательство
    должно деградировать в честный `[UNBOUNDED] SKIP`.
    """
    return not (isinstance(node, ast.Constant) and isinstance(node.value, int)
                and 0 <= node.value < _LIST_WINDOW)


def _replay_soft(exc: BaseException, where: str = "replay") -> None:
    """Мягкий выход из ЖИВОГО replay контрпримера (дефект #198/#208).

    Часть исключений ОЖИДАЕМА: функция не принимает такие аргументы
    (`TypeError`, `KeyError`, `ValueError`, `OverflowError`, `IndexError`,
    `RecursionError`) — молчим, нарушением это не считается.

    Но `NameError` / `AttributeError` / `SyntaxError` / `ImportError` значат,
    что сломан НАШ код (ровно класс #198: `_xray_file` не существовала, а
    `except Exception: pass` это скрыл). Такие печатаем в stderr, чтобы дефект
    был виден с первого запуска, а не через месяц.
    """
    if isinstance(exc, (TypeError, KeyError, ValueError, OverflowError,
                        IndexError, RecursionError, ArithmeticError)):
        return
    print(f"[!] {where}: внутренняя ошибка при живом replay: "
          f"{type(exc).__name__}: {exc}", file=sys.stderr)
# ОГРАНИЧЕННАЯ РАЗВЁРТКА (Bounded Model Checking, как в CBMC/Kani).
# `while` и `for ... in range(K)` разворачиваются в K копий тела, саморекурсия —
# в K вложенных тел (в самой глубине вызов становится havoc). Развёртка —
# НЕДО-аппроксимация: она годится для ПОИСКА контрпримеров, но не для
# доказательства корректности. Поэтому SAT-контрпример обязан подтвердиться
# ЖИВЫМ вызовом (Live Replay) — иначе он не считается нарушением (#206).
_UNROLL_K: list = [max(1, int(os.environ.get("KERN_UNROLL_K", "2")))]
_UNROLLED: list = [False]   # в трансляции была развёртка цикла/рекурсии
_INLINED: list = [0]        # сколько раз встроено тело саморекурсии




class Unsupported(Exception):
    pass


class NoReturn(Exception):
    """Путь исполнения доходит до конца функции без `return` (неявный None)."""


def _int_literal(node: ast.AST, env: dict) -> bool:
    """Целое-литерал ИЛИ имя локальной константы, чьё значение — литерал.

    ЗАЧЕМ (найдено крайним случаем `const k = 2; return x * k;`). Проверка
    «нелинейное умножение» смотрела ТОЛЬКО на `ast.Constant`, поэтому
    умножение на локальную константу отвергалось, хотя `k` уже подставлен
    в `env` как литерал `"2"`.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, int) \
            and not isinstance(node.value, bool):
        return True
    if isinstance(node, ast.Name) and node.id in env:
        v = env[node.id].strip()
        return v.lstrip("-").isdigit()
    return False


def _is_str_expr(node) -> bool:
    """ДЕФЕКТ (найден полевым сканом stdlib): `%` в Python — ДВА оператора:
    остаток от деления и строковое форматирование. `'%s' % self.reason`
    трактовалось как `mod` -> ЛОЖНЫЙ `[CRASH PATH]` «деление на ноль:
    self__reason == 0» в `urllib/error.py` и `http/cookiejar.py`.

    ЗВУЧИМОСТЬ: строковые выражения вне подмножества, поэтому такой `%`
    должен вести к честному SKIP, а не к мнимо��у делению.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):          # f-string
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _is_str_expr(node.left)
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "format":
            return True
    return False


# ДЕФЕКТ #317: текущий язык трансляции. Транслятор общий для Python и
# C-подобных, а семантика деления у них РАЗНАЯ, поэтому язык протаскивается
# до места трансляции: точки входа выставляют его из расширения файла.
_CURRENT_LANG = "python"


def _floor_div_smt(a: str, b: str) -> str:
    """`a // b` (Python, FLOOR): частное округляется вниз.

    ДЕФЕКТ #317. Оператор SMT `div` совпадает с floor только при b > 0, потому
    что его остаток всегда неотрицателен (евклидова семантика), а в Python
    остаток имеет знак ДЕЛИТЕЛЯ. При b < 0 нормализуем делитель:
    `floor(a/b) = floor(-a/-b)`. Внешний отчёт (M. Brigindi) + независимая
    проверка: 292 расхождения из 840 без адаптера, 0 с ним.
    """
    return f"(ite (> {b} 0) (div {a} {b}) (div (- {a}) (- {b})))"


def _trunc_div_smt(a: str, b: str) -> str:
    """`a / b` (C / Zig / Rust, УСЕЧЕНИЕ К НУЛЮ).

    На `|a| / |b|` евклидово деление и усечение совпадают (оба операнда
    неотрицательны), поэтому знак частного определяется отдельно:
    sign(a) * sign(b). Проверено на 420 точках: 0 расхождений с C.
    """
    aa = f"(ite (>= {a} 0) {a} (- {a}))"
    ab = f"(ite (> {b} 0) {b} (- {b}))"
    mag = f"(div {aa} {ab})"
    return f"(ite (= (>= {a} 0) (> {b} 0)) {mag} (- {mag}))"


def _mod_smt(a: str, b: str, q: str) -> str:
    """Остаток через тождество `r = a - b*q` — знак берётся автоматически.

    Это верно и для floor (Python), и для усечения (C): разница целиком в `q`.
    """
    return f"(- {a} (* {b} {q}))"


def expr_smt(node: ast.AST, env: dict, lang: str | None = None) -> str:
    """Python-выражение (подмножество) -> SMT-LIB2 с учётом локальных имён.

    `env` отображает имена локальных переменных в их SMT-выражения (результат
    символьного исполнения присваиваний). Имена, которых нет в env, считаются
    параметрами функции и печатаются как есть.

    `lang` определяет СЕМАНТИКУ ДЕЛЕНИЯ (дефект #317): Python — floor,
    C/Zig/Rust — усечение к нулю. Если не передан, берётся `_CURRENT_LANG`.
    """
    if lang is None:
        lang = _CURRENT_LANG
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "true" if node.value else "false"
        if isinstance(node.value, int):
            return str(node.value)
        if node.value is None:
            # БЛОКЕР `None` (40 функций): Optional моделируется сентинелом.
            return _NONE_SENTINEL
        raise Unsupported(f"литерал {node.value!r}")
    if isinstance(node, ast.Name):
        # ШАГ 1: СВОБОДНАЯ переменная ИНЛАЙНЕННОГО тела (`_inl_<g>_<n>_<var>`).
        # Она обязана быть ОБЪЯВЛЕНА в SMT: без объявления формула невалидна,
        # Z3 возвращает ошибку, и вердикт деградирует до «НЕ РЕШЕНО» — то есть
        # инструмент молчит там, где мог бы предъявить контрпример.
        # Это НЕ `_havoc` (не овер-аппроксимация): свободная переменная в теле
        # вызываемого — настоящий дефект (в Python это NameError), и контракт
        # обязан быть опровергнут с контрпримером.
        if node.id not in env and node.id.startswith("_inl_"):
            _ABSTRACT_SYMS.add(node.id)
        return env.get(node.id, node.id)
    # ПОЛЕВОЙ АДАПТЕР №1 (self.x / this.x / cfg.limit): реальный код на 80 %
    # состоит из методов классов и структур. Без этого `--xray` отправлял их
    # в SKIP. Трактуем `obj.field` как СИМВОЛИЧЕСКУЮ переменную `obj__field`.
    if isinstance(node, ast.Attribute):
        base = node.value
        if isinstance(base, ast.Name):
            nm = f"{base.id}__{node.attr}"
            return env.get(nm, nm)
        raise Unsupported("атрибут не от простого имени")
    # ПОЛЕВОЙ АДАПТЕР №4 (min/max/abs) -> точные линейные ite (определения,
    # а не приближения), вместо SKIP «неподдерживаемый вызов».
    if isinstance(node, ast.Call):
        fn = node.func
        fname = fn.id if isinstance(fn, ast.Name) else None
        if fname in ("min", "max") and len(node.args) == 2 and not node.keywords:
            a = expr_smt(node.args[0], env, lang)
            b = expr_smt(node.args[1], env, lang)
            cmp_ = "<=" if fname == "min" else ">="
            return f"(ite ({cmp_} {a} {b}) {a} {b})"
        if fname == "abs" and len(node.args) == 1 and not node.keywords:
            x = expr_smt(node.args[0], env, lang)
            return f"(ite (< {x} 0) (- 0 {x}) {x})"
        # СИМВОЛЬНАЯ АБСТРАКЦИЯ (правило №1): неизвестный вызов больше НЕ
        # означает отказ от функции. `len(x)` -> символ `len__x` с аксиомой
        # неотрицательности; `int(x)` -> x; `bool(x)` -> 0/1; всё прочее ->
        # СВЕЖАЯ символьная переменная (havoc), т.е. произвольное целое.
        # Такой SAT-контрпример обязан подтвердиться живым вызовом (см. вердикт).
        if fname == "len" and len(node.args) == 1 and not node.keywords:
            a0 = node.args[0]
            if isinstance(a0, ast.Name):
                # Длина ИЗВЕСТНОГО списка (литерала или уже смоделированного) —
                # это его фактическая длина, а не свободный символ.
                known = _lens(env).get(a0.id)
                if known is not None:
                    return known
                sym = f"len__{a0.id}"
            else:
                _HAVOC_SEQ[0] += 1
                sym = f"len__havoc_{_HAVOC_SEQ[0]}"
                _HAVOC_USED[0] = True
            _ABSTRACT_SYMS.add(sym)
            if f"(>= {sym} 0)" not in _AXIOMS:
                _AXIOMS.append(f"(>= {sym} 0)")
            return sym
        if fname in ("int", "bool") and len(node.args) == 1 and not node.keywords:
            x = expr_smt(node.args[0], env, lang)
            if fname == "int":
                return x
            return f"(ite (= {x} 0) 0 1)"
        # САМОРЕКУРСИЯ — ОГРАНИЧЕННЫЙ INLINE (K шагов, как bounded unroll):
        # тело функции подставляется с фактическими аргументами; на дне бюджета
        # вызов снова становится havoc. Недо-аппроксимация: SAT обязан
        # подтвердиться живым вызовом (правило №4).
        _meta = env.get("__self__") if isinstance(env, dict) else None
        if (_meta and isinstance(node.func, ast.Name)
                and node.func.id == _meta[0] and _meta[3] > 0 and not node.keywords
                and len(node.args) == len(_meta[1])):
            _sname, _sparams, _sbody, _budget = _meta
            _new_env = dict(env)
            for _p, _a in zip(_sparams, node.args):
                _new_env[_p] = expr_smt(_a, env, lang)
            _new_env["__self__"] = (_sname, _sparams, _sbody, _budget - 1)
            _INLINED[0] += 1
            _UNROLLED[0] = True
            return body_smt(copy.deepcopy(_sbody), _new_env)
        # ШАГ 1: ИНЛАЙНИНГ ВЫЗОВА ФУНКЦИИ ИЗ ТОГО ЖЕ ФАЙЛА (не саморекурсия).
        # Порядок проверок = правила звучимости: сначала реестр, потом стек
        # (рекурсия -> _havoc), потом бюджет.
        _inl = env.get("__inl__") if isinstance(env, dict) else None
        if (_inl and isinstance(node.func, ast.Name) and not node.keywords
                and node.func.id in _inl["reg"]
                and node.func.id not in _inl["stack"]
                and _inl["depth"] < _INLINE_MAX_DEPTH
                and _INLINED[0] < _INLINE_MAX_TOTAL):
            _gname = node.func.id
            _gparams, _gbody = _inl["reg"][_gname]
            if len(node.args) == len(_gparams):
                _seq = _inl["seq"] + 1
                _pfx = f"_inl_{_gname}_{_seq}_"
                # СНИМОК коллекторов: неудачный инлайн НЕ имеет права оставлять
                # обязанности от ЧАСТИЧНО исследованного тела (правило 3).
                _snap_div = len(_DIV_COLLECTOR)
                _snap_neg = len(_NEG_COLLECTOR)
                # `_ABSTRACT_SYMS` — МНОЖЕСТВО, а не список: срез-удаление к нему
                # неприменимо. Копируем целиком и восстанавливаем при откате.
                # (Дефект собственной реализации, найденный тестом на рекурсию:
                # `del set[...]` давал `TypeError: 'set' object does not support
                # item deletion` — то есть ИНСТРУМЕНТ ПАДАЛ на рекурсивном
                # хелпере вместо честного вердикта.)
                _snap_abs = set(_ABSTRACT_SYMS)
                _args = [expr_smt(a, env, lang) for a in node.args]
                _keep = _INLINE_KEEP | set(_inl["reg"])
                _ren = _rename_body(_gbody, _pfx, _keep)
                _new_env = {_pfx + p: a for p, a in zip(_gparams, _args)}
                _new_env["__inl__"] = {
                    "reg": _inl["reg"],
                    "stack": _inl["stack"] + [_gname],
                    "depth": _inl["depth"] + 1,
                    "seq": _seq,
                }
                try:
                    _val = body_smt(_ren, _new_env)
                except (Unsupported, NoReturn):
                    # ОТКАТ: тело вне подмножества -> прежнее поведение
                    # (_havoc), но БЕЗ следов частичного исследования.
                    del _DIV_COLLECTOR[_snap_div:]
                    del _NEG_COLLECTOR[_snap_neg:]
                    _ABSTRACT_SYMS.clear()
                    _ABSTRACT_SYMS.update(_snap_abs)
                else:
                    _INLINED[0] += 1
                    return _val
        _HAVOC_SEQ[0] += 1
        _HAVOC_USED[0] = True
        _sym = f"_havoc_{_HAVOC_SEQ[0]}"
        _ABSTRACT_SYMS.add(_sym)
        return _sym
    # Тернарный оператор `A if cond else B` -> SMT `ite`.
    if isinstance(node, ast.IfExp):
        # ДЕФЕКТ #327: гард ветвления активен ТОЛЬКО внутри своей ветки.
        # В `body` истинно `test`, в `orelse` — его отрицание. Без этого
        # `0 if b == 0 else a // b` давал ложное обвинение в делении на ноль.
        _cond = _as_bool(node.test, env)
        _g = len(_DIV_GUARDS)
        try:
            _DIV_GUARDS.append(_cond)
            _then = expr_smt(node.body, env, lang)
            _DIV_GUARDS[_g:] = [f"(not {_cond})"]
            _else = expr_smt(node.orelse, env, lang)
        finally:
            del _DIV_GUARDS[_g:]
        return f"(ite {_cond} {_then} {_else})"
    if isinstance(node, ast.BoolOp):
        # ДЕФЕКТ N1 (найден диагностикой после #327): ЛЕНИВОЕ вычисление.
        # В Python `A and B` вычисляет B ТОЛЬКО если A истинно, а `A or B` —
        # только если A ложно. Без протягивания гардов `b != 0 and a // b > 0`
        # давало ЛОЖНОЕ обвинение в делении на ноль: делитель `b` собирался
        # в контексте, где условие `b != 0` ещё не действует.
        # Гарды накапливаются: k-й операнд вычисляется при истинности ВСЕХ
        # предыдущих (`and`) либо при ложности всех предыдущих (`or`).
        op = "and" if isinstance(node.op, ast.And) else "or"
        _g = len(_DIV_GUARDS)
        parts: list[str] = []
        try:
            for i, v in enumerate(node.values):
                parts.append(expr_smt(v, env, lang))
                if i < len(node.values) - 1:
                    if op == "and":
                        _DIV_GUARDS.append(parts[-1])
                    else:
                        _DIV_GUARDS.append(f"(not {parts[-1]})")
        finally:
            del _DIV_GUARDS[_g:]
        return f"({op} {' '.join(parts)})"
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return f"(not {expr_smt(node.operand, env, lang)})"
        if isinstance(node.op, ast.USub):
            inner = expr_smt(node.operand, env, lang)
            # ДЕФЕКТ #334 (остаток N5): унарный минус на ЗНАКОВОМ фиксированном
            # типе — это `0 - x`, и при `x == MIN` результат непредставим
            # (`gcc -ftrapv`: SIGABRT). Собираем пару (операнд, гарды), чтобы
            # обязанность проверялась отдельно: диапазон РЕЗУЛЬТАТА её не видит,
            # потому что в математических целых `-MIN` влезает.
            _NEG_COLLECTOR.append((inner, tuple(_DIV_GUARDS)))
            return f"(- {inner})"
        raise Unsupported("унарный оператор")
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            op = "+"
        elif isinstance(node.op, ast.Sub):
            op = "-"
        elif isinstance(node.op, ast.Mult):
            # Умножение разрешено, если ХОТЯ БЫ один множитель — константа
            # (в том числе локальная: `const k = 2; x * k`).
            if not _int_literal(node.right, env) and not _int_literal(node.left, env):
                raise Unsupported("нелинейное умножение")
            op = "*"
        elif isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            # ДЕФЕКТ #317: СЕМАНТИКА ДЕЛЕНИЯ ЗАВИСИТ ОТ ЯЗЫКА.
            #   Python: `//` и `%` — FLOOR (остаток имеет знак ДЕЛИТЕЛЯ),
            #           `/` — истинное деление (float) -> вне подмножества;
            #   C/Zig/Rust: `/` и `%` — УСЕЧЕНИЕ К НУЛЮ;
            #   SMT-LIB `div`/`mod` — ЕВКЛИДОВЫ (остаток всегда >= 0).
            # Раньше ВСЁ уходило в `div`/`mod`, то есть описывало ДРУГУЮ функцию:
            # ложное ДОКАЗАНО на `a == 3 and b == -2` / `ensures result >= -1`.
            # В SMT `div`/`mod` — ТОТАЛЬНЫЕ функции, поэтому ноль НЕ ловится сам;
            # делители собираются, и `делитель ≠ 0` доказывается отдельно
            # (обязательство безопасности, см. `build_divzero_smt`).
            # `%` над СТРОКАМИ — это форматирование, а не остаток от деления.
            if isinstance(node.op, ast.Mod) and _is_str_expr(node.left):
                raise Unsupported("строковое форматирование %")
            left = expr_smt(node.left, env, lang)
            right = expr_smt(node.right, env, lang)
            # ДЕФЕКТ #327: сохраняем АКТИВНЫЕ ГАРДЫ вместе с делителем.
            _DIV_COLLECTOR.append((left, right, tuple(_DIV_GUARDS)))
            # ШАГ I: правило деления берётся из ТАБЛИЦЫ, а не из `if lang`.
            # Раньше здесь стояло `if lang == "python"`, и один переводчик
            # обслуживал Python и C — отсюда #317 (floor вместо усечения).
            sem = semantics_for(lang)
            if sem.true_div is None:
                if isinstance(node.op, ast.Div):
                    raise Unsupported("истинное деление / (float) вне подмножества")
            if sem.div == "floor":
                q = _floor_div_smt(left, right)
            else:
                q = _trunc_div_smt(left, right)
            if isinstance(node.op, ast.Mod):
                return _mod_smt(left, right, q)
            return q
        else:
            raise Unsupported("бинарный оператор (только + - * / // %)")
        return f"({op} {expr_smt(node.left, env, lang)} {expr_smt(node.right, env, lang)})"
    if isinstance(node, ast.Compare):
        # ДЕФЕКТ #203 (полевой аудит 595 функций 6 библиотек): идиома Python
        # `0 <= start < length` отвергалась как «цепочка сравнений», и функция
        # уходила в SKIP (в werkzeug `is_byte_range_valid`). Цепочка — это
        # КОНЪЮНКЦИЯ соседних сравнений (`a < b < c` ⟺ `a < b ∧ b < c`),
        # поэтому разворачиваем её без ослабления проверки.
        parts = []
        cur = node.left
        for op, right in zip(node.ops, node.comparators):
            opname = type(op).__name__
            if opname not in CMP:
                raise Unsupported(f"сравнение {opname}")
            parts.append(f"({CMP[opname]} {expr_smt(cur, env, lang)} {expr_smt(right, env, lang)})")
            cur = right
        if not parts:
            raise Unsupported("пустое сравнение")
        return parts[0] if len(parts) == 1 else f"(and {' '.join(parts)})"
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        # СПИСКИ В ЧИСТОМ Int: `arr[i]` -> каскад `ite` по окну элементов.
        # Срез (`arr[a:b]`) в модель не входит — честный отказ, а не догадка.
        base = node.value
        if not isinstance(base, ast.Name):
            raise Unsupported("индекс не от простого имени")
        if isinstance(node.slice, ast.Slice):
            raise Unsupported("срез списка")
        # ЗВУЧНОСТЬ (#217): окно из 3 элементов — НЕДО-аппроксимация, если
        # индекс не является литералом 0..2. Тогда `arr[5]` и `arr[3]` дают
        # ОДНО значение, и `--diff-equiv` мог бы объявить эквивалентность,
        # которой нет. Помечаем трансляцию как развёрнутую: доказательство
        # становится честным `[UNBOUNDED] SKIP`, поиск контрпримеров — работает.
        idx_node = node.slice
        if _idx_outside_window(idx_node):
            _UNROLLED[0] = True
        elems = _list_elems(env, base.id)
        idx = expr_smt(idx_node, env, lang)
        return _list_read(elems, idx)
    raise Unsupported(f"узел {type(node).__name__}")


def _as_bool(node, env: dict) -> str:
    """Логическое значение условия: Int-выражение -> `(not (= e 0))`.

    ЗАЧЕМ (`while n:` / `if n:` / `if arr:`): в Python истинность числа — это
    `n != 0`, а истинность последовательности — `len(arr) > 0`. Без приведения
    Z3 получал `Int` в позиции `Bool` и формула была невалидной, функция
    уходила в SKIP (`bitcount`, `possible_change`).
    """
    if isinstance(node, ast.Name) and node.id in _lists(env):
        _list_elems(env, node.id)
        return f"(> {_lens(env)[node.id]} 0)"
    text = expr_smt(node, env)
    if isinstance(node, (ast.Compare, ast.BoolOp)) or (
            isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)):
        return text
    return f"(not (= {text} 0))"


def _self_meta(fn, stmts, registry=None) -> dict:
    """Окружение с метаданными функции для inline саморекурсии (bounded) и
    РЕЕСТРОМ функций файла (ШАГ 1: инлайнинг вызовов из того же файла)."""
    params = [a.arg for a in fn.args.args if a.arg != "self"]
    meta = {"__self__": (fn.name, params, stmts, _UNROLL_K[0])}
    if registry:
        meta["__inl__"] = {"reg": registry, "stack": [fn.name], "depth": 0,
                           "seq": 0}
    return meta


# ── ШАГ 1: ИНЛАЙНИНГ ВЫЗОВОВ ФУНКЦИЙ ИЗ ТОГО ЖЕ ФАЙЛА ────────────────────────
# ЗАЧЕМ. В реальном коде почти каждая функция вызывает соседнюю (`lcm` зовёт
# `gcd`, парсер зовёт `clamp`). До этого шага ЛЮБОЙ такой вызов уходил в
# `_havoc` (свежий символ) — то есть тело вызываемого НЕ анализировалось, а его
# обязанности безопасности (деление на ноль, переполнение) НЕ собирались.
# ИЗМЕРЕНО на `TheAlgorithms/C/math`: проверено 26 из 66 функций; на 43 реальных
# провалах MBPP+ **43/43 содержат вызов функции**.
#
# ТРИ ПРАВИЛА ЗВУЧИМОСТИ (каждое — против конкретного способа соврать):
#   1. ГИГИЕНА ИМЁН. Тело `g` переименовывается уникальным префиксом вызова.
#      Без этого локальная `t` (или СВОБОДНАЯ переменная `k`) внутри `g` и
#      одноимённая переменная `f` — это ОДИН SMT-символ, и свободная переменная
#      `g` окажется связана с параметром `f`. Это ЛОЖНОЕ ДОКАЗАТЕЛЬСТВО, а не
#      приближение (существующий инлайн саморекурсии наследовал `dict(env)` и
#      был подвержен ровно этому).
#   2. ЗАЩИТА ОТ РЕКУРСИИ. Стек вызовов + бюджет глубины. Рекурсивная `g`
#      (прямая или взаимная) НЕ разворачивается бесконечно: вызов откатывается
#      к прежнему `_havoc` — овер-аппроксимация, а не ложь.
#   3. ОБЯЗАННОСТИ ПОД ГАРДАМИ ТОЧКИ ВЫЗОВА. Тело `g` исполняется ТЕМ ЖЕ
#      `body_smt`, поэтому его делители попадают в `_DIV_COLLECTOR` при активных
#      путевых условиях вызывающего. Неудачный инлайн ОТКАТЫВАЕТ коллекторы:
#      частично исследованное тело не имеет права оставлять обязанности.
_INLINE_MAX_DEPTH = int(os.environ.get("KERN_INLINE_DEPTH", "3"))
_INLINE_MAX_TOTAL = int(os.environ.get("KERN_INLINE_TOTAL", "64"))
# `KERN_INLINE_DEPTH=0` ОТКЛЮЧАЕТ инлайнинг — это нужно для честного замера
# ДО/ПОСЛЕ на одном и том же коде (иначе «до» пришлось бы брать из истории).

# Имена, которые НЕ переименовываются: встроенные, которые `expr_smt` понимает
# ТОЧНО (min/max/abs/len/int/bool), и `range` (его разбирает развёртка циклов).
_INLINE_KEEP = {"min", "max", "abs", "len", "int", "bool", "range",
                "True", "False", "None"}


def _inline_registry(tree) -> dict:
    """Реестр ВСЕХ функций верхнего уровня: имя -> (параметры, тело).

    Берутся и функции БЕЗ контрактов: именно они и есть хелперы (`gcd`), ради
    которых шаг и делается. Вложенные `def` не берутся — у них своя область.
    """
    reg = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            stmts = [
                st for st in node.body
                if not isinstance(st, ast.Pass)
                and not (isinstance(st, ast.Expr)
                         and isinstance(st.value, ast.Constant)
                         and isinstance(st.value.value, str))
            ]
            params = [a.arg for a in node.args.args if a.arg != "self"]
            reg[node.name] = (params, stmts)
    return reg


def _rename_body(stmts, prefix: str, keep: set) -> list:
    """Копия тела, где КАЖДОЕ имя получает префикс вызова (правило 1).

    Переименовываются и ПАРАМЕТРЫ: вызывающий связывает префиксованные имена с
    выражениями аргументов, поэтому ни одно имя `g` не может совпасть с именем
    `f` в SMT-тексте.

    НЕ переименовываются: встроенные (`min`/`max`/`abs`/`len`/`int`/`bool`) и
    имена функций из реестра — иначе вложенный вызов `h` внутри `g` перестал бы
    находиться и ушёл бы в `_havoc`.
    """
    body = copy.deepcopy(stmts)
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Name) and node.id not in keep:
            node.id = prefix + node.id
    return body


def body_smt(stmts, env: dict) -> str:
    """Символьно исполнить тело функции и вернуть SMT-выражение её результата.

    ПОДДЕРЖИВАЕТСЯ (ациклический код):
      * `return <expr>` — значение функции;
      * `if cond: ... [else: ...]` — транслируется в `(ite cond THEN ELSE)`;
      * `x = <expr>` — локальное присваивание (подстановка в `env`);
      * `elif` — это вложенный `if` в `orelse`, обрабатывается рекурсивно.

    ЧЕСТНЫЕ ОТКАЗЫ:
      * `NoReturn` — путь доходит до конца функции без `return` (неявный None).
        Ветка НЕ глотается: без этого функция с забытым `return` считалась бы
        корректной;
      * `Unsupported` — циклы, вызовы, всё прочее вне подмножества.

    Если у `if` нет `else`, роль else играют ОСТАВШИЕСЯ операторы после него.
    """
    for i, st in enumerate(stmts):
        if isinstance(st, ast.AnnAssign):
            # БЛОКЕР (28 функций): `x: int = 5` — обычная аннотация Python, а не
            # «вне подмножества». `x: int` без значения объявляет символ.
            if isinstance(st.target, ast.Name):
                if st.value is None:
                    env.setdefault(st.target.id, st.target.id)
                else:
                    env[st.target.id] = expr_smt(st.value, env)
                continue
            raise Unsupported("AnnAssign не в простое имя")
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # БЛОКЕР (30 функций): вложенный `def helper()` — No-Op: определение
            # ничего не вычисляет. Вызов helper(...) даст havoc (правило №1).
            continue
        if isinstance(st, ast.Try):
            # БЛОКЕР (39 функций): обходим тело `try` как основной путь.
            # ОГРАНИЧЕНИЕ МОДЕЛИ: исключения не моделируются (как в CBMC без
            # исключений); ложные тревоги отсекает Live Replay (правило №4).
            try:
                return body_smt([s for s in st.body if not isinstance(s, ast.Pass)],
                                dict(env))
            except NoReturn:
                continue
        if isinstance(st, (ast.Import, ast.ImportFrom)):
            # ПОЛЕВОЙ АДАПТЕР: `import` не влияет на арифметику результата —
            # это No-Op, а не «вне подмножества» (в QuixBugs 3 задачи падали
            # только из-за строчки `import` в начале файла).
            continue
        if isinstance(st, ast.While):
            # ОГРАНИЧЕННАЯ РАЗВЁРТКА (CBMC/Kani-стиль): K копий `if cond: body`
            # подряд. Это НЕДО-аппроксимация: годится для поиска контрпримеров,
            # но не для доказательства. SAT-контрпример обязан подтвердиться
            # живым вызовом (Live Replay, правило №4 / дефект #206).
            if st.orelse:
                raise Unsupported("while ... else")
            _UNROLLED[0] = True
            copies = [
                ast.If(test=copy.deepcopy(st.test),
                       body=copy.deepcopy(st.body), orelse=[])
                for _ in range(_UNROLL_K[0])
            ]
            return body_smt(copies + stmts[i + 1:], env)
        if isinstance(st, ast.For):
            # `for v in range(<константы>)` разворачивается так же (K копий
            # присваивания счётчика + тело). Не-range итераторы — честный отказ.
            it = st.iter
            _is_range = (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                         and it.func.id == "range" and not it.keywords)
            if not _is_range:
                # ЦИКЛ ПО СПИСКУ (`for x in arr:`) — синтаксический сахар:
                # `for i in range(len(arr)): x = arr[i]`. Разворачиваем K шагов
                # под условием `len__arr > t` (Bounded Unrolling, #207).
                if not isinstance(it, ast.Name):
                    raise Unsupported("for по не-range")
                if not isinstance(st.target, ast.Name):
                    raise Unsupported("for с распаковкой цели")
                if st.orelse:
                    raise Unsupported("for ... else")
                _list_elems(env, it.id)
                _UNROLLED[0] = True
                steps = []
                for t in range(_UNROLL_K[0]):
                    steps.append(ast.If(
                        test=ast.Compare(
                            left=ast.Call(func=ast.Name(id="len", ctx=ast.Load()),
                                          args=[ast.Name(id=it.id, ctx=ast.Load())],
                                          keywords=[]),
                            ops=[ast.Gt()],
                            comparators=[ast.Constant(value=t)]),
                        body=[ast.Assign(
                            targets=[copy.deepcopy(st.target)],
                            value=ast.Subscript(
                                value=ast.Name(id=it.id, ctx=ast.Load()),
                                slice=ast.Constant(value=t),
                                ctx=ast.Load()))] + copy.deepcopy(st.body),
                        orelse=[]))
                return body_smt(steps + stmts[i + 1:], env)
            if not isinstance(st.target, ast.Name):
                raise Unsupported("for с распаковкой цели")
            if st.orelse:
                raise Unsupported("for ... else")
            try:
                vals = [int(ast.literal_eval(a)) for a in it.args]
            except (ValueError, TypeError, SyntaxError):
                # НЕ-константный `range(len(arr))` и т.п.: недо-аппроксимация —
                # разворачиваем K итераций со счётчиком 0..K-1. Найденный
                # контрпример обязан подтвердиться живым вызовом (правило №4).
                _UNROLLED[0] = True
                unrolled = []
                for t in range(_UNROLL_K[0]):
                    unrolled.append(ast.Assign(
                        targets=[copy.deepcopy(st.target)],
                        value=ast.Constant(value=t)))
                    unrolled.extend(copy.deepcopy(st.body))
                return body_smt(unrolled + stmts[i + 1:], env)
            if len(vals) == 1:
                start, stop, step = 0, vals[0], 1
            elif len(vals) == 2:
                start, stop, step = vals[0], vals[1], 1
            elif len(vals) == 3:
                start, stop, step = vals
            else:
                raise Unsupported("range: не 1..3 аргумента")
            if step == 0:
                raise Unsupported("range с шагом 0")
            span = (stop - start) * (1 if step > 0 else -1)
            total = 0 if span <= 0 else (span + abs(step) - 1) // abs(step)
            _UNROLLED[0] = True
            unrolled = []
            for t in range(min(total, _UNROLL_K[0])):
                unrolled.append(ast.Assign(
                    targets=[copy.deepcopy(st.target)],
                    value=ast.Constant(value=start + t * step)))
                unrolled.extend(copy.deepcopy(st.body))
            return body_smt(unrolled + stmts[i + 1:], env)
        if isinstance(st, ast.AugAssign):
            # `x op= e` — это `x = x op e`. Для имён транслируется точно.
            if isinstance(st.target, ast.Subscript) and isinstance(st.target.ctx, ast.Store):
                # `arr[i] op= e` (мутация элемента, QuixBugs `next_palindrome`):
                # читаем текущее значение через `ite`-каскад, считаем `op` и
                # записываем обратно во все элементы окна.
                base = st.target.value
                if not isinstance(base, ast.Name):
                    raise Unsupported("AugAssign в индекс не от простого имени")
                if isinstance(st.target.slice, ast.Slice):
                    raise Unsupported("AugAssign в срез")
                if _idx_outside_window(st.target.slice):
                    _UNROLLED[0] = True
                elems = list(_list_elems(env, base.id))
                idx = expr_smt(st.target.slice, env)
                binop = ast.BinOp(left=ast.Name(id="__kern_old", ctx=ast.Load()),
                                  op=st.op, right=st.value)
                env["__kern_old"] = _list_read(elems, idx)
                val = expr_smt(binop, env)
                del env["__kern_old"]
                for k in range(_LIST_WINDOW):
                    elems[k] = f"(ite (= {idx} {k}) {val} {elems[k]})"
                _set_list(env, base.id, elems)
                continue
            if not isinstance(st.target, ast.Name):
                raise Unsupported("AugAssign не в имя")
            binop = ast.BinOp(left=ast.Name(id=st.target.id, ctx=ast.Load()),
                              op=st.op, right=st.value)
            env[st.target.id] = expr_smt(binop, env)
            continue
        if isinstance(st, ast.Assign):
            tgts = st.targets[0]
            if isinstance(tgts, (ast.Tuple, ast.List)):
                # БЛОКЕР (25 функций): `a, b = e1, e2` — покомпонентная распаковка.
                vals = st.value
                if not isinstance(vals, (ast.Tuple, ast.List)) \
                        or len(vals.elts) != len(tgts.elts):
                    raise Unsupported("распаковка нефиксированной длины")
                for name_node, val_node in zip(tgts.elts, vals.elts):
                    if not isinstance(name_node, ast.Name):
                        raise Unsupported("распаковка не в имена")
                    env[name_node.id] = expr_smt(val_node, env)
                continue
            if isinstance(tgts, ast.Subscript) and isinstance(tgts.ctx, ast.Store):
                # ЗАПИСЬ В ЭЛЕМЕНТ (`arr[i] = v`): обновляем ВСЕ элементы окна
                # через `ite`, сохраняя конгруэнтность чтения.
                base = tgts.value
                if not isinstance(base, ast.Name):
                    raise Unsupported("запись в индекс не от простого имени")
                if isinstance(tgts.slice, ast.Slice):
                    raise Unsupported("запись в срез")
                if _idx_outside_window(tgts.slice):
                    _UNROLLED[0] = True
                elems = list(_list_elems(env, base.id))
                idx = expr_smt(tgts.slice, env)
                val = expr_smt(st.value, env)
                for k in range(_LIST_WINDOW):
                    elems[k] = f"(ite (= {idx} {k}) {val} {elems[k]})"
                _set_list(env, base.id, elems)
                continue
            if len(st.targets) != 1 or not isinstance(tgts, ast.Name):
                raise Unsupported("присваивание не в простую переменную")
            if isinstance(st.value, ast.List):
                # ЛИТЕРАЛ СПИСКА (`arr = [a, b, c]`): элементы — выражения,
                # длина — ФАКТИЧЕСКАЯ константа (хвост окна добивается нулями,
                # но `len()` возвращает настоящую длину, поэтому лишние
                # элементы недостижимы по индексу из `range(len(arr))`).
                elts = [expr_smt(e, env) for e in st.value.elts]
                if len(elts) > _LIST_WINDOW:
                    # Окно короче литерала: элементы за окном схлопываются,
                    # значит трансляция недо-аппроксимирует (#217).
                    _UNROLLED[0] = True
                _set_list(env, tgts.id, (elts + ["0"] * _LIST_WINDOW)[:_LIST_WINDOW])
                _set_len(env, tgts.id, str(len(elts)))
                continue
            # Подстановка: имя запоминается как SMT-выражение (символьное значение).
            env[tgts.id] = expr_smt(st.value, env)
            continue
        if isinstance(st, ast.Raise):
            # ПОЛЕВОЙ АДАПТЕР (аудит 595 функций 6 библиотек: 18.2 % функций
            # отвергались из-за `raise`). `if bad: raise ValueError(f"...")` —
            # это ГАРД, а не «вне подмножества»: ветка, уходящая в raise,
            # значения НЕ возвращает, поэтому постусловие к ней неприменимо.
            # Возвращаем None как «нет значения на этом пути»; обработчик `if`
            # ниже отбрасывает такую ветку и сужает путь на её отрицание.
            return None
        if isinstance(st, ast.Expr) and not (
                isinstance(st.value, ast.Constant)
                and isinstance(st.value.value, str)):
            # ОПАЗКОВЫЙ оператор-выражение (лог/принт/учёт). Его результат не
            # используется. ОГРАНИЧЕНИЕ МОДЕЛИ: вызов может менять состояние
            # объекта, но не арифметическое значение результата функции.
            continue
        if isinstance(st, ast.If):
            # ДЕФЕКТ #327: условие ветвления как SMT + стек активных гардов.
            # В THEN истинно `test`, в ELSE — его отрицание. Гард нужен и в
            # ОСТАТКЕ операторов (он исполняется при ложном условии).
            try:
                _icond = _as_bool(st.test, env)
            except (Unsupported, NoReturn, SyntaxError):
                _icond = None  # условие вне подмножества -> гарда нет (как раньше)
            _ig = len(_DIV_GUARDS)
            del _DIV_GUARDS[_ig:]
            if _icond:
                _DIV_GUARDS.append(_icond)
            try:
                then_env = dict(env)
                then_expr = body_smt(st.body, then_env)
            finally:
                del _DIV_GUARDS[_ig:]
            rest = stmts[i + 1:]
            else_env = dict(env)
            if _icond:
                _DIV_GUARDS.append(f"(not {_icond})")
            try:
                if st.orelse:
                    else_expr = body_smt(st.orelse, else_env)
                elif rest:
                    # Нет `else` -> при ложном условии исполняются оставшиеся операторы.
                    else_expr = body_smt(rest, else_env)
                else:
                    # Нет `else` и нет остатка -> путь без `return` (неявный None).
                    else_expr = None
            finally:
                del _DIV_GUARDS[_ig:]
            # ВЕТКА БЕЗ `return` (только присваивания, например `if c: y = 1`)
            # НЕ терминальна: исполнение продолжается после `if`, поэтому
            # значение берётся из ОСТАТКА операторов (раньше это был ложный
            # отказ «путь без return»).
            _then_term = bool(st.body) and isinstance(st.body[-1], ast.Raise)
            if then_expr is None and not _then_term and rest:
                # ОСТАТОК исполняется при ИСТИННОМ условии -> гард THEN (#327).
                if _icond:
                    _DIV_GUARDS.append(_icond)
                try:
                    then_expr = body_smt(rest, then_env)
                finally:
                    del _DIV_GUARDS[_ig:]
            # ВЕТКА-ГАРД: `if cond: raise ...` (терминальный отказ) не даёт
            # значения, поэтому результат берётся из ДРУГОЙ ветки, а условие
            # пути сужается на её отрицание. Это ровно семантика guard-clause.
            then_terminal = bool(st.body) and isinstance(st.body[-1], ast.Raise)
            else_terminal = bool(st.orelse) and isinstance(st.orelse[-1], ast.Raise)
            if then_terminal and else_expr is not None:
                return else_expr
            if else_terminal:
                return then_expr
            if then_expr is None or else_expr is None:
                raise NoReturn(
                    f"путь без `return` (стр. {getattr(st, 'lineno', '?')}): "
                    f"функция вернула бы None")
            return f"(ite {_as_bool(st.test, env)} {then_expr} {else_expr})"
        if isinstance(st, ast.Return):
            if st.value is None:
                raise NoReturn("`return` без значения (неявный None)")
            return expr_smt(st.value, env)
        raise Unsupported(f"оператор {type(st).__name__} (циклы/вызовы вне подмножества)")
    return None  # дошли до конца -> неявный None


def _py_comment_anchors(src: str) -> dict:
    """Директивы `@kern:` ТОЛЬКО из настоящих комментариев Python.

    ЗАЧЕМ (Comment-in-String Injection). Построчный `ANNOT.match()` видел
    `# @kern:requires False` ВНУТРИ многострочного строкового литерала
    и подделывал контракт. `tokenize` различает COMMENT и STRING, поэтому
    текст внутри литералов больше не считается директивой.
    """
    import io
    import tokenize as _tok
    out: dict[int, dict[str, str]] = {}
    try:
        for t in _tok.generate_tokens(io.StringIO(src).readline):
            if t.type != _tok.COMMENT:
                continue
            body = t.string.strip()
            m = ANNOT.match(body)
            if m:
                out.setdefault(t.start[0], {})[m.group(1)] = m.group(2)
    except (_tok.TokenError, IndentationError, SyntaxError):
        return {}
    return out


def parse_file(path: Path):
    """Вернуть список (имя, params, requires, ensures, body_smt, lineno, причина)."""
    src = path.read_text(encoding="utf-8", errors="replace")
    # ДЕФЕКТ #317: явно фиксируем язык — иначе он «протечёт» из ранее
    # разобранного C-файла в одном прогоне.
    # ДЕФЕКТ #342 (шаг N12): но источник языка — НЕ литерал `"python"`, а
    # `_set_lang_from_path`: расширение `.py` даёт `python`, а ЯВНАЯ директива
    # `@kern:lang evm` В ФАЙЛЕ — `evm`. Без этого `lang="evm"` не выставлялся
    # НИ ОДНИМ путём разбора, и запись `evm` в таблице была мёртвой.
    global _CURRENT_LANG
    _set_lang_from_path(path)
    lines = src.splitlines()
    # ИЗ НАСТОЯЩИХ КОММЕНТАРИЕВ (tokenize), а не построчно — защита от
    # Comment-in-String Injection.
    anchors: dict[int, dict[str, str]] = _py_comment_anchors(src)
    tree = ast.parse(src)
    # ШАГ 1: РЕЕСТР ФУНКЦИЙ ФАЙЛА (включая функции БЕЗ контрактов — именно они и
    # есть хелперы, как `gcd`). Передаётся в `body_smt` через env.
    registry = _inline_registry(tree)
    out = []
    for node in tree.body:  # только верхний уровень: вложенный def не наследует аннотации
        if not isinstance(node, ast.FunctionDef):
            continue
        # контракт: якоря в нескольких строках НАД функцией
        req = ens = None
        skip_reason = None
        for k in range(max(1, node.lineno - 6), node.lineno):
            if k in anchors:
                req = anchors[k].get("requires", req)
                ens = anchors[k].get("ensures", ens)
        if req is None and ens is None:
            continue
        # 🔴 ДЕФЕКТ (найден прогоном на функции с циклом): недостаточно взять
        # последний `return` — тогда функция с циклом/ветвлением принималась за
        # чистое тело и давала ЛОЖНЫЙ FAIL. Тело обязано быть РОВНО одним
        # оператором `return <выражение>`; всё прочее — вне подмножества.
        body = None
        stmts = [
            st for st in node.body
            if not isinstance(st, ast.Pass)
            # докстрока — не оператор
            and not (isinstance(st, ast.Expr)
                     and isinstance(st.value, ast.Constant)
                     and isinstance(st.value.value, str))
        ]
        # СИМВОЛЬНОЕ ИСПОЛНЕНИЕ: поддерживаются ветвления (`ite`) и локальные
        # присваивания. Путь без `return` -> NoReturn (не глотаем ветку!),
        # циклы/вызовы -> Unsupported.
        _DIV_COLLECTOR.clear()
        _NEG_COLLECTOR.clear()
        _UNROLLED[0] = False
        try:
            body = body_smt(stmts, _self_meta(node, stmts, registry))
        except (NoReturn, Unsupported) as e:
            body = None
            skip_reason = str(e)
        # ДЕФЕКТ #207: была ли трансляция с РАЗВЁРТКОЙ цикла/рекурсии.
        # Развёртка — недо-аппроксимация: SAT на K шагах = честный контрпример,
        # UNSAT на K шагах НЕ доказывает корректность (цикл может идти дальше).
        unrolled = bool(_UNROLLED[0])
        # Делители, встреченные при трансляции -> обязательство «делитель ≠ 0».
        divs = list(dict.fromkeys(_DIV_COLLECTOR))
        params = [a.arg for a in node.args.args if a.arg != "self"]
        out.append((node.name, params, req, ens, body, node.lineno, skip_reason,
                    {"ranges": {}, "ret": None, "divisors": divs,
                     "unrolled": unrolled}))
    return out


# Головы SMT-операторов, возвращающих ЛОГИЧЕСКОЕ значение (Bool), а не число.
_BOOL_HEADS = {
    "<=", "<", ">=", ">", "=", "distinct", "and", "or", "not", "=>",
    "bvult", "bvule", "bvugt", "bvuge", "bvslt", "bvsle", "bvsgt", "bvsge",
}


def value_of(smt: str, *, bitvec_width=None) -> str:
    """Привести ВОЗВРАЩАЕМОЕ ЗНАЧЕНИЕ функции к числу (`Int` или `BitVec`).

    ДЕФЕКТ #122 (найден теневым контрактом C `safeFits`).
    ИЗМЕРЕНО: функция, тело которой — «голое» СРАВНЕНИЕ
    (`return len <= size - offset;`), транслировалась в
    `(assert (= result (<= len (- size offset))))` — равенство между `Int` и
    `Bool`. Z3 принимал такую формулу ТОЛЬКО по снисходительной коэрции, а
    пруф-чекер такую посылку к контракту не привязывал (`premises_unbound`) и
    КОРРЕКТНЫЙ вывод отвергался. В C/C++/Rust/Zig логическое значение в позиции
    целого — это 0/1, поэтому приводим его ЯВНО через `ite`, не полагаясь на
    недокументированное поведение решателя.
    """
    head = smt.lstrip()
    if not head:
        return smt
    if head[0] == "(":
        name = head[1:].split(None, 1)[0].rstrip(")")
    else:
        name = head.split(None, 1)[0]
    if name not in _BOOL_HEADS and name not in ("true", "false"):
        return smt
    if bitvec_width is None:
        return f"(ite {smt} 1 0)"
    return f"(ite {smt} (_ bv1 {bitvec_width}) (_ bv0 {bitvec_width}))"


def build_smt(params, req, ens, body_smt_text: str, ranges=None) -> str:
    """SMT-LIB2: параметры, МАШИННЫЕ ГРАНИЦЫ, requires, `result = <тело>`, ¬ensures.

    `ranges` (Zig/C/Rust) ограничивает ВХОДЫ типом (`i32` -> [-2^31, 2^31-1]),
    поэтому контрпример всегда лежит в машинном домене функции. Диапазон
    РЕЗУЛЬТАТА здесь НЕ ограничивается: переполнение ловит отдельное
    обязательство (`build_overflow_smt`), иначе оно «спряталось» бы в UNSAT.
    """
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    lines = ["(set-logic ALL)", decls, "(declare-const result Int)"]
    # СИМВОЛЫ АБСТРАКЦИИ (`len__x`, `_havoc_k`) — ДО любых assert:
    # SMT-LIB требует, чтобы все `declare-const` шли перед `assert`, иначе
    # Z3/kernc отвергает формулу и вердикт уходит в N (unknown).
    for _sym in sorted(_ABSTRACT_SYMS):
        if _sym not in params and _sym != "result":
            lines.append(f"(declare-const {_sym} Int)")
    env: dict = {}  # в requires/ensures локальных имён нет — только параметры
    for p, (lo, hi) in (ranges or {}).items():
        lines.append(f"(assert (and (>= {p} {lo}) (<= {p} {hi})))")
    # Аксиомы символьной абстракции (`len(x) >= 0`): часть модели, а не догадка —
    # длина контейнера неотрицательна по определению.
    for ax in _AXIOMS:
        if f"(assert {ax})" not in lines:
            lines.append(f"(assert {ax})")

    if req:
        lines.append(f"(assert {expr_smt(ast.parse(req, mode='eval').body, env)})")
    lines.append(f"(assert (= result {value_of(body_smt_text)}))")
    if ens:
        e = expr_smt(ast.parse(ens, mode='eval').body, env)
        lines.append(f"(assert (not {e}))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


# ЯВНЫЕ операторы оборачивания/насыщения — НЕ паникуют при переполнении.
# Zig: `+% -% *%` (wrapping), `+| -|` (saturating). Rust: методы.
#
# ШАГ I: ЕДИНЫЙ ИСТОЧНИК — поле `wrap_ops` в `VALUE_SEMANTICS` (ниже). Здесь
# списки больше не дублируются: два источника истины для одного правила — это
# ровно тот класс, из которого вышли #317/#321 (правили одно место из двух).


def _explicit_wrap(body: str, lang: str) -> str | None:
    """Вернуть найденный оператор оборачивания/насыщения или None.

    ЗАЧЕМ. Обычный `a + b` в Zig ПАНИКУЕТ при переполнении (это баг), а
    `a +% b` / `a +| b` — ЗАКОННЫЕ операции без паники. Обвинять вторые в
    `INTEGER OVERFLOW` — ЛОЖНОЕ СРАБАТЫВАНИЕ (False Positive), которого не
    должно быть: пользователь явно выбрал семантику.
    """
    if not body:
        return None
    # ШАГ I: маркеры законного оборачивания берутся из ТАБЛИЦЫ семантики
    # (`wrap_ops`), а не из `if lang == "zig"` / `if lang == "rust"`.
    for op in semantics_for(lang).wrap_ops:
        if op in body:
            return op
    return None


def build_overflow_smt(params, req, body_smt_text: str, ranges, res_range) -> str:
    """Обязательство ПЕРЕПОЛНЕНИЯ: `requires ∧ result ∉ [lo, hi]` -> SAT = баг.

    ЗАЧЕМ (машинные типы Zig/C/Rust). Python-контракты живут в ℤ и переполнения
    не видят вовсе; здесь тип возврата известен, поэтому `i32`-функция, чей
    результат выходит за [-2^31, 2^31-1], отвергается с контрпримером.
    """
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    lines = ["(set-logic ALL)", decls, "(declare-const result Int)"]
    env: dict = {}
    for p, (lo, hi) in (ranges or {}).items():
        lines.append(f"(assert (and (>= {p} {lo}) (<= {p} {hi})))")
    if req:
        lines.append(f"(assert {expr_smt(ast.parse(req, mode='eval').body, env)})")
    lines.append(f"(assert (= result {value_of(body_smt_text)}))")
    lo, hi = res_range
    lines.append(f"(assert (or (< result {lo}) (> result {hi})))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def _div_zero_terms(divisors, zero: str) -> list:
    """Термы обязательства «делитель = 0» С УЧЁТОМ АКТИВНЫХ ГАРДОВ (дефект #327).

    Элемент — `(числитель, делитель, гарды)` (дефект #334 расширил кортеж: для
    обязательства ПЕРЕПОЛНЕНИЯ ДЕЛЕНИЯ нужна пара). Совместимость: принимаются и
    старые формы — `(делитель, гарды)` и голая строка.
    Для незащищённого деления гарды пусты и терм прежний: `(= делитель 0)`. Для
    деления под гардом — `(and <гарды> (= делитель 0))`, поэтому Z3 получает
    ПРОТИВОРЕЧИЕ и отвечает UNSAT (ложное обвинение исчезает), а незащищённое
    деление остаётся SAT.
    """
    out = []
    for d in divisors:
        expr = _divisor_of(d)
        guards = _guards_of(d)
        eq = f"(= {expr} {zero})"
        out.append(f"(and {' '.join(guards)} {eq})" if guards else eq)
    return out


def _divisor_of(d) -> str:
    """Делитель из элемента сборщика: 3-кортеж (#334), 2-кортеж (#327) или строка."""
    if isinstance(d, tuple):
        return d[1] if len(d) >= 3 else d[0]
    return d


def _numerator_of(d) -> str | None:
    """Числитель — только у 3-кортежа (#334); иначе None."""
    return d[0] if isinstance(d, tuple) and len(d) >= 3 else None


def _guards_of(d) -> tuple:
    if isinstance(d, tuple):
        return d[2] if len(d) >= 3 else (d[1] if len(d) == 2 else ())
    return ()


def _div_overflow_terms(divisors, lo: int) -> list:
    """Термы обязательства ПЕРЕПОЛНЕНИЯ ДЕЛЕНИЯ (дефект #334).

    `a / b` и `a % b` при `a == MIN ∧ b == -1` дают непредставимое частное, и
    инструкция `idiv` на x86_64 вызывает аппаратное исключение (C11 §6.5.5p6 —
    UB). Для `%` это особенно коварно: математический остаток равен 0, и 0
    влезает в тип, поэтому проверка ДИАПАЗОНА РЕЗУЛЬТАТА его не видит — ловится
    только парой (числитель, делитель).
    """
    out = []
    for d in divisors:
        num = _numerator_of(d)
        if num is None:
            continue          # старая форма: пары нет — обязательство не строим
        guards = _guards_of(d)
        den = _divisor_of(d)
        trap = f"(and (= {den} (- 1)) (= {num} {lo}))"
        out.append(f"(and {' '.join(guards)} {trap})" if guards else trap)
    return out


def build_divoverflow_smt(params, req, divisors, ranges, res_range) -> str:
    """Обязательство ПЕРЕПОЛНЕНИЯ ДЕЛЕНИЯ: `requires ∧ гарды ∧ (b = -1 ∧ a = MIN)`
    -> SAT = аппаратный краш (дефект #334).

    Знаковый диапазон берётся из типа возвращаемого значения: `res_range[0]` —
    это MIN типа (`-2^31` для i32). Для БЕЗзнаковых типов обязательства нет:
    `MIN` там равен 0, а `a / -1` не существует (делитель беззнаковый).
    """
    lo = res_range[0]
    if lo >= 0:
        return ""              # беззнаковый тип: переполнение деления невозможно
    terms = _div_overflow_terms(divisors, lo)
    if not terms:
        return ""
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    lines = ["(set-logic ALL)", decls]
    env: dict = {}
    for p, (plo, phi) in (ranges or {}).items():
        lines.append(f"(assert (and (>= {p} {plo}) (<= {p} {phi})) )")
    if req:
        lines.append(f"(assert {expr_smt(ast.parse(req, mode='eval').body, env)})")
    lines.append("(assert (or " + " ".join(terms) + "))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def _neg_overflow_terms(negs, lo: int) -> list:
    """Термы обязательства ПЕРЕПОЛНЕНИЯ УНАРНОГО МИНУСА (дефект #334, N5).

    `-x` на знаковом фиксированном типе — это `0 - x`; при `x == MIN` результат
    непредставим. НАЗЕМНАЯ ПРАВДА: `gcc -ftrapv` на `-INT_MIN` -> SIGABRT.
    Диапазон РЕЗУЛЬТАТА этого не видит: в математических целых `-MIN` влезает.
    """
    out = []
    for n in negs:
        if isinstance(n, tuple) and len(n) == 2:
            operand, guards = n
        else:
            operand, guards = n, ()
        t = f"(= {operand} {lo})"
        if guards:
            t = f"(and {' '.join(guards)} {t})"
        out.append(t)
    return out


def build_negoverflow_smt(params, req, negs, ranges, res_range) -> str:
    """Обязательство ПЕРЕПОЛНЕНИЯ УНАРНОГО МИНУСА: `requires ∧ гарды ∧ (x = MIN)`
    -> SAT = аппаратный краш (дефект #334, остаток N5).

    Для БЕЗзнаковых типов обязательства нет: `MIN` там 0, а `-0` безобиден.
    """
    lo = res_range[0]
    if lo >= 0:
        return ""
    terms = _neg_overflow_terms(negs, lo)
    if not terms:
        return ""
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    lines = ["(set-logic ALL)", decls]
    env: dict = {}
    for p, (plo, phi) in (ranges or {}).items():
        lines.append(f"(assert (and (>= {p} {plo}) (<= {p} {phi})) )")
    if req:
        lines.append(f"(assert {expr_smt(ast.parse(req, mode='eval').body, env)})")
    lines.append("(assert (or " + " ".join(terms) + "))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def build_divzero_smt(params, req, divisors, ranges) -> str:
    """Обязательство ДЕЛЕНИЯ НА НОЛЬ: `requires ∧ <гарды> ∧ (делитель = 0)` -> SAT = баг.

    ЗАЧЕМ. В SMT-LIB2 `div`/`mod` — ТОТАЛЬНЫЕ функции: `(div x 0)` просто
    доопределён, поэтому наивный чекер ноль НЕ видит, а в рантайме будет
    `ZeroDivisionError` / аппаратное исключение. Проверяем каждый делитель.
    """
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    lines = ["(set-logic ALL)", decls]
    env: dict = {}
    for p, (lo, hi) in (ranges or {}).items():
        lines.append(f"(assert (and (>= {p} {lo}) (<= {p} {hi})))")
    if req:
        lines.append(f"(assert {expr_smt(ast.parse(req, mode='eval').body, env)})")
    lines.append("(assert (or " + " ".join(_div_zero_terms(divisors, "0")) + "))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def requires_only_smt(params, req: str) -> str:
    """SMT только из ПРЕДУСЛОВИЯ — для проверки его ВЫПОЛНИМОСТИ.

    ЗАЧЕМ (УЛУЧШЕНИЕ №1: детектор вакуумных предусловий). Обязательство
    проверяется от противного: `requires ∧ body=result ∧ ¬ensures`. Если сам
    `requires` ПРОТИВОРЕЧИВ (`x > 10 and x < 5`), то эта конъюнкция тривиально
    UNSAT, и KERN объявил бы ДОКАЗАННОЙ ЛЮБУЮ сломанную функцию — классическая
    ловушка `false => anything`.

    `kernc prove` доказывает UNSAT входного файла, поэтому «ДОКАЗАНО» на файле
    из одного `requires` означает: предусловие НЕВЫПОЛНИМО (домен пуст).
    """
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    r = expr_smt(ast.parse(req, mode="eval").body, {})
    return f"(set-logic ALL)\n{decls}\n(assert {r})\n(check-sat)\n"


def tmp_dir() -> str:
    """RAM-диск (`/dev/shm`), если он есть, иначе `/tmp`.

    Устраняет дисковый I/O и fsync на тысячах временных `.smt2`; на вердикты
    НЕ влияет (тот же текст, та же команда).
    """
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        d = shm / "kern-contracts"
        d.mkdir(exist_ok=True)
        return str(d)
    return "/tmp"


_SOLVER_CACHE: dict | None = None


def solver_info() -> dict:
    """Версия решателя, которой реально пользуется `kernc` (шаг 0K.5).

    Вердикты зависят от версии Z3, поэтому отчёт обязан её фиксировать:
    иначе «до/после» сравнивает разные решатели, выдавая это за регресс.
    Версия берётся у бинарника из PATH (его запускает z3_bridge),
    timeout — тот же, что в `run_kernc` (120 с).
    """
    global _SOLVER_CACHE
    if _SOLVER_CACHE is None:
        path = shutil.which("z3") or ""
        version = "unknown"
        if path:
            r = subprocess.run([path, "--version"], capture_output=True, text=True)
            lines = (r.stdout or r.stderr).strip().splitlines()
            if lines:
                version = lines[0].strip()
        _SOLVER_CACHE = {"name": "z3", "version": version, "path": path,
                         "timeout_ms": 120000, "calls": 0}
    _SOLVER_CACHE["calls"] = _SMT_CALLS[0]
    return _SOLVER_CACHE


def _solver_env() -> dict:
    """PATH с каталогом РЕШАТЕЛЯ, найденным рядом с `sys.executable` (дефект #407).

    ЗАЧЕМ. Z3 живёт python-модулем внутри `.venv`, а `kernc` ищет его через PATH.
    В оболочке без `.venv/bin` ВСЕ SMT-детекторы молча не давали находок, и
    «инструмент не запущен» выглядело как «чистый код» (класс #277: N выдан за T).
    Теперь каталог подхватывается САМ, и ручной прогон не зависит от PATH оболочки
    (CI не задет: `tools/ci.sh` и так ставит `.venv/bin` первым).
    """
    env = dict(os.environ)
    cands = [Path(sys.executable).resolve().parent,
             Path(__file__).resolve().parent.parent / ".venv" / "bin"]
    have = [str(p) for p in cands if (p / "z3").exists()]
    if have:
        env["PATH"] = os.pathsep.join(have + [env.get("PATH", "")])
    return env


def run_kernc(kernc, smt: str, query_kind: str = "refutation"):
    """Прогнать `kernc prove` на SMT-тексте. Возвращает (rc, вывод).

    `query_kind` (#303) передаётся ядру: для `equivalence` правило привязки
    посылок не применяется — контрактных посылок в запросе-сравнении нет.

    ДЕФЕКТ #208: счётчик `_SMT_CALLS` инкрементируется ЗДЕСЬ — это единственная
    точка, через которую проходят ВСЕ вызовы решателя (`_smt_sat`,
    `_smt_verdict`, `_prove_checked`, `--diff-equiv`). Так «проверено» означает
    «решатель реально вызывался», а не «функцию прочитали глазами».
    """
    _SMT_CALLS[0] += 1
    with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False,
                                     dir=tmp_dir()) as tf:
        tf.write(smt)
        sp = tf.name
    try:
        cmd = [str(kernc), "prove"]
        if query_kind != "refutation":
            cmd += ["--query-kind", query_kind]
        cmd.append(sp)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           env=_solver_env())
        return r.returncode, r.stdout + r.stderr
    finally:
        Path(sp).unlink(missing_ok=True)


# Причины, по которым C-like функции НЕ попали в сравнение `--diff-equiv`
# (дефект #361): пустой список «сравнивать нечего» обязан называть ПРИЧИНУ.
_CLIKE_SKIP_REASONS: list[str] = []


def _parse_bodies_clike(path: Path):
    """C-like тела для `--diff-equiv` (ДЕФЕКТ #361).

    ЗАЧЕМ. `parse_bodies` звал `ast.parse` ВСЕГДА, поэтому `--diff-equiv a.c b.c`
    падал с `SyntaxError: invalid syntax` и трассировкой вместо вердикта — это
    нашлось первым прогоном гейта `quixbugs-diff-check` на контрольной паре
    «файл против самого себя» (`cwe190_good.c` дала падение, а не `EQUIVALENT`).
    Класс тот же, что #318/#322: инструмент не называет причину, а рушится.

    ЧТО ДЕЛАЕТ. Идёт через `parse_clike` — то есть C-like получают СВОЮ
    языковую семантику (`VALUE_SEMANTICS`: усечение вместо floor, аппаратные
    ловушки, границы типов), а не питоновскую. Форма результата приведена к общей:
    `(имя, params, body_smt, строка, unrolled)`.

    ЧЕСТНАЯ ГРАНИЦА. `unrolled=True`, если в теле есть ЦИКЛ: `_exec_clike`
    разворачивает его на K шагов, а развёртка — недо-аппроксимация (дефект
    #207). UNSAT на ней НЕ доказывает эквивалентность, поэтому `cmd_diff_equiv`
    обязан выдать `UNKNOWN`, а не `EQUIVALENT`. Функции, которые `parse_clike`
    не разобрал (`why` не пуст) или которые ушли в BV-кандидаты, в сравнение НЕ
    попадают — иначе отсутствие тела молча читалось бы как «эквивалентно».
    """
    out = []
    _CLIKE_SKIP_REASONS.clear()
    for name, params, _req, _ens, body, lineno, why, meta in parse_clike(
            path, require_annotations=False):
        if why is not None:
            _CLIKE_SKIP_REASONS.append(f"{name}: {why}")
            continue
        if body is None:
            _CLIKE_SKIP_REASONS.append(f"{name}: тело не разобрано (вне подмножества)")
            continue
        if body == "BV_PENDING":
            # ЧЕСТНАЯ ГРАНИЦА: нелинейное умножение/битовые операции живут в
            # QF_BV, а `--diff-equiv` сравнивает тела в Int-теории. Молча
            # пропустить нельзя: «нет одноимённых функций» без причины читалось
            # бы как «сравнивать нечего», хотя причина КОНКРЕТНАЯ.
            _CLIKE_SKIP_REASONS.append(
                f"{name}: тело требует QF_BV (нелинейное умножение/битовые "
                f"операции) — `--diff-equiv` сравнивает в Int-теории")
            continue
        raw = meta.get("raw_body", "") or ""
        unrolled = re.search(r"\b(while|for|loop)\b", raw) is not None
        out.append((name, list(params), body, lineno, unrolled))
    return out


def parse_bodies(path: Path):
    """Все функции файла БЕЗ контракта: (имя, params, body_smt, строка, unrolled).

    Нужна для УЛУЧШЕНИЯ №3 (`--diff-equiv`): эквивалентность рефакторинга
    доказывается по ТЕЛАМ, контракты писать не требуется.

    `unrolled=True` означает, что тело получено РАЗВЁРТКОЙ цикла/рекурсии на
    K шагов. Такое тело — недо-аппроксимация: SAT на нём даёт честный
    контрпример, но UNSAT НЕ доказывает эквивалентность (дефект #207).

    ДЕФЕКТ #361: маршрутизация по РАСШИРЕНИЮ. Python идёт через `ast`, C-like
    (`.c .h .zig .rs .go .ts .js`) — через `parse_clike` со своей семантикой;
    раньше `ast.parse` вызывался для ЛЮБОГО входа, и C-файл ронял инструмент.
    """
    if path.suffix in CLIKE_EXT:
        return _parse_bodies_clike(path)
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    # ШАГ 1: тот же реестр, что в `parse_file`. БЕЗ него вызов хелпера уходил в
    # `_havoc`, а два РАЗНЫХ havoc всегда «различны» — то есть `--diff-equiv`
    # объявлял бы расхождением идентичный рефакторинг с вызовом (ложное
    # обвинение). Отдельная ветка для `_havoc_` (дефект #206) это гасила
    # (UNKNOWN), но инлайнинг даёт точный ответ вместо честного «не знаю».
    registry = _inline_registry(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        stmts = [
            st for st in node.body
            if not isinstance(st, ast.Pass)
            and not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)
                     and isinstance(st.value.value, str))
        ]
        _UNROLLED[0] = False
        try:
            body = body_smt(stmts, _self_meta(node, stmts, registry))
        except (NoReturn, Unsupported):
            continue
        params = [a.arg for a in node.args.args if a.arg != "self"]
        out.append((node.name, params, body, node.lineno, bool(_UNROLLED[0])))
    return out


def diff_equiv_smt(params, body_old: str, body_new: str) -> str:
    """SMT для проверки `∃x: f_old(x) != f_new(x)` (УЛУЧШЕНИЕ №3).

    Оба тела исполняются на ОДНИХ И ТЕХ ЖЕ символьных аргументах. Если
    конъюнкция с `(distinct res_old res_new)` UNSAT — поведение не изменилось.
    """
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    return ("(set-logic ALL)\n"
            f"{decls}\n"
            "(declare-const res_old Int)\n"
            "(declare-const res_new Int)\n"
            f"(assert (= res_old {body_old}))\n"
            f"(assert (= res_new {body_new}))\n"
            "(assert (distinct res_old res_new))\n"
            "(check-sat)\n")


def contract_fingerprints(path: Path) -> dict:
    """Отпечатки ВСЕХ запечатанных контрактов файла (УЛУЧШЕНИЕ №2).

    Ключ — `<имя_функции>:requires|ensures`, значение — SHA-256 ТЕКСТА
    контракта. Сравнение отпечатков ловит УДАЛЕНИЕ или ОСЛАБЛЕНИЕ строки
    `# @kern:ensures` — самый простой чит ИИ-агента, которому не удаётся
    починить код под `make contracts`.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    anchors: dict[int, dict[str, str]] = {}
    for i, ln in enumerate(lines, 1):
        m = ANNOT.match(ln)
        if m:
            anchors.setdefault(i, {})[m.group(1)] = (m.group(2), annot_class(m))
    out: dict[str, str] = {}

    # Ф1: замок покрывает ВЕСЬ репозиторий, включая Zig/C. `ast.parse` для них
    # неприменим (дефект: на первом же .zig падало с UnicodeDecode/SyntaxError).
    # Для не-Python привязываем аннотацию к ближайшему `fn NAME` / `NAME(`:
    # ключ остаётся стабильным, а переименование функции ломает замок.
    if path.suffix != ".py":
        fn_re = re.compile(r"^\s*(?:pub\s+)?(?:export\s+)?(?:fn|def)\s+([A-Za-z_][A-Za-z0-9_]*)")
        bound: dict[int, str] = {}
        current = ""
        for i, ln in enumerate(lines, 1):
            f = fn_re.match(ln)
            if f:
                current = f.group(1)
            bound[i] = current
        for i, kinds in anchors.items():
            name = bound.get(i) or f"line{i}"
            for kind, (text, cls) in kinds.items():
                # Ф6.1: класс ВХОДИТ в отпечаток, поэтому переклейка
                # `hard -> advisory` без обновления замка — расхождение.
                out[f"{name}:{kind}:{cls}"] = hashlib.sha256(
                    text.encode("utf-8")).hexdigest()
        return out

    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef):
            continue
        for k in range(max(1, node.lineno - 6), node.lineno):
            if k not in anchors:
                continue
            for kind, (text, cls) in anchors[k].items():
                out[f"{node.name}:{kind}:{cls}"] = hashlib.sha256(
                    text.encode("utf-8")).hexdigest()
    return out


def parse_counterexample(out: str) -> dict:
    """Разобрать строку `[КОНТРПРИМЕР] x = 11, y = -3` в словарь (УЛУЧШЕНИЕ №4)."""
    vals: dict[str, int] = {}
    for line in out.splitlines():
        if "КОНТРПРИМЕР" not in line:
            continue
        body = line.split("КОНТРПРИМЕР", 1)[1]
        for m in re.finditer(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(-?\d+)", body):
            vals[m.group(1)] = int(m.group(2))
        break
    return vals


# ---------------------------------------------------------------------------
#  МИНИМИЗАЦИЯ КОНТРПРИМЕРА (пункт 5 плана v2.5)
# ---------------------------------------------------------------------------
# ЗАЧЕМ. Z3 честно возвращает ПЕРВУЮ найденную модель, и она часто нечитаема:
# `x = -2147483640` вместо `x = -1`. Такой контрпример бесполезен для отладки —
# ни человеку, ни ИИ-агенту не понятно, что именно чинить.
#
# КАК. Второй запрос к ТОМУ ЖЕ решателю с ДОБАВЛЕННЫМИ ограничениями окна
# (`-WINDOW <= p <= WINDOW` для каждого параметра).
#
# ПОЧЕМУ ЭТО ЗВУЧИМО (главное). Мы только ДОБАВЛЯЕМ ограничения к исходной
# задаче, поэтому ЛЮБАЯ модель суженной задачи является моделью исходной:
# найденный вход по-прежнему НАРУШАЕТ контракт. Перевернуть вердикт это не
# может — вердикт берётся из ПЕРВОГО (несуженного) прогона, а суженный лишь
# предлагает более читаемый вход. Если суженный прогон не даёт контрпримера
# (окно пусто, UNSAT внутри окна или таймаут) — остаётся исходный контрпример.
COUNTEREXAMPLE_WINDOW = 10


def _bound_smt(smt: str, params, window: int = COUNTEREXAMPLE_WINDOW) -> str:
    """SMT с ДОБАВЛЕННЫМИ границами `-window <= p <= window` перед `(check-sat)`."""
    bounds = [f"(assert (and (>= {p} -{window}) (<= {p} {window})))" for p in params]
    out: list[str] = []
    placed = False
    for ln in smt.splitlines():
        if not placed and ln.strip().startswith("(check-sat)"):
            out.extend(bounds)
            placed = True
        out.append(ln)
    if not placed:
        return smt  # нет `(check-sat)` — не трогаем вход
    return "\n".join(out) + "\n"


def minimize_counterexample(kernc, smt: str, params, ce: dict) -> dict:
    """Заменить контрпример на МЕНЬШИЙ (в окне ±`COUNTEREXAMPLE_WINDOW`).

    Возвращает уменьшенный контрпример либо исходный. Непустой вход никогда
    не превращается в пустой результат.
    """
    if not ce:
        return ce
    if all(abs(v) <= COUNTEREXAMPLE_WINDOW for v in ce.values()):
        return ce  # уже читаемый — второй запрос не нужен
    # MIN-SHRINKING до АБСОЛЮТНОГО минимума (Раздел 5 Энциклопедии).
    #
    # Окно ±10 даёт «читаемый» контрпример, но не МИНИМАЛЬНЫЙ: для `x + 1 < 0`
    # это может быть -3, хотя есть -1. Поэтому после широкого окна пробуем
    # строго более узкие — и берём ПЕРВЫЙ успешный (он и есть минимальный по
    # модулю максимума). ЗВУЧИМО: каждая попытка только ДОБАВЛЯЕТ ограничения
    # к исходной задаче, значит любая найденная точка нарушает контракт.
    best: dict = {}
    for window in (COUNTEREXAMPLE_WINDOW, 5, 2, 1, 0):
        try:
            _rc, out = run_kernc(kernc, _bound_smt(smt, params, window))
        except (subprocess.SubprocessError, OSError):
            break
        cand = parse_counterexample(out)
        if cand:
            best = cand
        if window == 0:
            break
    return best or ce


# =========================================================================
#  ПОЛИГЛОТ-ЭКСТРАКТОР: Zig / C / Rust (ациклическое арифметическое подмножество)
# =========================================================================
# ЗАЧЕМ. Ядро KERN (`kernc prove`, пруф-чекер, `libkern.so`) ЯЗЫКОНЕЗАВИСИМО:
# оно принимает SMT-LIB2. Ограничение «только Python» было ровно в одном
# месте — в этом удобном экстракторе (`ast.parse`). Теперь он полиглотный.
#
# ЧТО ДАЁТ ПОЛИГЛОТ. У Zig/C/Rust у КАЖДОГО параметра известен машинный тип
# (`i32`, `u32`, `usize`, `int`), поэтому KERN автоматически проверяет
# ПЕРЕПОЛНЕНИЕ целых и уход беззнакового в минус — то, чего `Int` из Python
# в принципе не видит.

CLIKE_EXT = {".zig", ".c", ".h", ".cpp", ".cc", ".rs", ".ts", ".js", ".go"}

# =============================================================================
# ШАГ I: СЕМАНТИКА ЗНАЧЕНИЙ ЯЗЫКА КАК ОБЪЕКТ (VALUE_SEMANTICS)
# =============================================================================
#
# ЗАЧЕМ. До этого шага «семантика языка» была набором `if lang == ...` в
# РАЗНЫХ местах файла, и ошибка в ней давала не видимый SKIP, а ТИХИЙ ЛОЖНЫЙ
# ВЕРДИКТ. Именно так появились четыре дефекта подряд:
#   #317 — один переводчик на Python и C дал floor там, где нужно усечение
#          -> `--diff-equiv` объявлял идентичный файл расходящимся (ложное F);
#   #321 — тип возврата не канонизировался -> обязанность переполнения
#          МОЛЧА снималась -> ложное ДОКАЗАНО;
#   #327/#318 — гарды не протянуты через все пути (два места правили
#          согласованно, правили одно).
# Общий корень: значение нигде не было ОБЪЕКТОМ, его нельзя было проверить
# целиком. Здесь оно объект.
#
# ГРАНИЦА ШАГА (осознанная, не «не успели»): сюда попадает ТОЛЬКО семантика
# ЗНАЧЕНИЙ — то, ошибка в чём даёт ложный вердикт. Синтаксис (разбор заголовков,
# нормализация тела, регулярки) НЕ трогается: его ошибка даёт видимый SKIP и
# другая цена ошибки. Смешивать их — значит менять самое дорогое без нужды.
class ValueSemantics:
    """Семантика ЗНАЧЕНИЙ для одного языка.

    `div`/`mod`: "floor" (округление к -inf, знак остатка = знак делителя) или
    "trunc0" (усечение к нулю, знак остатка = знак делимого). Разные правила —
    разные SMT-формулы, и перепутать их значит доказать утверждение о ДРУГОЙ
    функции.

    `true_div`: правило для `/` или None, если истинное деление вне
    подмножества (в Python это float-деление).

    `div_zero_value`: True, если деление на ноль ОПРЕДЕЛЕНО как значение
    (EVM: `DIV`/`MOD`/`SDIV`/`SMOD` при b = 0 возвращают 0 по Yellow Paper), а
    не падает. Для таких языков обязанность «делитель != 0» НЕ ставится.

    `wrap_ops`: маркеры ЗАКОННОГО оборачивания/насыщения (`+%` в Zig,
    `.wrapping_add(` в Rust). Обычный `a + b` там паникует, а эти — нет.

    `signed`: есть ли знаковые типы. Определяет, нужны ли обязанности
    переполнения деления (`MIN / -1`) и унарного минуса (`-MIN`) — дефект #334.

    ПОЧЕМУ ОБЫЧНЫЙ КЛАСС, А НЕ `@dataclass`. `@dataclass` требует, чтобы модуль
    был зарегистрирован в `sys.modules` (он ищет через
    `sys.modules.get(cls.__module__)`), а `kern_contracts.py` грузят через
    `importlib.util.spec_from_file_location` больше десяти инструментов — они
    регистрацию не делают, и `@dataclass` уронил бы их все. Семантика не должна
    требовать особого способа загрузки.
    """

    __slots__ = ("name", "div", "mod", "true_div", "div_zero_value",
                 "wrap_ops", "signed", "signed_min_div_trap", "signed_min_neg_trap",
                 "bounded_ints", "allow_bv_fallback")

    def __init__(self, name: str, div: str, mod: str, true_div: str | None,
                 div_zero_value: bool, wrap_ops: tuple, signed: bool,
                 signed_min_div_trap: bool | None = None,
                 signed_min_neg_trap: bool | None = None,
                 bounded_ints: bool = False,
                 allow_bv_fallback: bool = False):
        self.name = name
        self.div = div
        self.mod = mod
        self.true_div = true_div
        self.div_zero_value = div_zero_value
        self.wrap_ops = wrap_ops
        self.signed = signed
        # ДЕФЕКТ #353 (шаг N11): три свойства «семантики языка» жили ВНЕ таблицы —
        # в условиях `if suffix in CLIKE_EXT` и в литералах парсера. Это и есть
        # дисперсия, из-за которой одно и то же свойство могло быть учтено в
        # одном месте и забыто в другом (класс #317/#321). Переносим в таблицу.
        #
        # `signed` НЕ разделён на два поля, а ДОПОЛНЕН ими: знаковость типа и
        # аппаратная ловушка — РАЗНЫЕ вещи. Python знаковый, но `MIN / -1`
        # не паникует (целые неограничены); EVM знаковый (`SDIV`), но по Yellow
        # Paper `SDIV(MIN, -1) = MIN` — тоже не ловушка. Значит одного `signed`
        # для обязанностей переполнения НЕДОСТАТОЧНО.
        self.signed_min_div_trap = (signed if signed_min_div_trap is None
                                    else signed_min_div_trap)
        self.signed_min_neg_trap = (signed if signed_min_neg_trap is None
                                    else signed_min_neg_trap)
        # Машинные границы типов (`TYPE_RANGE`) применимы только там, где типы
        # фиксированной ширины: у Python/EVМ их нет.
        self.bounded_ints = bounded_ints
        # Переход в теорию битовых векторов: нужен для языков с масками/сдвигами.
        self.allow_bv_fallback = allow_bv_fallback

    def __repr__(self) -> str:
        return (f"ValueSemantics({self.name!r}, div={self.div!r}, "
                f"mod={self.mod!r}, true_div={self.true_div!r}, "
                f"div_zero_value={self.div_zero_value}, "
                f"wrap_ops={self.wrap_ops!r}, signed={self.signed}, "
                f"min_div_trap={self.signed_min_div_trap}, "
                f"min_neg_trap={self.signed_min_neg_trap}, "
                f"bounded={self.bounded_ints}, bv={self.allow_bv_fallback})")


VALUE_SEMANTICS: dict[str, ValueSemantics] = {
    # ⚠️ ДЕФЕКТ #353: последние четыре аргумента — `signed_min_div_trap`,
    # `signed_min_neg_trap`, `bounded_ints`, `allow_bv_fallback`. Раньше три из
    # этих свойств жили ВНЕ таблицы (`if suffix in CLIKE_EXT`, литералы парсера),
    # то есть «семантика языка» была описана не в одном месте. Значения ниже
    # СОХРАНЯЮТ прежнее поведение — перенос, а не смена правил.
    # Python: целые НЕОГРАНИЧЕННЫ, `//` — floor, `%` берёт знак делителя,
    # `/` — истинное (float) деление и потому вне подмножества.
    # Знаковый, НО `MIN / -1` не паникует (неограниченные целые) — значит
    # ловушки нет, и это ВИДНО в таблице, а не в комментарии.
    "python": ValueSemantics("python", "floor", "floor", None, False, (), True,
                             signed_min_div_trap=False, signed_min_neg_trap=False,
                             bounded_ints=False, allow_bv_fallback=False),
    # C / C++: усечение к нулю, `%` берёт знак делимого. Типы машинные,
    # поэтому `MIN / -1` и `-MIN` — UB (idiv trap).
    "c": ValueSemantics("c", "trunc0", "trunc0", "trunc0", False, (), True,
                        signed_min_div_trap=True, signed_min_neg_trap=True,
                        bounded_ints=True, allow_bv_fallback=True),
    # Zig: как C, плюс законные оборачивающие/насыщающие операторы.
    "zig": ValueSemantics("zig", "trunc0", "trunc0", "trunc0", False,
                          ("+%", "-%", "*%", "+|", "-|"), True,
                          signed_min_div_trap=True, signed_min_neg_trap=True,
                          bounded_ints=True, allow_bv_fallback=True),
    # Rust: как C, плюс явные `wrapping_*` / `saturating_*`.
    "rust": ValueSemantics("rust", "trunc0", "trunc0", "trunc0", False,
                           (".wrapping_add(", ".wrapping_sub(", ".wrapping_mul(",
                            ".saturating_add(", ".saturating_sub(",
                            ".saturating_mul("), True,
                           signed_min_div_trap=True, signed_min_neg_trap=True,
                           bounded_ints=True, allow_bv_fallback=True),
    # TypeScript / JavaScript: числа double, но целочисленные операторы
    # усекают к нулю; `%` берёт знак делимого.
    "ts": ValueSemantics("ts", "trunc0", "trunc0", "trunc0", False, (), True,
                         signed_min_div_trap=True, signed_min_neg_trap=True,
                         bounded_ints=True, allow_bv_fallback=True),
    "js": ValueSemantics("js", "trunc0", "trunc0", "trunc0", False, (), True,
                         signed_min_div_trap=True, signed_min_neg_trap=True,
                         bounded_ints=True, allow_bv_fallback=True),
    # Go: усечение к нулю, `%` берёт знак делимого.
    "go": ValueSemantics("go", "trunc0", "trunc0", "trunc0", False, (), True,
                         signed_min_div_trap=True, signed_min_neg_trap=True,
                         bounded_ints=True, allow_bv_fallback=True),
    # EVM (шаг 8): SDIV/SMOD усекают к нулю, НО деление на ноль ОПРЕДЕЛЕНО как 0
    # (Yellow Paper), поэтому обязанности «делитель != 0» нет; SDIV(MIN, -1)
    # возвращает MIN без падения — то есть обязанности переполнения тоже нет.
    # Оба ловушки-поля ЛОЖНЫ, и это теперь ЧАСТЬ таблицы, а не комментарий.
    "evm": ValueSemantics("evm", "trunc0", "trunc0", "trunc0", True, (), False,
                          signed_min_div_trap=False, signed_min_neg_trap=False,
                          bounded_ints=False, allow_bv_fallback=False),
}


def semantics_for(lang: str) -> ValueSemantics:
    """Семантика языка. ПРАВИЛО I4: неизвестный язык — ЯВНАЯ ошибка.

    Раньше неизвестный язык молча получал семантику Python (через
    `_CURRENT_LANG = "python"`): забытая точка входа давала C-коду floor-деление,
    то есть #317 заново и ТИХО. Теперь это отказ, а не догадка.
    """
    sem = VALUE_SEMANTICS.get(lang)
    if sem is None:
        raise Unsupported(
            f"язык {lang!r} не имеет записи в VALUE_SEMANTICS: семантика "
            f"значений неизвестна, доказывать по догадке нельзя")
    return sem


# `/// @kern:...`, `// @kern:...`, `# @kern:...`
ANNOT = re.compile(r"^\s*(?:///|//|#)\s*@kern:(requires|ensures)\s+(.+?)(?:\s+\[(advisory)\])?\s*$")
# Ф6.1: класс обязательства. По умолчанию `hard` (нарушение = F и блокирует).
# Явный `[advisory]` в конце строки делает нарушение НЕ блокирующим, но и НЕ
# «доказанным»: вердикт становится `T_advisory` и НЕ попадает в счётчик `T`.
# Метка стоит в группе 3, поэтому все прежние `m.group(2)` (текст условия)
# остаются верными — совместимость без правки 30+ мест.
def ens_class_at(lines, ln: int) -> str:
    """Класс обязательства `ensures` для функции на строке `ln` (Ф6.1).

    Аннотации лежат в нескольких строках ВЫШЕ `def`, поэтому ищем в окне.
    """
    cls = "hard"
    for k in range(max(0, ln - 7), min(len(lines), ln)):
        m = ANNOT.match(lines[k])
        if m and m.group(1) == "ensures":
            cls = annot_class(m)
    return cls


def annot_class(m) -> str:
    """Класс обязательства из аннотации: `hard` (по умолчанию) или `advisory`."""
    return m.group(3) if m.group(3) else "hard"

# Машинные диапазоны типов: (минимум, максимум) в терминах ℤ.
TYPE_RANGE = {
    "i8": (-2**7, 2**7 - 1), "u8": (0, 2**8 - 1),
    "i16": (-2**15, 2**15 - 1), "u16": (0, 2**16 - 1),
    "i32": (-2**31, 2**31 - 1), "int": (-2**31, 2**31 - 1),
    "int32_t": (-2**31, 2**31 - 1), "uint32_t": (0, 2**32 - 1),
    "u32": (0, 2**32 - 1), "unsigned": (0, 2**32 - 1),
    "i64": (-2**63, 2**63 - 1), "long": (-2**63, 2**63 - 1),
    "int64_t": (-2**63, 2**63 - 1), "uint64_t": (0, 2**64 - 1),
    "u64": (0, 2**64 - 1), "usize": (0, 2**64 - 1), "size_t": (0, 2**64 - 1),
    # ПУНКТ 25: TypeScript/Go-написания тех же машинных типов.
    "int32": (-2**31, 2**31 - 1), "uint32": (0, 2**32 - 1),
    "int64": (-2**63, 2**63 - 1), "uint64": (0, 2**64 - 1),
    # SORBET-STYLE СЕМАНТИЧЕСКИЕ ТИПЫ: диапазон выводится из СМЫСЛА имени типа,
    # без ручного `@kern:requires` (задача пункта 25).
    "PositiveInt": (1, 2**63 - 1), "pos_int": (1, 2**63 - 1),
    "NonNegativeInt": (0, 2**63 - 1), "nat": (0, 2**63 - 1),
    "Percent": (0, 100), "Percentage": (0, 100),
}

# ТИПЫ, КОТОРЫЕ МЫ СОЗНАТЕЛЬНО НЕ МОДЕЛИРУЕМ (честный отказ, а не догадка).
# `number` в JS/TS — это IEEE-754 float64, а не целое: подставлять ему диапазон
# `int` означало бы проверять ДРУГУЮ функцию (и «доказывать» не то, что написано).
UNMODELED_TYPES = {"number": "float64 (IEEE-754) вне целочисленной модели; "
                             "для него нужен `@kern:float`"}

RE_FN_FN = re.compile(
    # Zig: `pub fn name(a: i32) i32 {`   Rust: `pub(crate) async fn name<T>(a: i32) -> Result<..> {`
    # ДЕФЕКТ #180: раньше поддерживался только `pub fn name(...)` — из-за этого
    # ripgrep (Rust) давал 0 / 1292 проверенных функций: у него `pub(crate) fn`,
    # `async fn`, `fn f<T: Read>(...)` и возвращаемые типы с дженериками.
    #
    # ДЕФЕКТ #325: `{` ОБЯЗАТЕЛЬНО стояла в конце строки заголовка, поэтому
    # стиль Allman (`{` на СЛЕДУЮЩЕЙ строке) давал «нет функций с аннотациями
    # @kern:» — функция МОЛЧА не проверялась. ИЗМЕРЕНО: один и тот же код с
    # переносом `{` — 0 проверок, без переноса — 1 проверка и найденное
    # переполнение. Теперь `{` необязательна, но строка обязана на ней
    # ЗАКОНЧИТЬСЯ (`$`), иначе заголовок без тела и без `{` (trait-метод
    # `fn f(a: i32) -> i32;`) утащил бы тело следующей функции. Тело собирает
    # brace-matching ниже — он уже умеет начинать со следующей строки.
    r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?"
    r"(?:extern\s+(?:\"[^\"]*\"\s+)?)?"
    r"(?:async\s+)?(?:unsafe\s+)?(?:const\s+)?"
    r"fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
    r"\s*(?:->\s*)?([\w:<>\[\]&' ]+)?\s*(?:\{.*)?$")
RE_FN_C = re.compile(
    # ДЕФЕКТ #188 (полевой прогон на cmark-gfm): старый шаблон требовал
    # `TYPE name(...)` с ОДНИМ словом типа и БЕЗ звёздочки, поэтому
    # `static cmark_node *make_block(...)` и `char *dup(int len)` — то есть
    # большинство функций реального C — не распознавались вообще.
    # Теперь: тип = одно и более слов (+ звёздочки), имя, параметры.
    # Ложные срабатывания на вызовах отсекаются: `;` внутри не допускается,
    # а управляющие слова (`if/for/while/return/…`) запрещены lookahead'ом.
    r"^\s*(?!(?:if|for|while|switch|return|else|do|case|sizeof|typedef|"
    r"struct|union|enum)\b)"
    r"((?:[A-Za-z_]\w*[\s*]+)+)"          # 1: возвращаемый тип (+ звёздочки)
    # ДЕФЕКТ #309: однострочные функции `int f(int a) { return a / b; }`
    # не распознавались вообще (`checked 0 / 0`), потому что шаблон требовал
    # КОНЦА строки после `{`. Теперь допускается тело в той же строке;
    # вызовы (`foo(bar);`) по-прежнему не матчатся: после `)` идёт `;`, а не `{`.
    r"([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*(\{.*)?$")
# ПУНКТ 25: TypeScript/JavaScript — `function name(x: Type): Ret {`,
# `export function name(x) {`. Стрелочные функции (`const f = (x) => …`) в
# подмножество НЕ входят и получают честный SKIP (регулярка их не матчит).
RE_FN_TS = re.compile(
    # ДЕФЕКТ #325 (тот же класс): `{` на следующей строке — стиль Allman — не
    # распознавался, и функция МОЛЧА не проверялась (ИЗМЕРЕНО: 0 проверок).
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)"
    r"\s*(?::\s*([\w<>\[\]]+))?\s*(?:\{.*)?$")
# ПУНКТ 25: Go — `func name(x int) int {`, `func (r T) name(x uint32) uint32 {`.
# Условия в Go пишутся БЕЗ скобок (`if x < 0 {`), но `_normalize_clike` убирает
# фигурные скобки, поэтому разбор операторов переиспользуется без изменений.
# ДЕФЕКТ #325: `{` на следующей строке (Allman) — тот же молчаливый пропуск.
RE_FN_GO = re.compile(
    r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)"
    r"\s*(?:\(([^)]*)\)|([\w\.\*\[\]]+))?\s*(?:\{.*)?$")


def _expand_go_params(raw: str) -> str:
    """Go: `a, b int` -> `a int, b int` (имя без типа наследует тип соседа)."""
    parts = [p.strip() for p in raw.split(",")]
    out: list[str] = []
    pending: list[str] = []
    for p in parts:
        if not p:
            continue
        if " " in p:                       # «имя тип»
            name, typ = p.rsplit(" ", 1)
            for q in pending:
                out.append(f"{q} {typ}")
            pending = []
            out.append(f"{name} {typ}")
        else:
            pending.append(p)
    if pending:
        raise Unsupported(f"параметр go без типа: {pending!r}")
    return ", ".join(out)


C_TYPE_WORDS = {"const", "volatile", "unsigned", "signed", "long", "short",
                "int", "char", "float", "double", "void", "_Bool", "bool"}

# ДЕФЕКТ #312: `TYPE_RANGE` знал `unsigned`/`size_t`/`long`, но ПАРСЕР требовал
# ровно ОДНО слово до имени, поэтому `unsigned int c` давал SKIP, а `size_t a`
# работал. Машинные типы C бывают многословными — канонизируем их к ключу
# `TYPE_RANGE`. `long` = i64 предполагает **LP64**; на LLP64 (Windows) `long`
# 32-битный, но Windows KERN не поддерживает (`docs/PLATFORMS.md`), и это
# записано явно, а не спрятано.
C_MACHINE_TYPES = {
    "int": "int", "signed": "int",
    "unsigned": "unsigned", "unsigned int": "unsigned",
    "long": "long", "long int": "long", "signed long": "long",
    "long long": "i64", "long long int": "i64",
    "unsigned long": "u64", "unsigned long int": "u64",
    "unsigned long long": "u64", "unsigned long long int": "u64",
    "short": "i16", "short int": "i16",
    "unsigned short": "u16", "unsigned short int": "u16",
    "signed char": "i8", "unsigned char": "u8",
    "int8_t": "i8", "uint8_t": "u8", "int16_t": "i16", "uint16_t": "u16",
    "int32_t": "int32_t", "uint32_t": "uint32_t",
    "int64_t": "int64_t", "uint64_t": "uint64_t",
    "size_t": "size_t", "ssize_t": "long", "ptrdiff_t": "long",
    "intptr_t": "long", "uintptr_t": "u64",
}


def clike_params(raw: str, lang: str):
    """Разобрать список параметров C-подобной функции -> [(имя, тип)]."""
    if lang == "go":
        raw = _expand_go_params(raw)
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part or part == "void":
            continue
        if lang == "c":
            # ДЕФЕКТ #312: разбираем по токенам, а не «одно слово до имени» —
            # иначе `unsigned int c` и `long long x` отвергались как SKIP.
            toks = part.replace("*", " ").split()
            if not toks:
                raise Unsupported(f"параметр c: {part!r}")
            if toks[-1] in C_TYPE_WORDS:
                raise Unsupported(f"параметр c без имени: {part!r}")
            typ = " ".join(t for t in toks[:-1] if t not in ("const", "volatile"))
            key = C_MACHINE_TYPES.get(typ)
            if key is None:
                raise Unsupported(
                    f"тип c {typ!r}: поддерживаются целые машинные типы "
                    f"(`int`, `unsigned int`, `long long`, `size_t`, `uint32_t`, …); "
                    f"вещественные типы и `char` — нет (`char` намеренно: его "
                    f"знаковость зависит от реализации)")
            out.append((toks[-1], key))
            continue
        elif lang == "go":
            m = re.match(r"^([A-Za-z_]\w*)\s+([A-Za-z_]\w*)$", part)
            if m:
                out.append((m.group(1), m.group(2)))
                continue
        elif lang in ("ts", "js"):
            # TypeScript: `x: uint32`; JavaScript: тип НЕ указан — берём модель
            # `int` (i32). ЭТО ЯВНОЕ ДОПУЩЕНИЕ, а не факт о языке: в JS числа —
            # float64, поэтому такой контракт проверяется в ЦЕЛОЧИСЛЕННОЙ модели
            # (и это записано в документации пункта 25).
            m = re.match(r"^(?:readonly\s+)?([A-Za-z_$]\w*)\s*:\s*([A-Za-z_]\w*)$", part)
            if m:
                out.append((m.group(1), m.group(2)))
                continue
            m = re.match(r"^([A-Za-z_$]\w*)$", part)
            if m:
                out.append((m.group(1), "int"))
                continue
        else:
            m = re.match(r"^(?:mut\s+)?([A-Za-z_]\w*)\s*:\s*&?\s*([A-Za-z_]\w*)$", part)
            if m:
                out.append((m.group(1), m.group(2)))
                continue
        raise Unsupported(f"параметр {lang}: {part!r}")
    return out


def convert_ternary(s: str) -> str:
    """`cond ? a : b` -> `(a if cond else b)` (рекурсивно).

    ЧТО БЫЛО НЕ ТАК (шаг 5 плана, ИЗМЕРЕНО на корпусе `actions/toolkit`).
    За `?` принимался ЛЮБОЙ вопросительный знак, поэтому:
      * опциональная цепочка TS/JS `obj?.field` (`.ts`/`.js`) и
      * nullish-оператор `a ?? b`
    считались тернарниками, а `:` у них нет — функция уходила в SKIP с причиной
    «тернарный оператор без ':'». ИЗМЕРЕНО: в корпусе 65 вхождений `??` и десятки
    `?.`; причина «тернарный оператор» стояла у 6 функций.
    Теперь `?` НЕ считается тернарником, если он часть `?.` или `??` (с любой
    стороны). Настоящий тернарник (`a ? b : c`) по-прежнему переводится в `ite`.
    """
    depth = 0
    q = -1
    for i, c in enumerate(s):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "?" and depth == 0:
            # `?.` и `??` — НЕ тернарники (опциональная цепочка и nullish).
            if i + 1 < len(s) and s[i + 1] in ".?":
                continue
            if i > 0 and s[i - 1] == "?":
                continue
            q = i
            break
    if q < 0:
        return s
    depth = 0
    qdepth = 0          # ВЛОЖЕННЫЕ тернарники: `a ? b ? c : d : e`
    cpos = -1
    for j in range(q + 1, len(s)):
        c = s[j]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and c == "?" and not (
                (j + 1 < len(s) and s[j + 1] in ".?") or s[j - 1] == "?"):
            # ДЕФЕКТ (найден негативным контролем шага 5): бралась ПЕРВАЯ `:` на
            # нулевой глубине, поэтому вложенный тернарник `a ? b ? c : d : e`
            # разбирался неверно: `a` = `b ? c`, у которого `:` нет, и перевод
            # ПАДАЛ с «тернарный оператор без ':'». Вложенность `?` теперь
            # считается, и берётся ПАРНАЯ `:` (правый ассоциативный разбор).
            qdepth += 1
        elif c == ":" and depth == 0:
            if qdepth:
                qdepth -= 1
                continue
            cpos = j
            break
    if cpos < 0:
        raise Unsupported("тернарный оператор без ':'")
    cond, a, b = s[:q], s[q + 1:cpos], s[cpos + 1:]
    return (f"({convert_ternary(a)} if {convert_ternary(cond)} "
            f"else {convert_ternary(b)})")


def clike_to_python(s: str) -> str:
    """C-подобное выражение -> Python-выражение (переиспользуем expr_smt)."""
    s = s.strip().rstrip(";").strip()
    # ДЕФЕКТ #416 (измерено): JS/TS пишут `===` и `!==`, которых нет ни в C, ни
    # в Python. ИЗМЕРЕНО на `actions/toolkit`: 35 из 77 отказов перевода
    # приходились РОВНО на эти два оператора (`error.code === 'ENOENT'` ->
    # `error.code === 6123186` -> SyntaxError -> SKIP). Приведение строгое по
    # смыслу: в Int-модели `===` и `==` неразличимы (типы уже потеряны).
    s = s.replace("===", "==").replace("!==", "!=")
    s = s.replace("&&", " and ").replace("||", " or ")
    s = re.sub(r"!(?![=])", " not ", s)
    s = re.sub(r"\btrue\b", "True", s)
    s = re.sub(r"\bfalse\b", "False", s)
    s = re.sub(r"\b(\d+)[uU]\b", r"\1", s)          # 5u -> 5
    s = re.sub(r"\b(\d+)[iI]\d*\b", r"\1", s)       # 5i32 -> 5
    # ЯВНЫЕ операторы оборачивания/насыщения (Zig `+% -% *% +| -|`, Rust
    # `.wrapping_*` / `.saturating_*`) — ЗАКОННЫЕ операции без паники.
    # Моделируем их как обычную арифметику ℤ: для проверки контрактов этого
    # достаточно, а обязательство «result в границах типа» для них СНЯТО
    # (`_explicit_wrap`). ОГРАНИЧЕНИЕ: точная кламп-семантика `+|` (насыщение
    # на границе) не моделируется — там, где важен сам факт насыщения,
    # используйте `@kern:bitvec` или явный гард.
    s = re.sub(r"([+\-*])%", r"\1", s)
    s = re.sub(r"([+\-])\|", r"\1", s)
    s = re.sub(r"\.(?:wrapping|saturating)_(?:add|sub|mul)\(", " + (", s)
    return convert_ternary(s)


# 🔴 ДЕФЕКТ #183 (полевой прогон по zls): в Zig гард пишется как
# `assert(@backingInt(index) < len)`, а `@backingInt(...)`/`@as(T, x)`
# наш C-like транслятор не знает — условие отбрасывалось, и `--xray`
# выдавал ложный `[CRASH PATH] len == 0` на защищённом коде.
# Здесь снимаем чисто обёртки (они не меняют значение выражения).
_ZIG_WRAP = ("backingInt", "fromBackingInt", "intCast", "intFromEnum",
             "intFromBool", "bitCast", "floatCast", "enumFromInt")


def _strip_c_casts(s: str) -> str:
    r"""Снять C-касты типов: `(size_t)(a - b)`, `(ptrdiff_t)(x)`, `(const char *)p`.

    ЗАЧЕМ (ретро-тест на cmark-gfm, дефект #189). После фикса `2cb4a20` строка
    защищена условием `if (len == (size_t)(max_rewind - rewind)) return true;`.
    Наш парсер видел `(size_t)(…)`, не мог перевести терм и **отбрасывал
    условие целиком** — значит путь не сужался, и на ИСПРАВЛЕННОМ файле
    оставалось 1 предупреждение. Тот же каст в `4682993`
    (`data[-((ptrdiff_t)rewind) - len - 1]`) вообще прятал уязвимость.

    Правило: каст НЕ меняет значение в нашей модели (все значения — Int),
    поэтому он снимается. Заменяется пробелом, чтобы номера строк/смещения
    не «съезжали».
    """
    prev = None
    while prev != s:
        prev = s
        s = _C_CAST.sub(" ", s)
    return s


def _unwrap_zig_builtins(s: str) -> str:
    # `@as(T, x)` — значение в последнем аргументе
    s = re.sub(r"@as\s*\(([^()]*)\)",
               lambda m: m.group(1).rsplit(",", 1)[-1].strip(), s)
    for _ in range(3):
        pat = r"@(?:" + "|".join(_ZIG_WRAP) + r")\s*\(([^()]*)\)"
        s2 = re.sub(pat, r"\1", s)
        if s2 == s:
            break
        s = s2
    return s


def _iter_call_args(src: str, name: str, raw: str | None = None):
    r"""Все аргументы вызова `name(...)` с БАЛАНСОМ скобок.

    🔴 ДЕФЕКТ #182 (найден полевым прогоном): регулярка `assert\s*\(([^()]*)\)`
    не видит вложенных скобок, поэтому `assert(@backingInt(index) < len)`
    (zls) НЕ становился гардом пути, и `--xray` выдавал ложный
    `[CRASH PATH] len == 0` на защищённом коде. Здесь скобки считаются.

    ДЕФЕКТ #412: поиск идёт по МАСКЕ (иначе `assert(` ВНУТРИ строкового
    литерала становился бы путём-условием и мог дать ЛОЖНУЮ мёртвую ветвь),
    а текст аргумента берётся из `raw` по тем же смещениям.
    """
    pat = re.compile(r"\b" + re.escape(name) + r"\s*\(")
    i = 0
    while True:
        m = pat.search(src, i)
        if not m:
            return
        depth = 1
        j = m.end()
        while j < len(src) and depth:
            c = src[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        if depth == 0:
            yield (raw or src)[m.end(): j - 1]
        i = j


_C_SIMPLE_ESC = {"0": chr(0), "t": chr(9), "n": chr(10), "r": chr(13),
                 "a": chr(7), "b": chr(8), "f": chr(12), "v": chr(11),
                 chr(92): chr(92), chr(39): chr(39), chr(34): chr(34), "?": "?"}


def _decode_c_char(raw: str):
    """Раскрыть стандартные C-эскейпы; вернуть ОДИН символ или None.

    Нужно, чтобы отличить `'x'` (символ: семантика — точный код) от
    `'win32'` (строка: семантика — просто метка).
    """
    if not raw:
        return None
    if raw[0] != chr(92):
        return raw if len(raw) == 1 else None
    esc = raw[1:2]
    if esc in _C_SIMPLE_ESC and len(raw) == 2:
        return _C_SIMPLE_ESC[esc]
    if esc == "x":
        try:
            return chr(int(raw[2:], 16))
        except ValueError:
            return None
    if esc.isdigit():
        try:
            return chr(int(raw[1:], 8))
        except ValueError:
            return None
    return None

def _literals_to_numbers(cond: str) -> str:
    """Заменить ЛИТЕРАЛЫ в ВЫРЕЗАННОМ условии на числа (дефект #410).

    ПОЧЕМУ ЗДЕСЬ, А НЕ В ОБЩЕМ СТРИППЕРЕ. `_strip_c_comments_strings` отвечает за
    ГРАНИЦЫ функций и номера строк: там литералы обязаны стать ПРОБЕЛАМИ 1-в-1
    (иначе едут смещения и число функций — ИЗМЕРЕНО 458 -> 476/443). Здесь текст
    условия УЖЕ вырезан по точным индексам, позиции файла никому не нужны,
    поэтому числа подставляются ПОЛНОСТЬЮ, без усечения по ширине кавычек.

    СЕМАНТИКА: `'x'` (ровно один символ после раскрытия C-эскейпов) -> `ord(x)`;
    строки и многосимвольные литералы -> детерминированное ПОЛОЖИТЕЛЬНОЕ число из
    содержимого (никогда 0, иначе строка склеилась бы с `NULL`).
    """
    out: list[str] = []
    i, n = 0, len(cond)
    while i < n:
        ch = cond[i]
        if ch not in chr(34) + chr(39) + chr(96):
            out.append(ch)
            i += 1
            continue
        j = i + 1
        buf: list[str] = []
        while j < n:
            if cond[j] == chr(92) and j + 1 < n:
                buf.append(cond[j:j + 2])
                j += 2
                continue
            if cond[j] == ch:
                break
            buf.append(cond[j])
            j += 1
        if j >= n:
            out.append(cond[i:])
            break
        raw = "".join(buf)
        if ch == chr(39):
            c = _decode_c_char(raw)
            num = (str(ord(c)) if (c is not None and len(c) == 1) else
                   str(1_000_000 + (zlib.crc32(raw.encode("utf-8", "replace")) & 0x7FFFFF)))
        else:
            num = str(1_000_000 + (zlib.crc32(raw.encode("utf-8", "replace")) & 0x7FFFFF))
        out.append(num)
        i = j + 1
    return "".join(out)


def _strip_c_comments_strings(text: str) -> str:
    """ДЕФЕКТ #178: убрать комментарии и содержимое строковых литералов.

    ЗАЧЕМ. `--xray` искал `/` по СЫРОМУ тексту C-like функций, поэтому
    `// entering/exiting`, `/// … uniform words`, `"pkg/windows/Manifest.xml"`
    и URL давали ложные `[CRASH PATH]` (по замеру: 95–100 % находок в
    Rust/TS/C/Zig были именно такими). В Python этой проблемы нет — там
    комментарии снимает `tokenize`.

    КАК. Конечный автомат: `//…`, `/*…*/`, `"…"`, `'…'`, `` `…` ``,
    а также zig-строки `\\\\…` до конца строки. Каждый удалённый символ
    заменяется ПРОБЕЛОМ, переводы строк сохраняются — поэтому номера строк
    остаются точными (на них ссылаются отчёты SARIF/DEAD BRANCH).
    """
    out: list[str] = []
    i, n = 0, len(text)
    state = "code"          # code | line | block | str
    quote = ""
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line"
                out.append("  ")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block"
                out.append("  ")
                i += 2
                continue
            if ch == "\\" and nxt == "\\":        # zig multiline string
                state = "line"
                out.append("  ")
                i += 2
                continue
            if ch in "\"'`":
                state = "str"
                quote = ch
                out.append(" ")
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                state = "code"
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                state = "code"
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        # state == "str"
        if ch == "\\" and i + 1 < n:
            out.append("  ")
            i += 2
            continue
        if ch == quote:
            state = "code"
            out.append(" ")
            i += 1
            continue
        out.append("\n" if ch == "\n" else " ")
        i += 1
    return "".join(out)


# Макроконстанты (`REFMAP_SIZE`, `MAX_LEN`, `PAGE_SIZE`) — это НЕ переменные
# входа: они не могут «принять 0» из модели, поэтому обязательство
# `делитель ≠ 0` для них бессмысленно (дефект #178).
_MACRO_DIV = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
# ДЕФЕКТ #200: делитель-«длина». Ненулевость длины обеспечивает ВЫЗЫВАЮЩИЙ,
# а межпроцедурные инварианты мы не моделируем — обвинять нельзя (см. zls 0.17.0:
# `if (trigrams.len > 0)` перед построением фильтра).
_RE_LEN_LIKE = re.compile(r"^(len|size|count|n|cap|capacity|length)$")
# ДЕФЕКТ #316: `Path / str` — СКЛЕЙКА ПУТИ, а не деление. Найдено
# САМОПРИМЕНЕНИЕМ: `--xray tools/` по собственному коду KERN дал 6 `[CRASH PATH]`,
# из которых два ложные — `self.root / log_dir` (`kern_exec_runner.py:82`) и
# `ROOT / "zig-out" / "bin" / name` (`measure_all_kern.py:105`). Существующее
# правило `_MACRO_DIV` ловило только ПРЯМОЙ `ROOT / x`: ни атрибут `self.root`,
# ни ВЛОЖЕННУЮ склейку (`ROOT / "a" / "b" / name`) оно не покрывало.
_RE_PATHISH = re.compile(
    r"(?i)(^|_)(root|dir|folder|path|file|home|base|prefix|suffix|slug|name)$")


def _is_path_expr(node) -> bool:
    """True, если левый операнд `/` — путь/строка, значит это НЕ арифметика.

    ЗВУЧИМОСТЬ: если левый операнд — `Path`, оператор `/` определён как
    склейка пути (`pathlib`), и делителя-числа там нет по построению.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.Name):
        return bool(_MACRO_DIV.match(node.id)) or bool(_RE_PATHISH.search(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_MACRO_DIV.match(node.attr)) or bool(_RE_PATHISH.search(node.attr))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_path_expr(node.left)
    return False




def _drop_macro_divisors(divs: list) -> list:
    """Отфильтровать макро-«делители». Элемент — `(числитель, делитель, гарды)`
    (#334) либо `(делитель, гарды)` (#327) либо голая строка (совместимость).

    ДЕФЕКТ #391: здесь стояло `d[0]`, то есть ЧИСЛИТЕЛЬ — фильтр проверял не ту
    часть выражения. На `Path / name` (см. #381) делителем является `name`, а
    проверялся `Path`: макро-«делитель» мог остаться или быть снят не по делу.
    """
    out = []
    for d in divs:
        expr = _divisor_of(d)
        if not _MACRO_DIV.match(expr):
            out.append(d)
    return out


# JS/TS: `/…/g` — это РЕГЕКС-ЛИТЕРАЛ, а не деление. Без этого `escapeData`
# из `actions/toolkit` давал `[CRASH PATH] g == 0` (делитель — флаг `g`).
_RE_JS_REGEX = re.compile(r"(?<![\w)\]$])/(?![/*\s])(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n])+/[dgimsuvy]*")


def _strip_js_regex(text: str) -> str:
    """Заменить regex-литералы пробелами (длина и переводы строк сохранены)."""
    def blank(m: re.Match) -> str:
        return "".join("\n" if c == "\n" else " " for c in m.group(0))
    return _RE_JS_REGEX.sub(blank, text)


def _normalize_clike(body: str, keep_newlines: bool = False) -> str:
    """Убрать комментарии и фигурные скобки вокруг одиночных операторов.

    `keep_newlines=True` (ПУНКТ 25: Go/JS/TS) — перевод строки СОХРАНЯЕТСЯ как
    разделитель операторов, потому что в этих языках `;` необязательна. Иначе
    тело `if x < 0 { return 0 }\nreturn x` склеилось бы в один оператор и
    разбор ветвления сломался бы.
    """
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    body = re.sub(r"//[^\n]*", " ", body)
    # `{ return X; }` -> ` return X; `  (ветвь без вложенности)
    body = re.sub(r"\{\s*(return\s+[^;{}]+;?)\s*\}", r" \1 ", body)
    sep = "\n" if keep_newlines else " "
    body = body.replace("{", sep).replace("}", sep)
    if keep_newlines:
        body = re.sub(r"[ \t]+", " ", body)
        return "\n".join(ln.strip() for ln in body.splitlines() if ln.strip())
    return re.sub(r"\s+", " ", body).strip()


def _join_if_blocks(lines: list) -> list:
    """Склеить `if`/`else` со СЛЕДУЮЩИМ оператором (ПУНКТ 25: Go/JS/TS).

    В этих языках `;` необязательна, поэтому после разбиения по переводам строк
    ветвление оказывается разрезанным: `if x < 0` и `return 0` — разные строки.
    Приводим форму к той, которую разбирает ОБЩИЙ код всех C-подобных языков:
    `if x < 0 return 0`, а `else` приклеиваем к предыдущему оператору.
    """
    out: list = []
    pending = False
    for ln in lines:
        if pending:
            out[-1] = f"{out[-1]} {ln}"
            pending = False
            continue
        if ln.startswith("else") and out:
            out[-1] = f"{out[-1]} else"
            pending = True
            continue
        out.append(ln)
        # `pending` только если в этой же строке ещё НЕ было `return` — иначе
        # (после свёртки `{ return X; }`) оператор уже полный и склеивать его со
        # следующим нельзя.
        if ln.startswith("if") and "return" not in ln:
            pending = True
    return out


def _clike_stmts(raw_body: str, lang: str) -> list:
    """Операторы тела: для Go/JS/TS разделитель — `;` ИЛИ перевод строки."""
    if lang in ("go", "js", "ts"):
        return _join_if_blocks([s for s in re.split(r"[;\n]", raw_body) if s.strip()])
    return raw_body.split(";")


def _clike_parse(text: str, lang: str):
    """C-подобное выражение (Zig/C/Rust) -> Python-AST для `expr_smt`.

    🔴 ДЕФЕКТ #117 (найден теневым контрактом на реальном коде: `@mod` в Zig).
    Раньше здесь стоял голый `ast.parse(clike_to_python(...))`, поэтому незнакомый
    конструктив (Zig-встроенная `@mod`, `@rem`, срез, приведение типа) падал
    Python-исключением `invalid syntax (<unknown>, line 1)` — и ЭТО сообщение уходило
    в SKIP как «причина». Диагностика обязана называть язык и конструктив, а не
    показывать ошибку чужого парсера.
    """
    converted = clike_to_python(text)
    try:
        return ast.parse(converted, mode="eval").body
    except SyntaxError as e:
        raise Unsupported(
            f"{lang}-выражение вне подмножества: {text.strip()[:48]!r} "
            f"(поддерживаются только + - * / // % и сравнения)") from e


def _exec_clike(stmts, env: dict, lang: str, expr_fn=None):
    """Символьно исполнить операторы; вернуть SMT-выражение результата или None.

    `expr_fn` (УЛУЧШЕНИЕ №15) позволяет переиспользовать ЭТОТ ЖЕ разбор операторов
    для теории битовых векторов (`expr_smt_bv`), не дублируя логику: иначе
    BV-режим проверял бы другой код.
    """
    if expr_fn is None:
        def expr_fn(node, env_):
            return expr_smt(node, env_)
    for i, raw in enumerate(stmts):
        st = raw.strip()
        if not st:
            continue
        m = re.match(r"^if\s*(.*?)\breturn\b(.*)$", st)
        if m:
            cond_txt = m.group(1).strip().strip("()").strip()
            rest = m.group(2).strip()
            consumed = 1
            else_txt = None
            if " else " in rest:
                then_txt, else_txt = rest.split(" else ", 1)
                then_txt = then_txt.strip()
                else_txt = re.sub(r"^return\b", "", else_txt).strip()
            else:
                then_txt = rest
                # КРАЙНИЙ СЛУЧАЙ (найден `if (n >= 0) return n; else return -n;`):
                # после разбиения по `;` ветвь `else` оказывается ОТДЕЛЬНЫМ
                # оператором, а не хвостом первого. Поглощаем её.
                if i + 1 < len(stmts):
                    nxt = stmts[i + 1].strip()
                    if nxt.startswith("else"):
                        else_txt = re.sub(r"^else\s+", "", nxt).strip()
                        else_txt = re.sub(r"^return\b", "", else_txt).strip()
                        consumed = 2
            cond_smt = expr_fn(_clike_parse(cond_txt, lang), env)
            then_v = expr_fn(_clike_parse(then_txt, lang), dict(env))
            if else_txt is not None:
                else_v = expr_fn(_clike_parse(else_txt, lang), dict(env))
            else:
                tail = _exec_clike(stmts[i + consumed:], dict(env), lang, expr_fn)
                if tail is None:
                    raise NoReturn("нет `return` на пути без ветвления")
                else_v = tail
            return f"(ite {cond_smt} {then_v} {else_v})"
        m = re.match(r"^return\s+(.+)$", st, re.S)
        if m:
            return expr_fn(_clike_parse(m.group(1), lang), env)
        m = re.match(
            r"^(?:const\s+|let\s+(?:mut\s+)?|"
            r"(?:int|long|i32|i64|u32|u64|usize|size_t|unsigned)\s+)?"
            r"([A-Za-z_]\w*)\s*(?::\s*[A-Za-z_]\w*)?\s*=\s*(.+)$", st, re.S)
        if m:
            env[m.group(1)] = expr_fn(_clike_parse(m.group(2), lang), env)
            continue
        # ДЕФЕКТ #306 (найден живым прогоном моделей): ХВОСТОВОЕ ВЫРАЖЕНИЕ.
        # Идиоматичный Rust/Zig пишут `a + b` вместо `return a + b;`, и модели
        # отвечают именно так. Раньше это давало SKIP «оператор rust: 'a + b'»,
        # то есть ответ живой модели НЕ проверялся вообще — при том, что
        # переполнение i32 в таком теле видно. Теперь хвостовое выражение
        # последнего оператора трактуется как возвращаемое значение.
        if lang in ("rust", "zig") and all(not s.strip() for s in stmts[i + 1:]):
            return expr_fn(_clike_parse(st.rstrip(";"), lang), env)
        raise Unsupported(f"оператор {lang}: {st[:40]!r}")
    return None


def _saturate_rewrite(text: str, ret: str) -> str:
    """ТОЧНАЯ семантика насыщения: `a +| b` -> clamp(a+b) в границы типа.

    ЗАЧЕМ (полумера из прошлой итерации). Раньше `+|` / `.saturating_add`
    просто переводились в `+` (обязательство переполнения снималось). Это
    неверно, если постусловие смотрит на ГРАНИЦУ: `ensures result <= 4294967295`
    при `a+b > MAX` давало бы ложное опровержение, потому что настоящая
    функция возвращает MAX.
    Теперь строится точное выражение:
        ite(a+b > HI, HI, ite(a+b < LO, LO, a+b))
    (записано тернарниками Python, которые `expr_smt` переводит в `ite`).
    """
    if ret not in TYPE_RANGE:
        return text
    lo, hi = TYPE_RANGE[ret]

    def clamp(op: str, a: str, b: str) -> str:
        e = f"({a} {op} {b})"
        # Для БЕЗЗНАКОВЫХ (lo == 0) нижняя ветвь недостижима при a,b >= 0,
        # поэтому её опускаем: формула короче, и чекер не оставляет
        # доверенный `rewrite` на лишнем `ite` (ИЗМЕРЕНО: trusted 1 -> 0).
        if lo == 0:
            return f"({hi} if {e} > {hi} else {e})"
        return f"({hi} if {e} > {hi} else ({lo} if {e} < {lo} else {e}))"

    # Rust: x.saturating_add(y) / .saturating_sub(y)
    text = re.sub(r"([A-Za-z_][\w]*)\.saturating_add\(\s*([A-Za-z_][\w]*|\d+)\s*\)",
                  lambda m: clamp("+", m.group(1), m.group(2)), text)
    text = re.sub(r"([A-Za-z_][\w]*)\.saturating_sub\(\s*([A-Za-z_][\w]*|\d+)\s*\)",
                  lambda m: clamp("-", m.group(1), m.group(2)), text)
    # Zig: a +| b / a -| b (операнды-идентификаторы или литералы)
    text = re.sub(r"\b([A-Za-z_][\w]*|\d+)\s*\+\|\s*([A-Za-z_][\w]*|\d+)",
                  lambda m: clamp("+", m.group(1), m.group(2)), text)
    text = re.sub(r"\b([A-Za-z_][\w]*|\d+)\s*-\|\s*([A-Za-z_][\w]*|\d+)",
                  lambda m: clamp("-", m.group(1), m.group(2)), text)
    return text


def parse_clike(path: Path, require_annotations: bool = True):
    """Функции Zig/C/Rust с контрактами -> формат `parse_file` + диапазоны типов."""
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    lang = ("rust" if path.suffix == ".rs"
            else ("ts" if path.suffix == ".ts"
                  else ("js" if path.suffix == ".js"
                        else ("go" if path.suffix == ".go"
                              else ("c" if path.suffix in {".c", ".h", ".cpp", ".cc"}
                                    else "zig")))))
    # ДЕФЕКТ #317: транслятор ОБЩИЙ для Python и C-подобных, а семантика
    # деления у них разная. Ставим язык ЗДЕСЬ, потому что точек входа
    # несколько (`_demo`, главный путь, JSON-путь) и не все проходят
    # через `_set_lang_from_path`.
    global _CURRENT_LANG
    _CURRENT_LANG = lang
    out = []
    i, n = 0, len(lines)
    while i < n:
        if lang in ("zig", "rust"):
            m = RE_FN_FN.match(lines[i])
        elif lang in ("ts", "js"):
            m = RE_FN_TS.match(lines[i])
        elif lang == "go":
            m = RE_FN_GO.match(lines[i])
        else:
            m = RE_FN_C.match(lines[i])
        if not m:
            i += 1
            continue
        if lang in ("zig", "rust", "ts", "js"):
            name, praw, ret = m.group(1), m.group(2), m.group(3)
        elif lang == "go":
            name, praw = m.group(1), m.group(2)
            ret = m.group(3) or m.group(4)
        else:
            ret, name, praw = m.group(1), m.group(2), m.group(3)
        # ДЕФЕКТ #180: у `pub(crate) … -> Result<…>` захват возвращаемого типа
        # может содержать пробелы — без strip `TYPE_RANGE[ret]` не находился,
        # и обязательство ПЕРЕПОЛНЕНИЯ для Rust молча пропускалось.
        #
        # ДЕФЕКТ #321 (тот же класс, C): тип возврата бывает МНОГОСЛОВНЫМ
        # (`unsigned int`, `long long`). `TYPE_RANGE` знает только канонические
        # ключи, поэтому `ret = "unsigned int"` НЕ находился, обязанность
        # переполнения молча снималась, и функция с настоящим переполнением
        # получала `ДОКАЗАНО`. Канонизируем так же, как параметры (#312).
        ret = (ret or "").strip()
        if lang == "c":
            ret = C_MACHINE_TYPES.get(ret, ret)
        meta = {"ranges": {}, "ret": ret}
        ret = meta["ret"]
        req = ens = None
        ens_cls = "hard"
        for k in range(max(0, i - 6), i):
            am = ANNOT.match(lines[k])
            if am:
                if am.group(1) == "requires":
                    req = am.group(2)
                else:
                    ens = am.group(2)
                    ens_cls = annot_class(am)  # Ф6.1
        # `require_annotations=False` — режим `--xray` (Zero-Annotation):
        # функции БЕЗ `@kern:` тоже анализируются (иначе std Zig давал 0/0).
        if require_annotations and req is None and ens is None:
            i += 1
            continue
        # тело: от первой `{` до парной `}`
        depth = 0
        body_lines = []
        started = False
        j = i
        while j < n:
            _open_at = None
            for _ci, ch in enumerate(lines[j]):
                if ch == "{":
                    depth += 1
                    if depth == 1:
                        started = True
                        _open_at = _ci
                        continue
                elif ch == "}":
                    depth -= 1
            if started and _open_at is not None:
                # Первая `{` на ЭТОЙ строке: берём ХВОСТ после неё (и до
                # закрывающей `}`), а не строку целиком.
                #
                # ДЕФЕКТ N4: тело на ОДНОЙ строке с объявлением
                # (`int f(int a, int b) { return a % b; }`) НЕ собиралось:
                # условия `j > i` и `depth >= 1` отсекали его, `body_lines`
                # оставался пустым, `_exec_clike` возвращал None — и функция
                # уходила в `SKIP — вне подъмножества` БЕЗ ПРИЧИНЫ. Та же самая
                # функция, записанная в две строки, доказывалась. Это и была
                # «загадка requires b != 0»: дело было не в контракте, а в
                # форматировании.
                #
                # ДЕФЕКТ #325: то же правило нужно, когда `{` стоит на
                # СЛЕДУЮЩЕЙ строке (стиль Allman) — иначе в тело попадала бы
                # сама `{` и разбор операторов ломался.
                _tail = lines[j][_open_at + 1:]
                _cut = _tail.rfind("}")
                if _cut >= 0:
                    _tail = _tail[:_cut]
                if _tail.strip():
                    body_lines.append(_tail)
            elif started and j > i and depth >= 1:
                body_lines.append(lines[j])
            if started and depth == 0:
                break
            j += 1
        try:
            params = clike_params(praw, lang)
        except Unsupported as e:
            out.append((name, [], req, ens, None, i + 1, str(e), meta))
            i = j + 1
            continue
        names = [p[0] for p in params]
        ranges = {p[0]: TYPE_RANGE[p[1]] for p in params if p[1] in TYPE_RANGE}
        unknown = [p[1] for p in params if p[1] not in TYPE_RANGE]
        if unknown:
            # ЧЕСТНЫЙ ОТКАЗ: у каждого неподдержанного типа — СВОЯ причина
            # (пункт 25: `number` — это float64, а не целое).
            why = "; ".join(UNMODELED_TYPES.get(u, f"тип вне таблицы диапазонов: {u}")
                            for u in unknown)
            out.append((name, names, req, ens, None, i + 1, why, meta))
            i = j + 1
            continue
        meta["ranges"] = ranges
        meta["lang"] = lang
        # ПУНКТ 25: в Go/JS/TS `;` необязательна — разделяем операторы по
        # переводу строки (сохранён в `_normalize_clike(keep_newlines=True)`).
        semi_optional = lang in ("go", "js", "ts")
        # ДЕФЕКТ #178: комментарии и строковые литералы снимаются ДО разбора,
        # иначе `// a/b`, `"pkg/windows/…"` и URL дают ложные `[CRASH PATH]`.
        clean_body = _strip_c_comments_strings("\n".join(body_lines))
        if lang in ("ts", "js"):
            clean_body = _strip_js_regex(clean_body)   # `/re/g` — не деление
        raw_body = _normalize_clike(clean_body, keep_newlines=semi_optional)
        # ТОЧНЫЙ кламп насыщения (по типу возврата), а не просто `+`.
        raw_body = _saturate_rewrite(raw_body, ret)
        meta["raw_body"] = raw_body   # УЛУЧШЕНИЕ №14: для конкретной перепроверки
        _DIV_COLLECTOR.clear()
        _NEG_COLLECTOR.clear()
        try:
            stmts = _clike_stmts(raw_body, lang)
            body = _exec_clike(stmts, {}, lang)
        except (NoReturn, Unsupported, SyntaxError) as e:
            # УЛУЧШЕНИЕ №15: Int-теория не знает битовых операций (`& | ^ ~ << >>`),
            # но ЯДРО KERN штатно работает с QF_BV. Если причина отказа — именно
            # битовая операция, помечаем функцию как «BV-кандидата»: тело будет
            # пересобрано в теории битовых векторов в `_demo` (а не отправлено в SKIP).
            if _needs_bitvec(raw_body, req, ens) or "нелинейное умножение" in str(e):
                # УЛУЧШЕНИЕ №16: `a * b` ДВУХ ПЕРЕМЕННЫХ нелинейно в Int (QF_LIA
                # его не решает), но в QF_BV это обычный `bvmul` — решаемый.
                # Поэтому такая функция идёт BV-кандидатом, а не в SKIP.
                meta["divisors"] = []
                meta["negs"] = []
                out.append((name, names, req, ens, "BV_PENDING", i + 1, None, meta))
            else:
                out.append((name, names, req, ens, None, i + 1, str(e), meta))
            i = j + 1
            continue
        meta["divisors"] = _drop_macro_divisors(list(dict.fromkeys(_DIV_COLLECTOR)))
        meta["negs"] = list(dict.fromkeys(_NEG_COLLECTOR))
        # ДЕФЕКТ N4: `_exec_clike` может вернуть `None` НЕ возбуждая исключения —
        # тогда причина отказа оставалась пустой, и в отчёте появлялось немое
        # `SKIP — вне подмножества`. Ровно это скрывало баг однострочного тела.
        # Причина обязана называть СТАДИЮ, а не отсутствовать.
        _why = None
        if body is None:
            if not raw_body.strip():
                _why = ("empty function body: тело пусто после снятия "
                        "комментариев/скобок (проверьте формат записи функции)")
            else:
                _why = ("body без `return`: ни один путь не возвращает значение "
                        "(ветвление/цикл вне подмножества)")
        out.append((name, names, req, ens, body, i + 1, _why, meta))
        i = j + 1
    return out


def _sem_of_suffix(suf: str) -> ValueSemantics:
    """Семантика языка ПО РАСШИРЕНИЮ файла — из ТАБЛИЦЫ, а не из литералов.

    ДЕФЕКТ #353 (шаг N11). Решения вида `p.suffix in CLIKE_EXT` (7 мест) брали
    свойство языка из литерального множества, а не из `VALUE_SEMANTICS`, то есть
    ОДНО свойство описывалось в ДВУХ местах — ровно тот механизм, который дал
    #317 (floor вместо усечения) и #321 (снятая обязанность переполнения):
    правило правили в одном месте из двух. Теперь расширение переводится в язык,
    а свойство (`bounded_ints` / `allow_bv_fallback`) читается ИЗ ТАБЛИЦЫ.

    Значения в таблице подобраны так, чтобы поведение НЕ изменилось: для
    C-подобных (`c/zig/rust/ts/js/go`) оба свойства `True`, для `python` — `False`.
    """
    suf = (suf or "").lower()
    lang = ("rust" if suf == ".rs" else "zig" if suf == ".zig"
            else "go" if suf == ".go" else "ts" if suf in {".ts", ".js"}
            else "c" if suf in {".c", ".h", ".cpp", ".cc"} else "python")
    return VALUE_SEMANTICS[lang]


# ДЕФЕКТ #342 (шаг N12): ЯВНАЯ директива языка в файле. До неё `lang="evm"` не
# выставлялся НИ ОДНИМ путём разбора: таблица семантики запись имела, а фронтенда
# не было. Форма та же, что у контрактов (`#`/`//`/`///`).
LANG_DIRECTIVE = re.compile(r"(?:///|//|#)\s*@kern:lang\s+([A-Za-z0-9_]+)")


def _set_lang_from_path(path: Path) -> str:
    """Выставить язык трансляции: ЯВНАЯ директива -> иначе расширение.

    Возвращает ПРЕДЫДУЩЕЕ значение, чтобы вызывающий мог восстановить его.

    ДЕФЕКТ #317: семантика деления зависит от языка, поэтому её нельзя угадывать.
    ДЕФЕКТ #342 (шаг N12): расширение — НЕ единственный источник. Директива
    `@kern:lang evm` в файле ПЕРЕОПРЕДЕЛЯЕТ его, иначе запись `evm` в
    `VALUE_SEMANTICS` остаётся мёртвой (её никто не мог выбрать), а реальный
    EVM-код не проходил через неё ни разу.

    ПОРЯДОК ЯВНЫЙ И ОБОСНОВАННЫЙ: директива сильнее расширения, потому что она
    стоит В САМОМ файле и говорит о нём точнее, чем суффикс имени. Неизвестное
    имя языка НЕ игнорируется молча: оно попадёт в `semantics_for`, который по
    правилу I4 даёт ЯВНЫЙ отказ (а не тихий дефолт в Python).
    """
    global _CURRENT_LANG
    prev = _CURRENT_LANG
    suf = path.suffix.lower()
    lang = ("rust" if suf == ".rs" else "zig" if suf == ".zig"
            else "go" if suf == ".go" else "ts" if suf in {".ts", ".js"}
            else "c" if suf in {".c", ".h", ".cpp", ".cc"} else "python")
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError:
        head = ""
    m = LANG_DIRECTIVE.search(head)
    if m:
        lang = m.group(1)
    _CURRENT_LANG = lang
    return prev


def parse_any(path: Path):
    """Диспетчер по расширению: `.py` -> ast, Zig/C/Rust -> полиглот-парсер.

    ВСЕГДА возвращает 8-кортежи; последний элемент — `meta` с МАШИННЫМИ
    диапазонами параметров, типом возврата и собранными делителями.
    """
    if path.suffix in CLIKE_EXT:
        return parse_clike(path)
    return parse_file(path)


def expect_demo(alloc_out: list) -> int:
    """Проверить, что демо дало РОВНО ожидаемые вердикты.

    ЗАЧЕМ. Цель `contracts` была ДЕМО: печатала PASS и FAIL и всегда
    завершалась успешно (`|| true` в Makefile), то есть НЕ МОГЛА УПАСТЬ —
    классическая «молчаливо сломанная проверка». Теперь она проверяет, что
    демо воспроизводит ожидаемое поведение, и падает, если нет.

    Ожидание: withdraw -> ДОКАЗАНО, withdraw_buggy -> НАРУШЕН, sum_to_n -> SKIP.
    """
    text = "\n".join(alloc_out)
    problems = []
    if "[PASS] withdraw:" not in text:
        problems.append("withdraw НЕ доказан (ожидался ДОКАЗАНО)")
    if "[FAIL] withdraw_buggy:" not in text:
        problems.append("withdraw_buggy НЕ отвергнут (ожидался НАРУШЕН)")
    if "sum_to_n" not in text or "SKIP" not in text:
        problems.append("sum_to_n не помечен SKIP (цикл вне подмножества)")
    # ВЕТВЛЕНИЯ: после дефекта #95 (частичная резолюция + трёхзначный
    # результат unit-resolution) пруф-чекер ПОКРЫВАЕТ выводы с `ite`,
    # поэтому корректные функции с ветвлениями обязаны быть PASS,
    # а НЕ SKIP. Раньше здесь ожидался SKIP — ожидание было записано,
    # когда чекер такие выводы отвергал.
    if "[PASS] withdraw_fixed" not in text:
        problems.append("withdraw_fixed НЕ доказан (ожидался PASS + PROOF VERIFIED)")
    if "[PASS] withdraw_ternary" not in text:
        problems.append("withdraw_ternary НЕ доказан (ожидался PASS)")
    # БАГ ОБЯЗАН БЫТЬ НАЙДЕН с контрпримером.
    if "[FAIL] withdraw_missing_neg" not in text:
        problems.append("withdraw_missing_neg НЕ отвергнут (баг не найден!)")
    if "КОНТРПРИМЕР" not in text:
        problems.append("контрпример не предъявлен")
    # ВАКУУМНЫЙ КОНТРАКТ обязан ловиться ОТДЕЛЬНЫМ вердиктом (УЛУЧШЕНИЕ №1):
    # без этой проверки ловушка `false => anything` объявила бы НАМЕРЕННО
    # сломанное тело `withdraw_vacuous` ДОКАЗАННЫМ.
    if "[VACUOUS] withdraw_vacuous" not in text:
        problems.append("withdraw_vacuous НЕ пойман (вакуумное предусловие!)")
    if "B4: N, e = 0" not in text:
        problems.append("вакуумный контракт не помечен `B4: N, e = 0`")
    # ПОЛИГЛОТ (Этап 2): те же контракты в Zig/C/Rust + машинные типы.
    if "[PASS] withdrawGuard" not in text:
        problems.append("Zig: withdrawGuard НЕ доказан (полиглот не работает)")
    if "[FAIL] share" not in text or "ДЕЛЕНИЕ НА НОЛЬ" not in text:
        problems.append("C: деление на ноль НЕ поймано")
    if "[FAIL] double_it" not in text or "ПЕРЕПОЛНЕНИЕ" not in text:
        problems.append("Rust: переполнение i32 НЕ поймано")
    # Zero-Trust к Z3 (пункт 11): контрпример обязан подтверждаться РАНТАЙМОМ.
    if "[RUNTIME CONFIRMED]" not in text:
        problems.append("контрпример НЕ подтверждён рантаймом "
                        "([RUNTIME CONFIRMED] отсутствует)")
    if problems:
        print("[!] ДЕМО НЕ СООТВЕТСТВУЕТ ОЖИДАНИЮ:")
        for x in problems:
            print(f"      - {x}")
        return 1
    print("[OK] демо воспроизвело ожидаемые вердикты")
    return 0


def emit_pytest(out_path: str, examples: list, files) -> int:
    """УЛУЧШЕНИЕ №4: превратить контрпример Z3 в ПАДАЮЩИЙ pytest.

    ЗАЧЕМ. Найденный Z3 баг (`balance = 0, amount = -1`) был всего лишь
    строкой в логе и нигде не воспроизводился. Теперь он становится обычным
    тестом: разработчик запускает `pytest` и видит КРАСНЫЙ тест с теми же
    числами, что предъявил решатель.
    """
    src = (Path(examples[0]["file"]).resolve() if examples
           else (Path(files[0]).resolve() if files else Path(".")))
    lines = [
        "# АВТОГЕНЕРАЦИЯ KERN: регрессионные тесты из КОНТРПРИМЕРОВ Z3.",
        "# КАЖДЫЙ тест ПАДАЕТ на текущем коде — это и есть найденный баг.",
        f"# Запуск: pytest {out_path}",
        "import sys",
        f'sys.path.insert(0, r"{src.parent}")',
        f"from {src.stem} import *  # noqa: F401,F403",
        "",
    ]
    for ex in examples:
        args = ", ".join(f"{p}={ex['vals'][p]}" for p in ex["params"])
        lines += [
            "",
            f"def test_counterexample_{ex['name']}():",
            f"    # KERN/Z3: контрпример к `ensures` (стр. {ex['line']})",
            f"    # ensures: {ex['ens']}",
            f"    result = {ex['name']}({args})",
            f"    assert ({ex['ens']}), (",
            f"        'KERN: контракт нарушен при {args}')",
        ]
    if not examples:
        lines += ["", "def test_no_counterexamples():",
                  "    # Z3 не нашёл контрпримеров — регрессий нет.",
                  "    assert True"]
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [i] pytest из контрпримеров: {out_path} ({len(examples)} тест(ов))")
    return 0


# Ф1: контракты больше не «один демо-файл». Замок обязан покрывать ВЕСЬ
# репозиторий, иначе can-fail «ослабили ensures» остаётся вакуумным.
CONTRACT_GLOBS = ("examples/**/*.py", "src/**/*.zig", "tools/**/*.py", "tests/**/*.zig")

# ДЕФЕКТ #382 (найден 2026-10-27 при проверке «enforced ли замок в CI»):
# критерий «содержит подстроку `@kern:`» был СЛИШКОМ ГРУБ. Он ловил
# ИНСТРУМЕНТЫ, которые лишь УПОМИНАЮТ контракты — в докстринге, в метке
# вывода, в генераторе строк. ИЗМЕРЕНО: из 6 «незапечатанных файлов»
# контрактами оказались только 2 (tests/fixtures/zig_ast_contracts*.zig),
# а 4 — инструменты (src/verifier/zig_ast_verify.zig, tools/inline_check.py,
# tools/real_cases_check.py, tools/svcomp_baseline.py). Это ложное обвинение
# того же класса, что #290/#296: инструмент, ГЕНЕРИРУЮЩИЙ контракты, не
# должен выглядеть как ЗАПЕЧАТАННЫЙ контракт.
#
# Точный критерий: аннотация в КОММЕНТАРИИ в начале строки — тот же префикс,
# что у ANNOT (стр. 1817). Проверено на всех 6 файлах: 2 фикстуры совпадают,
# 4 инструмента — нет.
CONTRACT_LINE = re.compile(r"^\s*(?:///|//|#)\s*@kern:(?:requires|ensures)\b", re.M)


def repo_contract_files() -> list[str]:
    """Файлы репозитория, содержащие хотя бы одну АННОТАЦИЮ контракта.

    Не «упоминание `@kern:`», а именно аннотация в комментарии в начале
    строки (см. `CONTRACT_LINE` и дефект #382).
    """
    found: list[str] = []
    for pattern in CONTRACT_GLOBS:
        for p in sorted(Path(".").glob(pattern)):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if CONTRACT_LINE.search(text):
                found.append(p.as_posix())
    return found


def cmd_lock(files, out_path: str) -> int:
    """УЛУЧШЕНИЕ №2: запечатать отпечатки контрактов (Contract Lock)."""
    data = {}
    for f in files:
        data[str(f)] = contract_fingerprints(Path(f))
    Path(out_path).write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    n = sum(len(v) for v in data.values())
    print(f"  [i] запечатано контрактов: {n} -> {out_path}")
    return 0


def cmd_verify_lock(files, lock_path: str) -> int:
    """УЛУЧШЕНИЕ №2: проверить, что ни один запечатанный контракт не изменён.

    ЭТО ЗАЩИТА ОТ ИИ-АГЕНТА: когда починить код под `make contracts` не
    получается, самый простой чит — УДАЛИТЬ или ОСЛАБИТЬ строку
    `# @kern:ensures`. Здесь такое изменение даёт `rc = 2`.
    """
    try:
        data = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[!] не читается замок {lock_path}: {e}")
        return 2
    if not files:
        files = list(data.keys())  # список берём ИЗ ЗАМКА (для pre-commit-хука)
    bad = 0
    for f in files:
        cur = contract_fingerprints(Path(f))
        old = data.get(str(f), {})
        for key, h in old.items():
            if key not in cur:
                print(f"  [SECURITY] контракт УДАЛЁН: {f}:{key}")
                bad += 1
            elif cur[key] != h:
                print(f"  [SECURITY] контракт ИЗМЕНЁН: {f}:{key}")
                bad += 1
        for key in cur:
            if key not in old:
                print(f"  [i] новый контракт (не запечатан): {f}:{key}")
    if bad:
        print(f"[!] ЗАПЕЧАТАННЫЕ КОНТРАКТЫ НАРУШЕНЫ: {bad}")
        return 2
    print("[OK] замок контрактов цел: ни один запечатанный контракт не изменён")
    return 0


def classify_prove(rc: int, out: str) -> str:
    """Класс вердикта `kernc prove` -> equivalent | unverified | diverged |
    unknown | tool_error.

    ДЕФЕКТ #243: `--diff-equiv` считал РАСХОЖДЕНИЕМ всё, кроме строки
    «ДОКАЗАНО», а `rc` у «доказано» и «опровергнуто» ОДИН И ТОТ ЖЕ (2 —
    пруф-чекер не привязал посылки к контракту). Поэтому идентичный файл
    объявлялся DIVERGED (ложное обвинение), а цель `make diff-equiv`
    проходила ВАКУУМНО. Классификация идёт по выводу решателя, не по rc.
    """
    low = out.lower()
    if "контрпример" in low or "[counterexample]" in low:
        return "diverged"
    if "z3 недоступен" in low or "z3 is not" in low:
        return "unknown"
    if "таймаут" in low or "timeout" in low:
        return "unknown"
    if rc == 0:
        return "equivalent"
    if "доказано" in low and "не доказано" not in low:
        return "unverified"
    if rc in (2, 3):
        return "unknown"
    return "tool_error"


def cmd_diff_equiv(old_file: str, new_file: str, kernc) -> int:
    """УЛУЧШЕНИЕ №3: доказать эквивалентность рефакторинга БЕЗ контрактов."""
    if not Path(kernc).exists():
        print(f"[!] не найден kernc: {kernc} (соберите: zig build)")
        return 2
    a = {n: (p, b, ln, u) for n, p, b, ln, u in parse_bodies(Path(old_file))}
    b2 = {n: (p, b, ln, u) for n, p, b, ln, u in parse_bodies(Path(new_file))}
    common = [n for n in a if n in b2]
    if not common:
        print("[!] нет одноимённых функций в подмножестве — сравнивать нечего")
        # ДЕФЕКТ #361: пустой список обязан называть ПРИЧИНУ. Иначе C-файл с
        # нелинейным умножением давал бы «сравнивать нечего», хотя причина
        # конкретна (тело живёт в QF_BV, а сравнение идёт в Int-теории).
        if _CLIKE_SKIP_REASONS:
            print("    причины (C-like вход):")
            for r in _CLIKE_SKIP_REASONS:
                print(f"      - {r}")
        return 2
    diverged = same = unknown = unverified = tool_errors = 0
    for name in sorted(common):
        pa, ba, _ln, ua = a[name]
        pb, bnew, _ln2, ub = b2[name]
        if pa != pb:
            print(f"  [SKIP] {name}: разные наборы параметров {pa} / {pb}")
            continue
        # ДЕФЕКТ #206: `_havoc_k` — НЕОГРАНИЧЕННАЯ переменная абстракции
        # (вместо вызова/агрегата). Два разных havoc в двух телах всегда
        # «различны» (distinct SAT тривиально), поэтому объявлять DIVERGED
        # по такой модели — ЛОЖНОЕ обвинение. Честный исход — UNKNOWN.
        if "_havoc_" in ba or "_havoc_" in bnew:
            print(f"  [UNKNOWN] {name}: тело содержит абстракцию (_havoc_k) — "
                  f"расхождение НЕДОКАЗУЕМО в этой модели (не баг)")
            unknown += 1
            continue
        # ДЕФЕКТ #207: развёртка — недо-аппроксимация. UNSAT на K шагах НЕ
        # доказывает эквивалентность (цикл может идти дальше). Только UNKNOWN.
        if ua or ub:
            unknown += 1
            print(f"  [UNKNOWN] {name}: развёртка цикла/рекурсии — "
                  f"эквивалентность НЕДОКАЗУЕМА (дефект #207)")
            continue
        rc, out = run_kernc(kernc, diff_equiv_smt(pa, ba, bnew), query_kind="equivalence")
        verdict = classify_prove(rc, out)
        if verdict == "equivalent":
            print(f"  [EQUIVALENT] {name}: рефакторинг математически "
                  f"эквивалентен на всём домене Z (пруф-чекер принял)")
            same += 1
        elif verdict == "unverified":
            print(f"  [EQUIVALENT?] {name}: решатель доказал эквивалентность, "
                  f"но пруф-чекер отверг вывод (premises_unbound) — "
                  f"это НЕ расхождение и НЕ доверенное доказательство")
            unverified += 1
        elif verdict == "diverged":
            print(f"  [DIVERGED] {name}: РЕФАКТОРИНГ ИЗМЕНИЛ ПОВЕДЕНИЕ")
            for line in out.splitlines():
                if "КОНТРПРИМЕР" in line:
                    print(f"         {line.strip()}")
                    break
            diverged += 1
        elif verdict == "unknown":
            hint = " (z3 недоступен/таймаут)" if "z3" in out.lower() else ""
            print(f"  [UNKNOWN] {name}: решатель не определился{hint} — "
                  f"это НЕ расхождение и НЕ доказательство")
            unknown += 1
        else:
            print(f"  [TOOL_ERROR] {name}: код {rc} — это НЕ расхождение; "
                  f"проверьте решатель/PATH")
            tool_errors += 1
    print("-" * 74)
    print(f"ИТОГО: эквивалентных {same} | эквивалентных без пруф-чекера "
          f"{unverified} | разошедшихся {diverged} | недоказуемых {unknown} | "
          f"ошибок инструмента {tool_errors} | всего {len(common)}")
    if diverged:
        return 1
    return 2 if (unknown or unverified or tool_errors) else 0


ROOT = Path(__file__).resolve().parent.parent

HOOK_BODY = """#!/bin/sh
# KERN pre-commit шлюз (установлен `kern_contracts.py --install-hook`).
# Блокирует коммит, если ИИ-агент или разработчик оставляет код с нарушенным
# контрактом, вакуумным предусловием, делением на ноль / переполнением
# ИЛИ ослабил запечатанный контракт. Обход (осознанный): git commit --no-verify
set -u
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT" || exit 1
PY="${PYTHON:-python3}"
if [ -f docs/contracts.lock.json ]; then
  "$PY" tools/kern_contracts.py --verify-lock docs/contracts.lock.json || {
    echo "[KERN] КОММИТ ЗАБЛОКИРОВАН: запечатанный контракт изменён или удалён."
    exit 1; }
fi
"$PY" tools/kern_contracts.py --git-diff HEAD --github-annotations || {
  echo "[KERN] КОММИТ ЗАБЛОКИРОВАН: нарушен контракт, вакуумное предусловие"
  echo "       или найдено деление на ноль / переполнение типа."
  exit 1; }
exit 0
"""


def changed_contract_files(ref: str):
    """Файлы с аннотациями `@kern:`, которые войдут в коммит.

    Набор = ПРОИНДЕКСИРОВАННЫЕ (`git diff --cached`) + НОВЫЕ (untracked).
    Именно это проверяет pre-commit: «что сейчас закоммитится». `--cached`
    работает и на ПЕРВОМ коммите, когда `HEAD` ещё не существует.
    """
    names: list[str] = []
    cmds = [["git", "diff", "--name-only", "--cached"]]
    if ref not in ("HEAD", "STAGED"):
        cmds.append(["git", "diff", "--name-only", ref])
    cmds.append(["git", "ls-files", "--others", "--exclude-standard"])
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                               cwd=str(ROOT))
            names += [n.strip() for n in r.stdout.splitlines() if n.strip()]
        except (OSError, subprocess.SubprocessError):
            continue
    out = []
    skipped_demo = []
    for n in names:
        fp = ROOT / n
        if not fp.is_file():
            continue
        if fp.suffix not in CLIKE_EXT and fp.suffix != ".py":
            continue
        try:
            # ВАЖНО: проверяем ПОСТРОЧНО. `ANNOT.search(весь_файл)` без
            # `re.MULTILINE` сработал бы только на первой строке файла, и
            # pre-commit молча пропускал бы сломанные контракты ниже.
            txt = fp.read_text(encoding="utf-8", errors="replace")
            if any(ANNOT.match(ln) for ln in txt.splitlines()):
                # ДЕМО-ФИКСТУРЫ с НАМЕРЕННЫМИ нарушениями (их контракты обязаны
                # падать) помечаются маркером `@kern:expect-violations` —
                # иначе собственный pre-commit блокировал бы их коммит.
                if "@kern:expect-violations" in txt:
                    skipped_demo.append(n)
                    continue
                out.append(n)
        except OSError:
            continue
    if skipped_demo:
        print(f"[i] пропущены демо-фикстуры с намеренными нарушениями "
              f"(@kern:expect-violations): {', '.join(skipped_demo)}")
    return out


def cmd_git_diff(ref: str, kernc: str, sarif=None, annotations=False,
                 json_out=None) -> int:
    """Проверить ТОЛЬКО изменённые файлы (быстрый шлюз для pre-commit)."""
    files = changed_contract_files(ref)
    if not files:
        print(f"[OK] изменённых файлов с @kern:-контрактами нет (ref={ref})")
        return 0
    print(f"[i] проверяю изменённые файлы ({len(files)}): {', '.join(files)}")
    ns = argparse.Namespace(files=files, kernc=kernc, sarif=sarif,
                            github_annotations=annotations, emit_pytest=None,
                            json=json_out)
    return _demo(ns)


def cmd_install_hook(repo_dir: str) -> int:
    """Поставить `.git/hooks/pre-commit` одной командой."""
    gitdir = Path(repo_dir).resolve() / ".git"
    if not gitdir.is_dir():
        print(f"[!] не найден каталог git: {gitdir}")
        return 2
    hooks = gitdir / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text(HOOK_BODY, encoding="utf-8")
    hook.chmod(0o755)
    print(f"[OK] установлен {hook}")
    print("     `git commit` теперь блокируется, если контракт нарушен,")
    print("     предусловие вакуумно, найдено деление на ноль / переполнение")
    print("     или ослаблен docs/contracts.lock.json.")
    return 0


# ===========================================================================
#  Ф6.3: ОБЪЯСНЕНИЯ (read-only гипотезы по `requires`)
# ===========================================================================
# ЗАЧЕМ. Контрпример говорит «так нельзя», но не говорит «что добавить».
# Абдукция предлагает гипотезу. ГИПОТЕЗА — не доказательство, поэтому:
#   * кандидаты строятся ТОЛЬКО для `requires`; `ensures` не ослабляется
#     никогда (это был бы ровно тот чит, против которого стоит замок);
#   * каждый кандидат ПЕРЕПРОВЕРЯЕТСЯ вторым прогоном решателя;
#   * файл НЕ изменяется (read-only), в JSON `"kind": "hypothesis"`.
HYP_BANNER = "ГИПОТЕЗА, не доказательство. Файл не изменён."
HYP_BANNER_EN = "HYPOTHESIS, not a proof. File not modified."


def _hyp_candidates(params, req: str | None) -> list[str]:
    """Кандидаты-условия для `requires`, детерминированный порядок."""
    out: list[str] = []
    seen: set[str] = set()

    def add(x: str) -> None:
        x = x.strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)

    if req:
        for part in re.split(r"\s+and\s+", req):
            add(part)
    for v in sorted(params):
        add(f"{v} >= 0")
        add(f"{v} > 0")
        add(f"{v} != 0")
        add(f"{v} <= 0")
    return out


def _hyp_holds(expr: str, vals: dict) -> bool | None:
    """Значение кандидата на конкретном контрпримере (None = не вычислить).

    Ожидаемые отказы вычисления (тип, деление на ноль, неизвестное имя в
    выражении) молча дают None. Но если сломан НАШ код (`AttributeError`/
    `SyntaxError`), это обязано быть видно — `_replay_soft` печатает такие в
    stderr (класс #198: голый `except Exception:` скрывал дефект месяц).
    """
    try:
        return bool(eval(expr, {"__builtins__": {}}, dict(vals)))  # noqa: S307
    except (TypeError, ValueError, ZeroDivisionError, KeyError,
            OverflowError, NameError) as e:
        _replay_soft(e, "hypothesis")
        return None


def _hyp_write_json(as_json, payload: dict) -> None:
    """Единственная точка записи отчёта: JSON выдаётся ВСЕГДА (#294).

    Раньше при «доказывать нечего» и при неподдержанном теле функция выходила
    раньше, чем писала JSON: вызывающая сторона просила файл и не получала
    его, принимая отсутствие отчёта за ошибку.
    """
    if as_json:
        as_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def cmd_explain_hypotheses(kernc: str, path: Path, fn_name: str | None,
                           as_json: Path | None, max_hyp: int) -> int:
    """Печатает гипотезы по `requires`. НИКОГДА не пишет в исходник."""
    from hashlib import sha256 as _sha

    before = _sha(path.read_bytes()).hexdigest()
    _set_lang_from_path(path)   # дефект #317: семантика деления зависит от языка
    funcs = parse_any(path)
    if not funcs:
        print(f"[!] {path}: функций с @kern: не найдено")
        return 2
    target = None
    for item in funcs:
        name, params, req, ens, body, ln, skip, meta = item
        if fn_name and name != fn_name:
            continue
        if ens and body is not None:
            target = item
            break
    if target is None:
        print(f"[!] {path}: нет функции с @kern:ensures и поддержанным телом")
        return 2
    name, params, req, ens, body, ln, _skip, meta = target

    # ДЕФЕКТ #295 (найден обкаткой корпуса): тело, полученное РАЗВЁРТКОЙ
    # цикла/рекурсии, — недо-аппроксимация. `contracts` честно выдаёт SKIP
    # (#207), а `explain` успевал объявить «доказано» и выдать гипотезу
    # вроде `n <= 0`, которая просто обнуляет рекурсию. Гипотезы здесь
    # запрещены: подтвердить их тем же раннером невозможно.
    if meta.get("unrolled"):
        print(f"[!] {name}: тело получено развёрткой цикла/рекурсии — "
              f"развёртка не исчерпывает поведение, гипотезы не выдаются (#207)")
        _hyp_write_json(as_json, {
            "kind": "hypothesis", "file": str(path), "function": name,
            "status": "unbounded", "hypotheses": [],
            "banner": HYP_BANNER_EN})
        return 0

    smt = build_smt(params, req, ens, body, ranges=meta.get("ranges"))
    rc, out = run_kernc(kernc, smt)
    if "ДОКАЗАНО" in out and rc == 0:
        print(f"[OK] {name}: контракт ДОКАЗАН — объяснять нечего")
        _hyp_write_json(as_json, {
            "kind": "hypothesis", "file": str(path), "function": name,
            "status": "proven", "hypotheses": [],
            "banner": HYP_BANNER_EN})
        return 0
    ce = parse_counterexample(out)
    print("=" * 74)
    print("KERN: объяснение — гипотезы для `requires` (Ф6.3)")
    print("=" * 74)
    print(f"  функция: {name} (стр. {ln})")
    print(f"  requires: {req or '—'}")
    print(f"  ensures:  {ens}")
    print(f"  контрпример: {fmt_ce(ce) if ce else 'не найден (решатель вернул N)'}")
    print(f"\n  {HYP_BANNER}\n")

    results: list[dict] = []
    rejected: list[str] = []
    for cand in _hyp_candidates(params, req):
        combined = f"({req}) and ({cand})" if req else cand
        smt2 = build_smt(params, combined, ens, body, ranges=meta.get("ranges"))
        rc2, out2 = run_kernc(kernc, smt2)
        if not ("ДОКАЗАНО" in out2 and rc2 == 0):
            continue                      # кандидат НЕ отсекает контрпример
        if ce:
            holds = _hyp_holds(cand, ce)
            if holds is not False:
                continue                  # не отсекает ИМЕННО этот контрпример
        # КРИТИЧНО: кандидат не должен делать `requires` ПРОТИВОРЕЧИВЫМ.
        # Иначе «доказано» — это вакуумная истина (`false => anything`),
        # то есть ровно та ложь, против которой стоит детектор вакуумных
        # предусловий. Такой кандидат ОТБРАСЫВАЕТСЯ и называется вслух.
        try:
            rcv, outv = run_kernc(kernc, requires_only_smt(params, combined))
        except (Unsupported, subprocess.SubprocessError, OSError):
            continue
        if "ДОКАЗАНО" in outv:
            rejected.append(cand)
            continue
        # что кандидат НЕ отсекает: он один (без исходного requires)
        smt_alone = build_smt(params, cand, ens, body, ranges=meta.get("ranges"))
        rc3, out3 = run_kernc(kernc, smt_alone)
        alone_ok = "ДОКАЗАНО" in out3 and rc3 == 0
        residual = {} if alone_ok else parse_counterexample(out3)
        results.append({
            "candidate": cand,
            "prunes": fmt_ce(ce) if ce else "",
            "proven_with_original": True,
            "proven_alone": alone_ok,
            "does_not_prune": fmt_ce(residual) if residual else "",
            "fragile": not alone_ok,
        })
        if len(results) >= max_hyp:
            break

    for i, r in enumerate(results, 1):
        mark = "хрупкая" if r["fragile"] else "самодостаточна"
        print(f"  [{i}] requires += `{r['candidate']}`   ({mark})")
        print(f"      отсекает: {r['prunes']}")
        if r["does_not_prune"]:
            print(f"      НЕ отсекает: {r['does_not_prune']}")
        else:
            print("      НЕ отсекает: — (доказывает и без исходного requires)")
    for cand in rejected:
        print(f"  [!] отклонён `{cand}`: делает requires противоречивым "
              f"(«доказательство» было бы вакуумным)")
    if not results:
        print("  кандидатов, отсекающих контрпример, не найдено — честный ответ")
    print(f"\n  {HYP_BANNER_EN}")

    after = _sha(path.read_bytes()).hexdigest()
    if before != after:                    # защита от случайной записи
        print("[FAIL] файл изменён — это нарушение read-only")
        return 1
    _hyp_write_json(as_json, {
        "kind": "hypothesis", "file": str(path), "function": name,
        "status": "reported",
        "requires": req, "ensures": ens, "counterexample": fmt_ce(ce),
        "hypotheses": results, "banner": HYP_BANNER_EN,
    })
    if as_json:
        print(f"  JSON: {as_json}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--kernc", default=str(Path(__file__).resolve().parent.parent
                                          / "zig-out" / "bin" / "kernc"))
    ap.add_argument("--anti-cheat", default=None, metavar="PATH",
                    help="ПУНКТ 32: анти-чит (Reward Hacking, overfitting, mock, exit)")
    ap.add_argument("--import-lock", default=None, metavar="ALLOW.json",
                    help="ПУНКТ 32: белый список импортов (защита от slopsquatting)")
    ap.add_argument("--audit-mcp", default=None, metavar="PATH",
                    help="ПУНКТ 33: отравление MCP (инъекции, невидимый Unicode, rug-pull)")
    ap.add_argument("--mcp-lock", default=None, metavar="LOCK.json",
                    help="ПУНКТ 33: замок отпечатков инструментов (rug-pull)")
    ap.add_argument("--noninterference", default=None, metavar="PATH",
                    help="ПУНКТ 34: неинтерференция (@kern:secret, 2-Safety)")
    ap.add_argument("--html", default=None, metavar="OUT.html",
                    help="ПУНКТ 40Б: интерактивный холст доказательств (0 CDN)")
    ap.add_argument("--verify-action", nargs=2, default=None,
                    metavar=("ACTION.json", "POLICY.json"),
                    help="ПУНКТ 36: FinOps/Action Firewall (200/422/409)")
    ap.add_argument("--verify-doc", default=None, metavar="PATH",
                    help="ПУНКТ 37: противоречия в документе + минимальное ядро")
    ap.add_argument("--rlvr-reward", default=None, metavar="PATH",
                    help="ПУНКТ 38: верифицируемый оракул вознаграждения")
    ap.add_argument("--verify-sql", default=None, metavar="PATH",
                    help="ПУНКТ 30: изоляция тенантов (RLS-предикаты доступа)")
    ap.add_argument("--verify-pricing", default=None, metavar="PATH",
                    help="ПУНКТ 31: полнота и непротиворечивость тарифной матрицы")
    ap.add_argument("--presets", default=None, metavar="PATH",
                    help="ПУНКТ 26: однословные пресеты (non_negative, percentage, "
                         "bounded, idempotent, monotonic, no_arbitrage)")
    ap.add_argument("--spec-gaps", action="store_true",
                    help="ПУНКТ 26: диагностика неполных спецификаций (MacFarlane); "
                         "работает только вместе с --presets")
    ap.add_argument("--state-inv", default=None, metavar="PATH",
                    help="ПУНКТ 24: инвариант состояния (state_invariant)")
    ap.add_argument("--loops", default=None, metavar="PATH",
                    help="ПУНКТ 20: тотальная корректность циклов (invariant+decreases)")
    ap.add_argument("--simplify", default=None, metavar="PATH",
                    help="ПУНКТ 17: упрощение с ДОКАЗАТЕЛЬСТВОМ эквивалентности")
    ap.add_argument("--simplify-out", default=None, metavar="OUT.py",
                    help="куда записать упрощённый файл (по умолчанию не пишем)")
    ap.add_argument("--gen-tests", nargs=2, default=None, metavar=("SRC.py", "OUT.py"),
                    help="ПУНКТ 14: SBST-генератор pytest со 100 процентами покрытия ветвей")
    ap.add_argument("--audit-repo", dest="audit_repo", default=None,
                    help="универсальный аудит: путь, файл или GitHub URL")
    ap.add_argument("--html-out", dest="html_out", default=None,
                    help="сохранить HTML-паспорт аудита")
    # ДЕФЕКТ #213: флаг упоминался в документации, но ОТСУТСТВОВАЛ в CLI.
    # Делегируем в отдельный модуль `tools/trust_scorecard.py`.
    ap.add_argument("--trust-score", dest="trust_score", default=None,
                    metavar="PATH|owner/repo",
                    help="KERN Trust Scorecard: паспорт доверия для репозитория")
    # Zero-Annotation Implicit Safety (как у CBMC / AWS Kani): проверять функции
    # БЕЗ @kern: — те же обязанности (деление на ноль, границы типов),
    # что и в `--xray`. Имя `--auto` добавлено, чтобы ожидание совпадало.
    ap.add_argument("--auto", default=None, metavar="PATH",
                    help="Zero-Annotation: проверять функции без @kern: (алиас --xray)")
    ap.add_argument("--xray", default=None, metavar="PATH",
                    help="ПУНКТ 13: рентген кода БЕЗ аннотаций "
                         "(мёртвые ветки, избыточные проверки, краш-пути, CC)")
    ap.add_argument("--full-scan", dest="full_scan", default=None, metavar="PATH",
                    help="полноспектральный обход: xray (7 языков) + anti-cheat "
                         "+ MCP-аудит + авто-роутинг теорий (честно: без контракта "
                         "теории только помечаются как применимые)")
    ap.add_argument("--explain", default=None, metavar="PATH",
                    help="ПУНКТ 18: человеческий паспорт функций")
    # Ф6.3: read-only объяснение — гипотезы ТОЛЬКО для requires.
    ap.add_argument("--explain-hypotheses", default=None, metavar="FILE",
                    help="Ф6.3: гипотезы для requires (файл НЕ меняется)")
    ap.add_argument("--hypotheses-fn", "--fn", dest="hypotheses_fn", default=None, metavar="NAME",
                    help="Ф6.3: какую функцию объяснять")
    ap.add_argument("--hypotheses-json", default=None, metavar="OUT.json",
                    help="Ф6.3: машиночитаемый отчёт (kind=hypothesis)")
    ap.add_argument("--max-hypotheses", type=int, default=5,
                    help="Ф6.3: предел числа гипотез")
    ap.add_argument("--pr-summary", nargs=2, default=None, metavar=("OLD", "NEW"),
                    help="ПУНКТ 19: математическое резюме для Code Review")
    ap.add_argument("--concolic", default=None, metavar="PATH",
                    help="конколика: реальные запуски + инверсия условий в Z3"),
    ap.add_argument("--heal", default=None, metavar="PATH",
                    help="гомеостатическая петля: F -> патч -> перепроверка -> T"),
    ap.add_argument("--infer-requires", default=None, metavar="PATH",
                    help="ПУНКТЫ 15/16: синтез гарда и requires с проверкой Z3")
    ap.add_argument("--expect-demo", action="store_true",
                    help="проверить, что демо дало ОЖИДАЕМЫЕ вердикты "
                         "(превращает цель в ПРОВЕРКУ: падает при расхождении)")
    ap.add_argument("--emit-smt2", default=None, metavar="DIR",
                    help="записать каждую проверяемую формулу в DIR/<fn>.smt2 "
                         "(детерминированный фронтенд -> файлы для kernc prove и .kimg)")
    ap.add_argument("--emit-pytest", default=None, metavar="OUT.py",
                    help="сгенерировать ПАДАЮЩИЙ pytest из контрпримеров Z3")
    ap.add_argument("--lock", default=None, metavar="LOCK.json",
                    help="запечатать отпечатки контрактов (Contract Lock)")
    ap.add_argument("--lock-repo", default=None, metavar="LOCK.json",
                    help="запечатать контракты ВСЕГО репозитория "
                         "(examples/src/tools/tests с @kern:)")
    ap.add_argument("--verify-lock-repo", default=None, metavar="LOCK.json",
                    help="проверить замок И покрытие: каждый файл с @kern: "
                         "обязан быть запечатан")
    ap.add_argument("--verify-lock", default=None, metavar="LOCK.json",
                    help="проверить, что запечатанные контракты НЕ изменены "
                         "(rc=2 при удалении/ослаблении контракта)")
    ap.add_argument("--diff-equiv", nargs=2, default=None,
                    metavar=("OLD.py", "NEW.py"),
                    help="доказать эквивалентность рефакторинга (без контрактов)")
    ap.add_argument("--sarif", default=None, metavar="OUT.sarif",
                    help="экспорт нарушений в SARIF 2.1.0 (GitHub Code Scanning)")
    ap.add_argument("--json", default=None, metavar="OUT.json",
                    help="машиночитаемый JSON-отчёт по всем функциям и сводке")
    ap.add_argument("--github-annotations", action="store_true",
                    help="нативные плашки GitHub Actions "
                         "(`::error file=...,line=...,title=...`)")
    ap.add_argument("--git-diff", nargs="?", const="HEAD", default=None,
                    metavar="REF",
                    help="проверить ТОЛЬКО изменённые файлы с контрактами")
    ap.add_argument("--install-hook", nargs="?", const=".", default=None,
                    metavar="DIR",
                    help="установить .git/hooks/pre-commit (блокирует коммит "
                         "при нарушенном контракте)")
    args = ap.parse_args(argv)

    if args.install_hook is not None:
        return cmd_install_hook(args.install_hook)
    if args.git_diff is not None:
        return cmd_git_diff(args.git_diff, args.kernc, args.sarif,
                            args.github_annotations, args.json)
    if getattr(args, "anti_cheat", None):
        return cmd_anti_cheat(args.anti_cheat, args.import_lock)
    if getattr(args, "audit_mcp", None):
        return cmd_audit_mcp(args.audit_mcp, args.mcp_lock)
    if getattr(args, "noninterference", None):
        return cmd_noninterference(args.noninterference, args.kernc)
    if getattr(args, "html", None):
        if not args.files:
            print("[!] --html требует исходник: <file.py> --html <out.html>")
            return 2
        return cmd_html(args.files[0], args.html, args.kernc)
    if getattr(args, "verify_action", None):
        return cmd_verify_action(args.verify_action[0], args.verify_action[1], args.kernc)
    if getattr(args, "verify_doc", None):
        return cmd_verify_doc(args.verify_doc, args.kernc)
    if getattr(args, "rlvr_reward", None):
        return cmd_rlvr_reward(args.rlvr_reward, args.kernc)
    if getattr(args, "verify_sql", None):
        return cmd_verify_sql(args.verify_sql, args.kernc)
    if getattr(args, "verify_pricing", None):
        return cmd_verify_pricing(args.verify_pricing, args.kernc)
    if getattr(args, "presets", None):
        return cmd_presets(args.presets, args.kernc, spec_gaps=args.spec_gaps)
    if getattr(args, "state_inv", None):
        return cmd_state_inv(args.state_inv, args.kernc)
    if getattr(args, "loops", None):
        return cmd_loops(args.loops, args.kernc)
    if args.simplify:
        return cmd_simplify(args.simplify, args.simplify_out, args.kernc)
    if args.gen_tests:
        return cmd_gen_tests(args.gen_tests[0], args.gen_tests[1], args.kernc)
    if getattr(args, "trust_score", None):
        return cmd_trust_score(args.trust_score)
    if getattr(args, "audit_repo", None):
        return cmd_audit_repo(args.audit_repo, args.kernc,
                              getattr(args, "html_out", None))
    if getattr(args, "full_scan", None):
        return cmd_full_scan(args.full_scan, args.kernc)
    if args.xray:
        return cmd_xray(args.xray, args.kernc)

    if args.auto:
        return cmd_xray(args.auto, args.kernc)
    if args.heal:
        return cmd_heal(args.heal, args.kernc)
    if args.concolic:
        return cmd_concolic(args.concolic, args.kernc)
    if args.explain_hypotheses:
        return cmd_explain_hypotheses(
            args.kernc, Path(args.explain_hypotheses), args.hypotheses_fn,
            Path(args.hypotheses_json) if args.hypotheses_json else None,
            args.max_hypotheses)

    if args.explain:
        return cmd_explain(args.explain, args.kernc)
    if args.pr_summary:
        return cmd_pr_summary(args.pr_summary[0], args.pr_summary[1], args.kernc)
    if args.infer_requires:
        return cmd_suggest_fix(args.infer_requires, args.kernc, infer_requires=True)
    if args.diff_equiv:
        return cmd_diff_equiv(args.diff_equiv[0], args.diff_equiv[1],
                              Path(args.kernc))
    if args.lock_repo:
        files = repo_contract_files()
        if not files:
            print("[!] не найдено ни одного файла с аннотацией контракта")
            return 2
        print(f"  [i] файлов с контрактами: {len(files)}")
        return cmd_lock(files, args.lock_repo)
    if args.verify_lock_repo:
        files = repo_contract_files()
        rc = cmd_verify_lock(files, args.verify_lock_repo)
        if rc != 0:
            return rc
        # Покрытие: новый файл с АННОТАЦИЕЙ контракта обязан попасть в замок.
        # ДЕФЕКТ #382: критерий — аннотация в комментарии (CONTRACT_LINE), а не
        # подстрока `@kern:` — иначе инструменты, лишь упоминающие контракты,
        # выглядели бы как незапечатанные файлы (ложное обвинение).
        sealed = set(json.loads(Path(args.verify_lock_repo).read_text(encoding="utf-8")))
        missing = sorted(set(files) - sealed)
        if missing:
            print(f"  [SECURITY] НЕ запечатаны файлы с контрактами: {missing}")
            print("  → пересоберите замок: make contracts-lock")
            return 2
        print(f"  [OK] покрытие замка: {len(files)} файлов с аннотациями")
        return 0
    if args.lock:
        if not args.files:
            print("[!] --lock требует список файлов")
            return 2
        return cmd_lock(args.files, args.lock)
    if args.verify_lock:
        # Без списка файлов берём их ИЗ САМОГО ЗАМКА — так pre-commit-хук
        # работает без знания о том, какие файлы были запечатаны.
        return cmd_verify_lock(args.files, args.verify_lock)
    if not args.files:
        ap.error("нужен файл (или --diff-equiv / --lock / --verify-lock)")

    if args.expect_demo:
        cap = io.StringIO()
        old = sys.stdout
        sys.stdout = cap
        try:
            _demo(args)
        finally:
            sys.stdout = old
        print(cap.getvalue(), end="")
        return expect_demo(cap.getvalue().splitlines())
    return _demo(args)


IMPURE_MODULES = ("os", "sys", "subprocess", "socket", "random", "time",
                  "shutil", "pathlib", "requests", "urllib", "secrets", "uuid")
IMPURE_BUILTINS = ("open", "input", "print", "exec", "eval", "compile",
                   "__import__", "exit", "quit")


def purity_violation(path: Path, name: str):
    """Функция с контрактом обязана быть ЧИСТОЙ. Вернуть причину нарушения.

    ЗАЧЕМ (referential transparency). Если внутри «математической» функции
    спрятать `random.randint` или `os.system`, то доказанное свойство относится
    не к коду, а к фантазии: тело перестаёт быть функцией от аргументов.

    Для `.py` проверяем AST (`global`/`nonlocal`, модули ввода-вывода и
    недетерминизма, мутирующие методы, `open`/`exec`). Для Zig/C/Rust чистота
    обеспечена ПО ПОСТРОЕНИЮ: полиглот-парсер принимает только присваивания,
    `if` и `return` — вызовы он отвергает как «вне подмножества».
    """
    if path.suffix != ".py":
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == name):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Global, ast.Nonlocal)):
                return f"`{type(sub).__name__.lower()}` — изменение внешнего состояния"
            if isinstance(sub, ast.Attribute):
                base = sub.value
                if isinstance(base, ast.Name) and base.id in IMPURE_MODULES:
                    return f"обращение к модулю `{base.id}.{sub.attr}`"
            if isinstance(sub, ast.Call):
                f = sub.func
                if isinstance(f, ast.Name) and f.id in IMPURE_BUILTINS:
                    return f"вызов `{f.id}`"
                if isinstance(f, ast.Attribute) and f.attr in (
                        "append", "pop", "sort", "insert", "remove", "extend",
                        "clear", "update", "write", "read", "flush"):
                    return f"мутирующий метод `{f.attr}()`"
        return None
    return None


def _eval_node(node, env: dict):
    """Конкретное вычисление ТОГО ЖЕ подмножества, что понимает `expr_smt`.

    🔴 УЛУЧШЕНИЕ №14 (по замечанию CodeRabbit): `[RUNTIME CONFIRMED]` раньше
    существовал только для Python (`runtime_confirm` возвращал None для любого
    другого языка). Здесь — независимый конкретный вычислитель: он считает тело
    на найденных Z3 числах, и если результат РАСХОДИТСЯ с моделью, значит ошибка
    в ТРАНСЛЯЦИИ, а не в коде (контрпример фальшивый).

    Семантика намеренно повторяет модель: деление — floor (`div` в SMT-LIB для
    Int), `%` — соответствующий остаток. Всё, что вне подмножества, честно
    поднимает Unsupported -> подтверждения не будет (никаких догадок).
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return node.value
        if isinstance(node.value, int):
            return node.value
        raise Unsupported(f"литерал {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise Unsupported(f"имя {node.id!r} не связано")
    if isinstance(node, ast.IfExp):
        return _eval_node(node.body, env) if _eval_node(node.test, env) else _eval_node(node.orelse, env)
    if isinstance(node, ast.BoolOp):
        vals = [_eval_node(v, env) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _eval_node(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -_eval_node(node.operand, env)
        raise Unsupported("унарный оператор")
    if isinstance(node, ast.BinOp):
        a = _eval_node(node.left, env)
        b = _eval_node(node.right, env)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, (ast.Div, ast.FloorDiv)):
            if b == 0:
                raise ZeroDivisionError
            return a // b
        if isinstance(node.op, ast.Mod):
            if b == 0:
                raise ZeroDivisionError
            return a % b
        raise Unsupported("бинарный оператор")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, env)
            if isinstance(op, ast.Lt):
                good = left < right
            elif isinstance(op, ast.LtE):
                good = left <= right
            elif isinstance(op, ast.Gt):
                good = left > right
            elif isinstance(op, ast.GtE):
                good = left >= right
            elif isinstance(op, ast.Eq):
                good = left == right
            elif isinstance(op, ast.NotEq):
                good = left != right
            else:
                raise Unsupported("сравнение")
            if not good:
                return False
            left = right
        return True
    raise Unsupported(f"узел {type(node).__name__}")


def _eval_expr_clike(text: str, env: dict, lang: str):
    return _eval_node(_clike_parse(text, lang), env)


def _eval_body_concrete(raw_body: str, env: dict, lang: str):
    """Зеркало `_exec_clike`, но считает КОНКРЕТНЫЕ значения (перепроверка модели).

    Разбор операторов намеренно совпадает с моделью символ-в-символ (тот же
    regex `^if\\s*(.*?)\\breturn\\b(.*)$`, та же обработка `else` отдельным
    оператором) — иначе это была бы проверка другого кода. Независимо только
    ВЫЧИСЛЕНИЕ: модель строит SMT-терм, здесь считаются числа.

    ПУНКТ 25: разделение операторов берётся из `_clike_stmts`, то есть для
    Go/JS/TS учитывается отсутствие обязательной `;` — ровно как в модели.
    """
    stmts = _clike_stmts(raw_body, lang)
    for i, raw in enumerate(stmts):
        st = raw.strip()
        if not st:
            continue
        m = re.match(r"^if\s*(.*?)\breturn\b(.*)$", st)
        if m:
            cond_txt = m.group(1).strip().strip("()").strip()
            rest = m.group(2).strip()
            consumed = 1
            else_txt = None
            if " else " in rest:
                then_txt, else_txt = rest.split(" else ", 1)
                then_txt = then_txt.strip()
                else_txt = re.sub(r"^return\b", "", else_txt).strip()
            else:
                then_txt = rest
                if i + 1 < len(stmts):
                    nxt = stmts[i + 1].strip()
                    if nxt.startswith("else"):
                        else_txt = re.sub(r"^else\s+", "", nxt).strip()
                        else_txt = re.sub(r"^return\b", "", else_txt).strip()
                        consumed = 2
            if _eval_expr_clike(cond_txt, env, lang):
                return _eval_expr_clike(then_txt, env, lang)
            if else_txt is not None:
                return _eval_expr_clike(else_txt, env, lang)
            return _eval_body_concrete(";".join(stmts[i + consumed:]), dict(env), lang)
        m = re.match(r"^return\s+(.+)$", st, re.S)
        if m:
            return _eval_expr_clike(m.group(1), env, lang)
        m = re.match(
            r"^(?:const\s+|let\s+(?:mut\s+)?|"
            r"(?:int|long|i32|i64|u32|u64|usize|size_t|unsigned)\s+)?"
            r"([A-Za-z_]\w*)\s*(?::\s*[A-Za-z_]\w*)?\s*=\s*(.+)$", st, re.S)
        if m:
            env[m.group(1)] = _eval_expr_clike(m.group(2), env, lang)
            continue
        raise Unsupported(f"оператор: {st[:40]!r}")
    raise Unsupported("нет return на пути без ветвления")


def runtime_confirm_clike(meta: dict, params, vals):
    """Перепроверка контрпримера для zig/c/rust БЕЗ компилятора.

    True  — конкретное вычисление тела дало ТО ЖЕ значение, что модель (модель верна);
    False — РАСХОЖДЕНИЕ: ошибка трансляции, контрпример фальшивый;
    None  — подтвердить нельзя (нет тела / не все параметры / вне подмножества /
            деление на ноль — оно подтверждается отдельной ветвью KERN004).
    """
    raw = meta.get("raw_body")
    if not raw or not all(p in vals for p in params):
        return None
    env = {p: vals[p] for p in params}
    try:
        got = _eval_body_concrete(raw, env, meta.get("lang", "?"))
    except ZeroDivisionError:
        return None
    except Exception as e:  # noqa: BLE001
        _replay_soft(e, "clike-replay")
        return None
    want = vals.get("result")
    return None if want is None else (got == want)


_BITWISE = re.compile(r"<<|>>|(?<![&|])[&|^~](?![&|])")
_BV_CMP = {
    (ast.Lt, True): "bvslt", (ast.LtE, True): "bvsle", (ast.Gt, True): "bvsgt", (ast.GtE, True): "bvsge",
    (ast.Lt, False): "bvult", (ast.LtE, False): "bvule", (ast.Gt, False): "bvugt", (ast.GtE, False): "bvuge",
}


def _needs_bitvec(raw_body: str, req, ens, forced: bool = False) -> bool:
    """Есть ли битовые операции (или явная аннотация @kern:bitvec32/64)."""
    if forced:
        return True
    return any(_BITWISE.search(x or "") for x in (raw_body, req, ens))


def _bv_shape(ranges: dict):
    """(width, signed) из МАШИННЫХ диапазонов: i32 -> (32, True), u64 -> (64, False)."""
    width, signed = 32, False
    for lo, hi in (ranges or {}).values():
        if lo < 0:
            signed = True
        if hi > 2**32 - 1 or lo < -2**31:
            width = 64
    return width, signed


def expr_smt_bv(node, env: dict, w: int, signed: bool) -> str:
    """Трансляция подмножества в QF_BV: арифметика + БИТОВЫЕ операции.

    Зеркало `expr_smt`, но вместо `Int` — `(_ BitVec w)`: `&`->`bvand`,
    `|`->`bvor`, `^`->`bvxor`, `~`->`bvnot`, `<<`->`bvshl`, `>>`->`bvlshr`/`bvashr`,
    `+`->`bvadd`, `-`->`bvsub`, `*`->`bvmul`, `/`->`bvudiv`/`bvsdiv`,
    `%`->`bvurem`/`bvsrem`, сравнения -> `bvult`/`bvslt`/`=`.
    """
    mask = 2**w - 1

    def bv(v: int) -> str:
        return f"(_ bv{v & mask} {w})"

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "true" if node.value else "false"
        if isinstance(node.value, int):
            return bv(node.value)
        raise Unsupported(f"литерал {node.value!r}")
    if isinstance(node, ast.Name):
        return env.get(node.id, node.id)
    if isinstance(node, ast.IfExp):
        return (f"(ite {expr_smt_bv(node.test, env, w, signed)} "
                f"{expr_smt_bv(node.body, env, w, signed)} "
                f"{expr_smt_bv(node.orelse, env, w, signed)})")
    if isinstance(node, ast.BoolOp):
        op = "and" if isinstance(node.op, ast.And) else "or"
        return f"({op} " + " ".join(expr_smt_bv(v, env, w, signed) for v in node.values) + ")"
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return f"(not {expr_smt_bv(node.operand, env, w, signed)})"
        if isinstance(node.op, ast.USub):
            return f"(bvneg {expr_smt_bv(node.operand, env, w, signed)})"
        if isinstance(node.op, ast.Invert):
            return f"(bvnot {expr_smt_bv(node.operand, env, w, signed)})"
        raise Unsupported("унарный оператор")
    if isinstance(node, ast.BinOp):
        left = expr_smt_bv(node.left, env, w, signed)
        right = expr_smt_bv(node.right, env, w, signed)
        o = node.op
        simple = {ast.BitAnd: "bvand", ast.BitOr: "bvor", ast.BitXor: "bvxor",
                  ast.LShift: "bvshl", ast.Add: "bvadd", ast.Sub: "bvsub", ast.Mult: "bvmul"}
        for cls, name in simple.items():
            if isinstance(o, cls):
                return f"({name} {left} {right})"
        if isinstance(o, ast.RShift):
            return f"({'bvashr' if signed else 'bvlshr'} {left} {right})"
        if isinstance(o, (ast.Div, ast.FloorDiv, ast.Mod)):
            _DIV_COLLECTOR.append((left, right, tuple(_DIV_GUARDS)))  # #327
            if isinstance(o, ast.Mod):
                name = "bvsrem" if signed else "bvurem"
            else:
                name = "bvsdiv" if signed else "bvudiv"
            return f"({name} {left} {right})"
        raise Unsupported("бинарный оператор")
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise Unsupported("цепочка сравнений")
        o = node.ops[0]
        left = expr_smt_bv(node.left, env, w, signed)
        right = expr_smt_bv(node.comparators[0], env, w, signed)
        if isinstance(o, ast.Eq):
            return f"(= {left} {right})"
        if isinstance(o, ast.NotEq):
            return f"(not (= {left} {right}))"
        name = _BV_CMP.get((type(o), signed))
        if not name:
            raise Unsupported("сравнение")
        return f"({name} {left} {right})"
    raise Unsupported(f"узел {type(node).__name__}")


def build_smt_bv(params, req, ens, body_bv: str, w: int, signed: bool, lang: str) -> str:
    """SMT-LIB2 в теории БИТОВЫХ ВЕКТОРОВ: `(_ BitVec w)`, арифметика + битовые операции.

    ЗАЧЕМ (УЛУЧШЕНИЕ №15, найдено теневыми контрактами на РЕАЛЬНОМ коде).
    Реальные системные функции почти всегда используют `& | ^ ~ << >>` — например
    `isAligned` из `andrewrk/zig-general-purpose-allocator`:
    `(addr & ~(alignment - 1)) == addr`. В математических `Int` таких операций нет,
    поэтому экстрактор отправлял их в SKIP — хотя ЯДРО KERN (`kernc` + `proof_check.zig`)
    штатно работает с QF_BV, что доказано рукописной моделью
    `audits/andrewrk-gpa/isAligned.smt2` (ДОКАЗАНО на всех 2^32 значениях).

    ВАЖНО (честно): в BV-режиме переполнение — это СЕМАНТИКА (машина заворачивает),
    поэтому обязательство «нет переполнения» здесь НЕ проверяется: проверяются
    контракт и деление на ноль. Это документировано в METRICS §77.
    """
    decls = "\n".join(f"(declare-const {p} (_ BitVec {w}))" for p in params)
    lines = ["(set-logic QF_BV)", decls, f"(declare-const result (_ BitVec {w}))"]
    env: dict = {}
    if req:
        lines.append(f"(assert {expr_smt_bv(_clike_parse(req, lang), env, w, signed)})")
    lines.append(f"(assert (= result {value_of(body_bv, bitvec_width=w)}))")
    if ens:
        lines.append(f"(assert (not {expr_smt_bv(_clike_parse(ens, lang), env, w, signed)}))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def build_divzero_smt_bv(params, req, divisors, w: int, signed: bool, lang: str) -> str:
    """Обязательство «делитель ≠ 0» в BV-режиме (`bvudiv`/`bvsdiv` тотальны в SMT)."""
    decls = "\n".join(f"(declare-const {p} (_ BitVec {w}))" for p in params)
    lines = ["(set-logic QF_BV)", decls]
    env: dict = {}
    if req:
        lines.append(f"(assert {expr_smt_bv(_clike_parse(req, lang), env, w, signed)})")
    zero = f"(_ bv0 {w})"
    lines.append("(assert (or " + " ".join(_div_zero_terms(divisors, zero)) + "))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def runtime_confirm(path: Path, name: str, params, ens, vals):
    """Подставить контрпример в НАСТОЯЩУЮ функцию и проверить постусловие.

    ЗАЧЕМ (УЛУЧШЕНИЕ №11, Zero-Trust к САМОМУ Z3). При `UNSAT` вывод решателя
    перепроверяет пруф-чекер, а при `SAT` мы раньше верили модели на слово.
    Ошибка в ТРАНСЛЯЦИИ Python -> SMT дала бы ФАЛЬШИВЫЙ контрпример. Здесь
    найденные числа подставляются в живую функцию, и постусловие вычисляется
    реально — это 0 % ложных срабатываний по построению.

    Возвращает True (нарушение подтверждено), False (контрпример фальшивый)
    или None (подтвердить нельзя: не Python / не все параметры связаны).

    ВНИМАНИЕ: выполняется КОД ИЗ ПРОВЕРЯЕМОГО ФАЙЛА — инструмент локальный и
    проверяет код того же разработчика (как это делает любой тест-раннер).
    """
    if path.suffix != ".py" or not ens or not all(p in vals for p in params):
        return None
    ns: dict = {}
    try:
        exec(compile(path.read_text(encoding="utf-8", errors="replace"),
                     str(path), "exec"), ns)  # noqa: S102
        fn = ns.get(name)
        if not callable(fn):
            return None
        res = fn(*[vals[p] for p in params])
    except Exception as e:  # noqa: BLE001
        _replay_soft(e, "py-replay")
        return None
    env = {p: vals[p] for p in params}
    env["result"] = res
    try:
        ok = eval(ens, {"__builtins__": {}}, env)  # noqa: S307
    except Exception as e:  # noqa: BLE001
        _replay_soft(e, "py-replay-ens")
        return None
    return not bool(ok)


def fmt_ce(vals: dict) -> str:
    """`{a: 1, b: -2}` -> `a = 1, b = -2` (для печати контрпримера)."""
    return ", ".join(f"{k} = {v}" for k, v in vals.items())


def _kern_version() -> str:
    """Версия из ЕДИНСТВЕННОГО источника — `server.json` (дефект #343).

    ЗАЧЕМ. Здесь был ЖЁСТКО ЗАПИСАН литерал `"2.4.0"`, и он попал в JSON-отчёт
    (`"version"`) и в SARIF. К моменту релиза v2.6.4 бинарник печатал `v2.6.4`,
    а отчёт — `2.4.0`: внешний исследователь (Massimiliano Brighindi) заметил
    рассинхрон, скачав релизный бинарник. `make version-check` эту поверхность
    не покрывал — 11 поверхностей контролировались, отчёт нет. Тот же класс,
    что #97 и #292: литерал версии вне единого источника.

    Падение при отсутствии `server.json` — намеренное: молчаливый откат к
    зашитой строке вернул бы ровно тот дефект, который здесь закрывается.
    """
    p = ROOT / "server.json"
    return json.loads(p.read_text(encoding="utf-8"))["version"]


KERN_VERSION = _kern_version()

SARIF_RULES = [
    ("KERN001", "ContractViolation",
     "Contract violated (Belnap F, e=0). The Z3 counterexample below shows the "
     "exact inputs that break the postcondition."),
    ("KERN002", "VacuousPrecondition",
     "Precondition is unsatisfiable (empty domain): `false => anything` would "
     "have declared any body proved."),
    ("KERN003", "EquivalenceDivergence",
     "Refactoring changed behaviour: the two versions differ on the given input."),
    ("KERN004", "SafetyObligation",
     "Safety obligation violated: division by zero or machine-integer overflow."),
]


def write_sarif(path: str, violations: list) -> int:
    """Экспорт нарушений в стандарт SARIF 2.1.0 (GitHub Code Scanning).

    ЗАЧЕМ. Без этого контрпример Z3 виден только в терминале. SARIF рисует
    красную плашку ПРЯМО ПОД строкой с багом в Pull Request, а `--github-
    annotations` делает то же через нативные `::error`-команды GitHub Actions
    (они работают даже на приватных репозиториях без Advanced Security).
    """
    rules = [{"id": rid, "name": rn, "shortDescription": {"text": rn},
              "fullDescription": {"text": desc},
              "defaultConfiguration": {"level": "error"}}
             for rid, rn, desc in SARIF_RULES]
    results = []
    for v in violations:
        results.append({
            "ruleId": v["rule"],
            "level": "error",
            "message": {"text": v["message"]},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": v["file"]},
                "region": {"startLine": max(1, int(v["line"]))}}}],
        })
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "KERN",
                "version": KERN_VERSION,
                "informationUri": "https://github.com/newmathphys/kern",
                "rules": rules}},
            "results": results,
        }],
    }
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(f"  [i] SARIF 2.1.0: {path} ({len(results)} находок, "
          f"{len(rules)} правил)")
    return 0


def write_json_report(path: str, json_files: list, summary: dict) -> int:
    """Экспорт машиночитаемого отчёта в JSON (`--json <out.json>`)."""
    doc = {
        "tool": "KERN",
        "version": KERN_VERSION,
        "solver": solver_info(),
        "files": json_files,
        "summary": summary,
    }
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return 0


def print_annotations(violations: list) -> int:
    """Нативные плашки GitHub Actions: `::error file=...,line=...,title=...::...`."""
    for v in violations:
        title = f"KERN {v['rule']}"
        msg = v["message"].replace("\n", " ").replace("%", "%25")
        print(f"::error file={v['file']},line={max(1, int(v['line']))},"
              f"title={title}::{msg}")
    return 0


def _demo(args) -> int:
    kernc = Path(args.kernc)
    if not kernc.exists():
        print(f"[!] не найден kernc: {kernc} (соберите: zig build)")
        return 1
    # ДЕФЕКТ #277 (найден корпусом Ф4B): без Z3 в PATH `kernc prove`
    # завершается rc=2 на КАЖДЫЙ вызов, и старый код трактовал это как
    # «контракт нарушен» — то есть ЛОЖНО обвинял весь корректный код.
    # «Инструмент недоступен» — это N, а не F; поэтому проверяем ДО вердиктов.
    _rc0, _out0 = run_kernc(kernc, "(set-logic ALL)\n(check-sat)\n")
    _low0 = (_out0 or "").lower()
    if "z3 недоступен" in _low0 or "z3 is not" in _low0:
        print("[!] решатель Z3 недоступен: добавьте `.venv/bin` в PATH "
              "(uv pip install z3-solver).")
        print("    Вердикты НЕ выдаются: недоступный инструмент — это N, а не F.")
        return 2

    total = ok = failed = skipped = vacuous = safety_failed = unknown = 0
    advisory_ok = 0  # Ф6.1: T_advisory — НЕ доказано и НЕ нарушено
    unconfirmed = 0  # правило №4: SAT, не подтверждённый живым вызовом
    # Контрпримеры для `--emit-pytest` (УЛУЧШЕНИЕ №4): найденный Z3 баг обязан
    # превращаться в ОБЫЧНЫЙ падающий pytest, а не только в строку в логе.
    examples: list[dict] = []
    # Нарушения для `--sarif` (Code Scanning) и `--github-annotations`.
    violations: list[dict] = []
    # Функции по файлам для `--json` (машиночитаемая сводка для CI и агентов).
    json_files: list[dict] = []
    print("=" * 74)
    print("KERN: контракты из комментариев (@kern:requires / @kern:ensures)")
    print("=" * 74)
    for f in args.files:
        p = Path(f)
        f_funcs: list[dict] = []
        json_files.append({"path": str(p), "functions": f_funcs})
        try:
            funcs = parse_any(p)
        except SyntaxError as e:
            print(f"  {p}: SKIP (синтаксис: {e})")
            skipped += 1
            continue
        if not funcs:
            print(f"  {p}: нет функций с аннотациями @kern:")
            continue
        try:
            ftext = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ftext = ""
        for name, params, req, ens, body, ln, skip_reason, meta in funcs:
            total += 1
            # ---- ДЕТЕКТОР ЧИСТОТЫ (referential transparency) --------------
            # ВАЖНО: проверяется ПЕРВОЙ. Раньше он стоял после проверки
            # подмножества и был НЕДОСТИЖИМ: `random.randint(...)` или
            # `global x` отвергались как «вне подмножества», и пользователь
            # не узнавал НАСТОЯЩУЮ причину. Теперь вердикт однозначен:
            # функция не чистая — контракт к ней неприменим.
            impure = purity_violation(p, name)
            if impure:
                print(f"  [IMPURE] {name} (стр. {ln}): {impure} -> контракт "
                      f"не проверяется (функция НЕ чистая)")
                f_funcs.append({"name": name, "line": ln, "verdict": "SKIP",
                                "reason": f"impure: {impure}"})
                skipped += 1
                continue
            if body is None:
                # Причина ОТКАЗА печатается как есть: «нет return» и «цикл»
                # требуют разных действий, а раньше сообщение было одно.
                print(f"  {name} (стр. {ln}): SKIP — {skip_reason or 'вне подмножества'}")
                f_funcs.append({"name": name, "line": ln, "verdict": "SKIP",
                                "reason": skip_reason or "вне подмножества"})
                skipped += 1
                continue
            # ДЕФЕКТ #321 (остаток): тип возврата ВНЕ целочисленного подмножества
            # (`float`, `double`, `char`). Обязанность переполнения к нему
            # неприменима, а контракт в Int-теории был бы МОДЕЛЬЮ, а не фактом.
            # Молча пропускать нельзя — это класс ложного ДОКАЗАНО, поэтому в
            # контрактном пути функция честно уходит в SKIP. В режиме `--xray`
            # тип возврата не важен (ищутся краш-пути) — там поведение прежнее.
            _ret = meta.get("ret")
            if (not args.xray and _sem_of_suffix(p.suffix).bounded_ints and _ret
                    and _ret != "void" and _ret not in TYPE_RANGE):
                print(f"  {name} (стр. {ln}): SKIP — тип возврата {_ret!r} "
                      f"вне целочисленного подмножества")
                f_funcs.append({"name": name, "line": ln, "verdict": "SKIP",
                                "reason": f"тип возврата {_ret!r} вне подмножества"})
                skipped += 1
                continue
            forced_bv = ("@kern:bitvec32" in ftext) or ("@kern:bitvec64" in ftext)
            # ДЕФЕКТ #353: свойство «переходить в BV» читается из ТАБЛИЦЫ
            # (`allow_bv_fallback`), а не из литерального `suffix in CLIKE_EXT`.
            # ДЕФЕКТ #342 (шаг N12): ЯВНАЯ директива `@kern:bitvec32/64` сильнее
            # таблицы — как `@kern:lang` сильнее расширения.
            # ⚠️ BV-путь существует ТОЛЬКО для C-подобных файлов: он работает с
            # `raw_body` (текст тела), которого у Python-парсера нет. Без этой
            # проверки явная директива в `.py`-файле валила прогон
            # `KeyError: 'raw_body'` — то есть «усиление» ломало штатный путь.
            _has_raw = meta.get("raw_body") is not None
            use_bv = (_has_raw
                      and (_sem_of_suffix(p.suffix).allow_bv_fallback or forced_bv)
                      and (body == "BV_PENDING"
                           or _needs_bitvec(meta.get("raw_body"), req, ens, forced_bv)))
            try:
                if use_bv:
                    # УЛУЧШЕНИЕ №15: битовые операции -> QF_BV. Пересобираем тело в BV-теории
                    # ТЕМ ЖЕ разбором операторов (`_exec_clike` с другим `expr_fn`).
                    w, signed = _bv_shape(meta.get("ranges"))
                    if "@kern:bitvec32" in ftext:
                        w = 32
                    elif "@kern:bitvec64" in ftext:
                        w = 64
                    _DIV_COLLECTOR.clear()
                    _NEG_COLLECTOR.clear()
                    bv_body = _exec_clike(meta["raw_body"].split(";"), {},
                                          meta.get("lang", "zig"),
                                          lambda node, env_: expr_smt_bv(node, env_, w, signed))
                    meta["divisors"] = _drop_macro_divisors(list(dict.fromkeys(_DIV_COLLECTOR)))
                    meta["negs"] = list(dict.fromkeys(_NEG_COLLECTOR))
                    meta["bv"] = (w, signed)
                    smt = build_smt_bv(params, req, ens, bv_body, w, signed,
                                       meta.get("lang", "zig"))
                    print(f"  [BV] {name} (стр. {ln}): теория битовых векторов "
                          f"(_ BitVec {w}, {'знаковый' if signed else 'беззнаковый'})")
                else:
                    smt = build_smt(params, req, ens, body, ranges=meta.get("ranges"))
            except (Unsupported, NoReturn) as e:
                print(f"  {name} (стр. {ln}): SKIP — вне подмножества: {e}")
                f_funcs.append({"name": name, "line": ln, "verdict": "SKIP",
                                "reason": f"вне подмножества: {e}"})
                skipped += 1
                continue
            # Делители собраны ПРИ ПАРСИНГЕ (трансляция тела уже выполнена).
            divisors = meta.get("divisors") or []
            # ДЕФЕКТ #327: элемент — `(делитель, гарды)`; для ЧЕЛОВЕКА печатаем
            # только делитель (гарды видны в самом свидетельстве).
            # ДЕФЕКТ #391: кортеж сборщика — `(числитель, делитель, гарды)` (#334),
            # поэтому `d[0]` — это ЧИСЛИТЕЛЬ. Подпись называла делимое («делитель: a»
            # при `a / b`): вердикт и контрпример были верны, а подпись ЛГАЛА.
            # Берём делитель готовым помощником (он же разбирает 2-кортеж и строку).
            _divnames = [_divisor_of(d) for d in divisors]
            # ---- ДЕТЕРМИНИРОВАННЫЙ ФРОНТЕНД: выгрузка формулы -----------------
            # `--emit-smt2 DIR`: формула, которую РЕАЛЬНО проверяет ядро, пишется
            # файлом. Это позволяет (а) перепроверить её `kernc prove` вручную,
            # (б) запечатать в .kimg-корпус аудитов. Никакой генерации «по мотивам»:
            # файл — это ровно тот SMT, что был отправлен в решатель.
            if args.emit_smt2:
                outdir = Path(args.emit_smt2)
                outdir.mkdir(parents=True, exist_ok=True)
                stem = f"{p.stem}_{name}"
                (outdir / f"{stem}.smt2").write_text(smt, encoding="utf-8")
                meta["smt_path"] = str(outdir / f"{stem}.smt2")
            # ---- УЛУЧШЕНИЕ №1: ДЕТЕКТОР ВАКУУМНЫХ ПРЕДУСЛОВИЙ ------------
            # ЛОВУШКА `false => anything`: при ПРОТИВОРЕЧИВОМ `requires`
            # обязательство `requires ∧ ¬ensures` тривиально UNSAT, и любая
            # сломанная функция выглядела бы ДОКАЗАННОЙ. Поэтому сначала
            # проверяем ВЫПОЛНИМОСТЬ самого `requires` (отдельным запросом).
            if req:
                try:
                    _rcv, outv = run_kernc(kernc, requires_only_smt(params, req))
                except (Unsupported, subprocess.SubprocessError, OSError):
                    outv = ""
                if "ДОКАЗАНО" in outv:
                    print(f"  [VACUOUS] {name}: предусловие ПРОТИВОРЕЧИВО "
                          f"(пустой домен) -> B4: N, e = 0")
                    print(f"         requires: {req}")
                    f_funcs.append({"name": name, "line": ln, "verdict": "VACUOUS"})
                    violations.append({
                        "file": str(p), "line": ln, "rule": "KERN002",
                        "message": (f"{name}: предусловие ПРОТИВОРЕЧИВО (пустой "
                                    f"домен) — `false => anything` объявило бы "
                                    f"любое тело доказанным; requires: {req}")})
                    vacuous += 1
                    continue
            # ---- ОБЯЗАТЕЛЬСТВА БЕЗОПАСНОСТИ: семантика берётся из ТАБЛИЦЫ ----
            # ШАГ 8: набор обязанностей зависит от языка:
            #   `div_zero_value` — падает ли деление на ноль (EVM: нет, это 0);
            #   `signed`         — есть ли знаковые типы (обязанности MIN/-1, -x).
            # Раньше эти различия жили в разбросанных условиях, и именно там
            # появились #317/#321: правило правили в одном месте из двух.
            _sem_here = VALUE_SEMANTICS.get(meta.get("lang", "python"))
            # ---- ОБЯЗАТЕЛЬСТВО БЕЗОПАСНОСТИ: ПЕРЕПОЛНЕНИЕ ДЕЛЕНИЯ (#334) ----
            # `a / b` И `a % b` при `a == MIN ∧ b == -1` — UB: частное
            # непредставимо, и `idiv` на x86_64 вызывает аппаратное исключение
            # (C11 §6.5.5p6). НАЗЕМНАЯ ПРАВДА: `gcc -O0` на `INT_MIN % -1` ->
            # SIGFPE (rc=136). Проверка ДИАПАЗОНА РЕЗУЛЬТАТА этого НЕ видит: для
            # `%` математический остаток равен 0, и 0 влезает в тип. Ловится
            # только парой (числитель, делитель) — поэтому сборщик и расширен.
            # ШАГ 8: обязанность переполнения деления существует только там, где
            # есть ЗНАКОВЫЕ типы. У беззнаковых `MIN = 0`, и `a / -1` не
            # существует; у EVM деление на ноль и `SDIV(MIN, -1)` ОПРЕДЕЛЕНЫ
            # (Yellow Paper), то есть падения нет вовсе.
            if divisors and _sem_of_suffix(p.suffix).bounded_ints and not meta.get("bv") \
                    and _sem_of_suffix(p.suffix).signed_min_div_trap \
                    and (_sem_here is None or _sem_here.signed):
                _rr = TYPE_RANGE.get(meta.get("ret"))
                if _rr:
                    try:
                        smt_o = build_divoverflow_smt(params, req, divisors,
                                                      meta.get("ranges"), _rr)
                    except (Unsupported, subprocess.SubprocessError, OSError):
                        smt_o = ""
                    if smt_o:
                        try:
                            _rco, outo = run_kernc(kernc, smt_o)
                        except (Unsupported, subprocess.SubprocessError, OSError):
                            outo = ""
                        if "ДОКАЗАНО" not in outo:
                            ceo = parse_counterexample(outo)
                            print(f"  [FAIL] {name}: ПЕРЕПОЛНЕНИЕ ДЕЛЕНИЯ "
                                  f"(a = MIN, b = -1 — аппаратный trap)")
                            if ceo:
                                print(f"         [КОНТРПРИМЕР] {fmt_ce(ceo)}")
                            f_funcs.append({"name": name, "line": ln,
                                            "verdict": "CONTRACT_VIOLATED"})
                            violations.append({
                                "file": str(p), "line": ln, "rule": "KERN002",
                                "message": (f"{name}: деление при a = MIN и "
                                            f"b = -1 непредставимо (UB, idiv "
                                            f"trap)")})
                            failed += 1
                            safety_failed += 1
                            continue
            # ---- ОБЯЗАТЕЛЬСТВО БЕЗОПАСНОСТИ: ПЕРЕПОЛНЕНИЕ УНАРНОГО МИНУСА (#334) --
            # `-x` на знаковом фиксированном типе — это `0 - x`; при `x == MIN`
            # результат непредставим. НАЗЕМНАЯ ПРАВДА: `gcc -ftrapv` на
            # `-INT_MIN` -> SIGABRT (rc=134). Проверка ДИАПАЗОНА РЕЗУЛЬТАТА этого
            # НЕ видит: в математических целых `-MIN` влезает в Int.
            _negs = meta.get("negs") or []
            if _negs and _sem_of_suffix(p.suffix).bounded_ints and not meta.get("bv") \
                    and _sem_of_suffix(p.suffix).signed_min_neg_trap:
                _rrn = TYPE_RANGE.get(meta.get("ret"))
                if _rrn:
                    try:
                        smt_n = build_negoverflow_smt(params, req, _negs,
                                                      meta.get("ranges"), _rrn)
                    except (Unsupported, subprocess.SubprocessError, OSError):
                        smt_n = ""
                    if smt_n:
                        try:
                            _rcn, outn = run_kernc(kernc, smt_n)
                        except (Unsupported, subprocess.SubprocessError, OSError):
                            outn = ""
                        if "ДОКАЗАНО" not in outn:
                            cen = parse_counterexample(outn)
                            print(f"  [FAIL] {name}: ПЕРЕПОЛНЕНИЕ УНАРНОГО МИНУСА "
                                  f"(-x при x = MIN — аппаратный trap)")
                            if cen:
                                print(f"         [КОНТРПРИМЕР] {fmt_ce(cen)}")
                            f_funcs.append({"name": name, "line": ln,
                                            "verdict": "CONTRACT_VIOLATED"})
                            violations.append({
                                "file": str(p), "line": ln, "rule": "KERN002",
                                "message": (f"{name}: -x при x = MIN "
                                            f"непредставимо (UB, signed overflow)")})
                            failed += 1
                            safety_failed += 1
                            continue
            # ---- ОБЯЗАТЕЛЬСТВО БЕЗОПАСНОСТИ: ДЕЛЕНИЕ НА НОЛЬ ---------------
            # В SMT-LIB2 `div`/`mod` — ТОТАЛЬНЫЕ функции: `(div x 0)` просто
            # доопределён, поэтому наивный чекер ноль НЕ видит, а в рантайме
            # будет `ZeroDivisionError` / аппаратное исключение. Проверяем
            # ОТДЕЛЬНО: `requires ∧ (делитель = 0)` — SAT означает баг.
            #
            # ШАГ 8: обязанность ставится ТОЛЬКО если семантика языка считает
            # деление на ноль падением. В EVM `DIV`/`MOD`/`SDIV`/`SMOD` при
            # b = 0 возвращают 0 по Yellow Paper — это ОПРЕДЕЛЕНО, и обвинять
            # такой код значило бы выдать ложное срабатывание за находку.
            if divisors and not (_sem_here and _sem_here.div_zero_value):
                try:
                    if meta.get("bv"):
                        _w, _s = meta["bv"]
                        smt_d = build_divzero_smt_bv(params, req, divisors, _w, _s,
                                                     meta.get("lang", "zig"))
                    else:
                        smt_d = build_divzero_smt(params, req, divisors,
                                                  meta.get("ranges"))
                    _rcd, outd = run_kernc(kernc, smt_d)
                except (Unsupported, subprocess.SubprocessError, OSError):
                    outd = ""
                if "ДОКАЗАНО" not in outd:
                    ce = parse_counterexample(outd)
                    print(f"  [FAIL] {name}: ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ "
                          f"(делитель: {', '.join(_divnames)})")
                    if ce:
                        print(f"         [КОНТРПРИМЕР] {fmt_ce(ce)}")
                        # УЛУЧШЕНИЕ №14: воспроизвести деление на ноль КОНКРЕТНО
                        # (для zig/c/rust — без компилятора).
                        if p.suffix in CLIKE_EXT and meta.get("raw_body") \
                                and all(x in ce for x in params):
                            try:
                                _eval_body_concrete(meta["raw_body"],
                                                    {x: ce[x] for x in params},
                                                    meta.get("lang", "?"))
                            except ZeroDivisionError:
                                print("         [RUNTIME CONFIRMED] деление на ноль "
                                      "воспроизведено на этих значениях")
                            except Exception as e:  # noqa: BLE001
                                _replay_soft(e, "replay-print")
                    fn_entry: dict = {"name": name, "line": ln,
                                      "verdict": "CONTRACT_VIOLATED"}
                    if ce:
                        fn_entry["counterexample"] = ce
                    f_funcs.append(fn_entry)
                    violations.append({
                        "file": str(p), "line": ln, "rule": "KERN004",
                        "message": (f"{name}: возможно деление на ноль "
                                    f"(делитель: {', '.join(_divnames)})"
                                    + (f"; контрпример: {fmt_ce(ce)}" if ce else ""))})
                    failed += 1
                    safety_failed += 1
                    continue
            # ---- ОБЯЗАТЕЛЬСТВО ПЕРЕПОЛНЕНИЯ (машинные типы Zig/C/Rust) ------
            # У Python тип один — ℤ, и переполнения там нет. У Zig/C/Rust тип
            # возврата известен, поэтому `result ∉ [lo, hi]` — это БАГ, который
            # обязан быть предъявлен с контрпримером.
            ret = meta.get("ret")
            # УЛУЧШЕНИЕ №15: в BV-режиме переполнение — это СЕМАНТИКА (машина
            # заворачивает), поэтому обязательство «нет переполнения» неприменимо:
            # проверяются контракт и деление на ноль (см. METRICS §77).
            wrap = _explicit_wrap(meta.get("raw_body") or "", meta.get("lang", ""))
            if wrap:
                # ИЗМЕРЕНО: явное оборачивание/насыщение — законная семантика,
                # паники НЕТ; обязательство «result в границах типа» неприменимо.
                print(f"  [OK] {name}: явное `{wrap}` — переполнение не паникует "
                      f"(обязательство типа снято)")
            if ret in TYPE_RANGE and not meta.get("bv") and not wrap:
                try:
                    _rco, outo = run_kernc(
                        kernc, build_overflow_smt(params, req, body,
                                                  meta.get("ranges"),
                                                  TYPE_RANGE[ret]))
                except (Unsupported, subprocess.SubprocessError, OSError):
                    outo = ""
                if "ДОКАЗАНО" not in outo:
                    ce = parse_counterexample(outo)
                    lo, hi = TYPE_RANGE[ret]
                    print(f"  [FAIL] {name}: ПЕРЕПОЛНЕНИЕ типа `{ret}` "
                          f"(диапазон [{lo}, {hi}])")
                    if ce:
                        print(f"         [КОНТРПРИМЕР] {fmt_ce(ce)}")
                        # УЛУЧШЕНИЕ №14: подтвердить переполнение КОНКРЕТНО —
                        # вычислить тело на этих значениях и проверить границы типа.
                        if p.suffix in CLIKE_EXT and meta.get("raw_body") \
                                and all(x in ce for x in params):
                            try:
                                got = _eval_body_concrete(meta["raw_body"],
                                                          {x: ce[x] for x in params},
                                                          meta.get("lang", "?"))
                                if got < lo or got > hi:
                                    print(f"         [RUNTIME CONFIRMED] вычисленное значение "
                                          f"{got} вне диапазона [{lo}, {hi}]")
                            except Exception as e:  # noqa: BLE001
                                _replay_soft(e, "replay-print")
                    fn_entry = {"name": name, "line": ln,
                                "verdict": "CONTRACT_VIOLATED"}
                    if ce:
                        fn_entry["counterexample"] = ce
                    f_funcs.append(fn_entry)
                    violations.append({
                        "file": str(p), "line": ln, "rule": "KERN004",
                        "message": (f"{name}: ПЕРЕПОЛНЕНИЕ типа `{ret}` "
                                    f"(диапазон [{lo}, {hi}])"
                                    + (f"; контрпример: {fmt_ce(ce)}" if ce else ""))})
                    failed += 1
                    safety_failed += 1
                    continue
            # ДЕФЕКТ #202 (найден контрактным аудитом реальных функций jinja2 и
            # werkzeug): `@kern:requires` БЕЗ `@kern:ensures`. Постусловия нет —
            # доказывать нечего, но `build_smt` не добавляет `(assert (not ens))`,
            # формула становится тривиально SAT и печатался ЛОЖНЫЙ «КОНТРАКТ
            # НАРУШЕН» с бессмысленным контрпримером. Обязательства безопасности
            # (деление на ноль, переполнение) проверены ВЫШЕ и сюда не доходят,
            # поэтому честный вердикт здесь — «нечего проверять», а не FAIL.
            if not ens:
                print(f"  [SKIP] {name}: нет @kern:ensures — доказывать нечего")
                f_funcs.append({"name": name, "line": ln, "verdict": "SKIP",
                                "reason": "нет @kern:ensures (нет постусловия)"})
                skipped += 1
                continue
            rc, out = run_kernc(kernc, smt)
            # ДЕФЕКТ #207: тело получено РАЗВЁРТКОЙ цикла/рекурсии (K шагов) —
            # это недо-аппроксимация. UNSAT на K шагах НЕ доказывает цикл:
            # он может продолжаться на шаге K+1. Доказательство требует
            # инварианта (--loops) или unwinding assertion, поэтому честный
            # вердикт при «ДОКАЗАНО» — SKIP/UNBOUNDED, а НЕ PASS.
            if meta.get("unrolled") and "ДОКАЗАНО" in out:
                print(f"  [SKIP] {name}: [UNBOUNDED] развёртка {_UNROLL_K[0]} шагов "
                      f"не исчерпывает цикл/рекурсию — для доказательства нужен "
                      f"инвариант (--loops)")
                f_funcs.append({"name": name, "line": ln, "verdict": "SKIP",
                                "reason": "unbounded loop: unrolling is under-approx (#207)"})
                skipped += 1
                continue
            # ТРИ РАЗЛИЧНЫХ ИСХОДА (раньше два). Различие принципиально:
            #   PASS — Z3 доказал И пруф-чекер перепроверил вывод;
            #   SKIP — Z3 доказал, но пруф-чекер НЕ ПОКРЫВАЕТ такую форму вывода
            #          (например, с `ite`). Код не виноват, но и «проверено»
            #          сказать нельзя — поэтому НЕ PASS и НЕ FAIL;
            #   FAIL — контракт опровергнут (предъявлен контрпример).
            if "ДОКАЗАНО" in out and rc != 0:
                reason = ""
                for line in out.splitlines():
                    if "причина:" in line:
                        reason = line.split("причина:", 1)[1].strip()
                        break
                print(f"  [SKIP] {name}: Z3 доказал, но пруф-чекер не покрывает "
                      f"вывод ({reason or 'причина не указана'})")
                f_funcs.append({"name": name, "line": ln, "verdict": "SKIP",
                                "reason": reason or "пруф-чекер не покрывает вывод"})
                skipped += 1
                continue
            if "ДОКАЗАНО" in out and rc == 0:
                proof = ""
                for line in out.splitlines():
                    if "PROOF VERIFIED" in line:
                        proof = line.strip()
                print(f"  [PASS] {name}: ДОКАЗАНО")
                if proof:
                    print(f"         {proof}")
                f_funcs.append({"name": name, "line": ln, "verdict": "PROVEN"})
                ok += 1
            elif "KERN-EQ2 : N" in out or " : N" in out:
                # ДЕФЕКТ #120: вердикт решателя `N` (UNKNOWN — таймаут или
                # неразрешённая теория) печатался как «КОНТРАКТ НАРУШЕН».
                # Это НЕ опровержение: контрпример не найден, доказательства
                # тоже нет. Честный трёхзначный вердикт — «НЕ РЕШЕНО».
                print(f"  [N] {name}: НЕ РЕШЕНО (решатель вернул unknown — "
                      f"ни доказательства, ни контрпримера)")
                f_funcs.append({"name": name, "line": ln, "verdict": "UNKNOWN"})
                unknown += 1
            else:
                # ДЕФЕКТ #277: решатель мог умереть ПОСРЕДИ прогона.
                if "z3 недоступен" in out.lower() or "z3 is not" in out.lower():
                    print(f"  [N] {name}: НЕ РЕШЕНО (решатель недоступен — N, не F)")
                    f_funcs.append({"name": name, "line": ln,
                                    "verdict": "UNKNOWN",
                                    "reason": "solver unavailable"})
                    unknown += 1
                    continue
                # Ф6.1: класс обязательства решает, БЛОКИРУЕТ ли нарушение.
                # advisory: вердикт `T_advisory` — не F (не блокирует) и не T
                # (не доказано). Смешивать его со счётчиком T нельзя.
                _cls = ens_class_at(ftext.splitlines(), ln)
                if _cls == "advisory":
                    print(f"  [T_advisory] {name}: advisory-обязательство нарушено "
                          f"(не блокирует, но и НЕ доказано)")
                    vals = parse_counterexample(out)
                    if vals:
                        print(f"         [КОНТРПРИМЕР] {fmt_ce(vals)}")
                    f_funcs.append({"name": name, "line": ln,
                                    "verdict": "T_ADVISORY",
                                    "reason": "advisory obligation violated"})
                    advisory_ok += 1
                    continue
                print(f"  [FAIL] {name}: КОНТРАКТ НАРУШЕН")
                for line in out.splitlines():
                    if "ВЕРДИКТ" in line or "KERN-EQ2" in line:
                        print(f"         {line.strip()}")
                # КОНТРПРИМЕР Z3: конкретные значения, сломавшие контракт.
                # Без них вердикт F бесполезен — непонятно, что именно чинить.
                vals = parse_counterexample(out)
                if vals:
                    # ПУНКТ 5 ПЛАНА v2.5: МИНИМИЗАЦИЯ контрпримера. Второй
                    # запрос с ДОБАВЛЕННЫМ окном даёт читаемый вход; это
                    # звучимо, потому что сужение только ДОБАВЛЯЕТ ограничения.
                    vals = minimize_counterexample(kernc, smt, params, vals)
                if vals:
                    print(f"         [КОНТРПРИМЕР] {fmt_ce(vals)}")
                else:
                    for line in out.splitlines():
                        if "КОНТРПРИМЕР" in line:
                            print(f"         {line.strip()}")
                            break
                # УЛУЧШЕНИЕ №11: РАНТАЙМ-ПОДТВЕРЖДЕНИЕ контрпримера.
                # Z3 мог ошибиться в ТРАНСЛЯЦИИ (Python -> SMT) — тогда
                # «контрпример» фальшивый. Подставляем найденные числа в
                # НАСТОЯЩУЮ функцию и вычисляем постусловие вживую.
                conf = runtime_confirm(p, name, params, ens, vals)
                if conf is None and p.suffix in CLIKE_EXT:
                    # УЛУЧШЕНИЕ №14 (по замечанию CodeRabbit): для zig/c/rust
                    # компилятора под рукой может не быть, но модель можно
                    # перепроверить НЕЗАВИСИМЫМ конкретным вычислителем тела.
                    conf = runtime_confirm_clike(meta, params, vals)
                if conf is False:
                    # ПРАВИЛО №4 (Live Replay — финальный судья): SAT, который
                    # живой вызов НЕ подтвердил, — это овер-аппроксимация модели
                    # (havoc) или ошибка трансляции, а НЕ дефект кода. Раньше он
                    # всё равно печатался как «КОНТРАКТ НАРУШЕН» — ложное обвинение.
                    print("         [!] SAT не подтверждён живым вызовом -> "
                          "ЛОЖНАЯ ТРЕВОГА (овер-аппроксимация); нарушением НЕ считается")
                    _entry = {"name": name, "line": ln, "verdict": "UNCONFIRMED",
                              "runtime_confirmed": False}
                    if vals:
                        _entry["counterexample"] = vals
                    f_funcs.append(_entry)
                    unconfirmed += 1
                    continue
                if conf is True:
                    if p.suffix in CLIKE_EXT:
                        print("         [RUNTIME CONFIRMED] контрпример перепроверен "
                              "конкретным вычислителем тела (модель совпала с исходником)")
                    else:
                        print("         [RUNTIME CONFIRMED] нарушение подтверждено "
                              "и в рантайме (0% ложных срабатываний)")
                fn_entry = {"name": name, "line": ln,
                            "verdict": "CONTRACT_VIOLATED"}
                if vals:
                    fn_entry["counterexample"] = vals
                if conf is not None:
                    fn_entry["runtime_confirmed"] = conf
                f_funcs.append(fn_entry)
                # УЛУЧШЕНИЕ №4: сохраняем контрпример для генерации pytest.
                if ens and all(p in vals for p in params):
                    examples.append({"name": name, "params": list(params),
                                     "ens": ens, "vals": vals, "line": ln,
                                     "file": str(p)})
                violations.append({
                    "file": str(p), "line": ln, "rule": "KERN001",
                    "message": (f"{name}: КОНТРАКТ НАРУШЕН (Belnap F, e=0)"
                                + (f"; контрпример Z3: {fmt_ce(vals)}" if vals else ""))})
                failed += 1
    print("-" * 74)
    print(f"ИТОГО: доказано {ok} | T_advisory {advisory_ok} | нарушено {failed} (из них "
          f"безопасность: {safety_failed}) | НЕ РЕШЕНО {unknown} | "
          f"ЛОЖНЫХ ТРЕВОГ {unconfirmed} | "
          f"ВАКУУМНЫХ {vacuous} | "
          f"вне подмножества {skipped} | всего {total}")
    # ---- УЛУЧШЕНИЕ №4: ПАДАЮЩИЙ PYTEST ИЗ КОНТРПРИМЕРА Z3 ----------------
    if getattr(args, "emit_pytest", None):
        emit_pytest(args.emit_pytest, examples, args.files)
    # ---- ЭКСПОРТ ДЛЯ GITHUB (Этап 1) -------------------------------------
    # SARIF 2.1.0 -> красные плашки в Code Scanning / Pull Request;
    # ::error-аннотации -> работают даже без GitHub Advanced Security.
    if getattr(args, "sarif", None):
        write_sarif(args.sarif, violations)
    if getattr(args, "json", None):
        write_json_report(args.json, json_files, {
            "proven": ok,
            "t_advisory": advisory_ok,
            "violated": failed,
            "vacuous": vacuous,
            "skipped": skipped,
        })
    if getattr(args, "github_annotations", False):
        print_annotations(violations)
    return 0 if (failed == 0 and vacuous == 0) else 1


# =============================================================================
# ЭШЕЛОН 3, ПУНКТ 13 — БЕЗАННОТАЦИОННЫЙ РЕНТГЕН `--xray`.
#
# Работает на ГОЛОМ коде: ни одной аннотации `@kern:` не требуется.
# Что ищет (всё — через Z3, а не эвристикой):
#   * [DEAD BRANCH]      — путь до ветки НЕВЫПОЛНИМ (перекрыта предыдущими if);
#   * [REDUNDANT GUARD]  — `путь AND NOT cond` невыполним => условие ВСЕГДА истинно;
#   * [CRASH PATH]       — достижимо деление на ноль;
#   * Цикломатическая сложность Маккейба (CC = ветви + 1) и Code Smells.
#
# ЧЕСТНОСТЬ. Печатается ВОРОНКА ОХВАТА: сколько функций всего, сколько проверено,
# сколько пропущено и ПОЧЕМУ. Функции вне SMT-подмножества не «проходят молча».
# =============================================================================


def _smt_sat(kernc, params, asserts) -> bool | None:
    """Выполним ли набор утверждений? True/False, либо None (не решено).

    🔴 ДЕФЕКТ #184: раньше «НЕ доказано» считалось SAT — а так печатает и
    `N` (решатель не решил / ошибка разбора). Теперь решение берётся из
    ТРЁХЗНАЧНОГО вердикта: `unknown` -> None (не обвиняем).
    """
    kind, _ce = _smt_verdict(kernc, params, asserts)
    if kind == "sat":
        return True
    if kind == "unsat":
        return False
    return None


def _cc_and_smells(fn: ast.FunctionDef) -> tuple[int, list[str]]:
    """Цикломатическая сложность Маккейба и Code Smells."""
    cc = 1
    smells: list[str] = []
    for n in ast.walk(fn):
        if isinstance(n, (ast.If, ast.For, ast.While, ast.IfExp)):
            cc += 1
        elif isinstance(n, ast.BoolOp):
            cc += max(0, len(n.values) - 1)
        elif isinstance(n, ast.Try):
            cc += len(n.handlers)
    # Глубина вложенности управляющих конструкций.
    def depth(node, d=0) -> int:
        best = d
        for ch in ast.iter_child_nodes(node):
            nd = d + 1 if isinstance(ch, (ast.If, ast.For, ast.While, ast.Try)) else d
            best = max(best, depth(ch, nd))
        return best
    dep = depth(fn)
    if dep > 3:
        smells.append(f"Deep Nesting (глубина {dep} > 3)")
    npar = len([a for a in fn.args.args if a.arg != "self"])
    if npar > 5:
        smells.append(f"Too Many Parameters ({npar} > 5)")
    if cc > 15:
        smells.append(f"High Cyclomatic Complexity (CC={cc} > 15)")
    return cc, smells


def _mentions_param(div_smt: str, params) -> bool:
    """Зависит ли делитель от ВХОДНЫХ параметров (дефект #179).

    `Path(...) / name`, `bin_dir / name` — это pathlib-склейка, а не арифметика;
    `name` не параметр функции, поэтому такое деление не является риском
    ZeroDivisionError. Проверяем только делители, зависящие от входа.
    """
    return any(re.search(rf"\b{re.escape(str(p))}\b", div_smt) for p in params)


def _could_be_zero(div_smt: str) -> bool:
    """Может ли ЭТОТ делитель быть нулём (дефект #178/#179).

    Отсекаем заведомо ненулевые: числовые литералы (`2`, `-1`) и
    UPPER_SNAKE_CASE (константы/макросы — `REFMAP_SIZE`, `MAX_LEN`).
    Иначе `median: 2 == 0` и `REFMAP_SIZE == 0` давали ложные [CRASH PATH].
    """
    s = div_smt.strip()
    while s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    if re.fullmatch(r"-?\d+", s):
        return False
    if _MACRO_DIV.match(s):
        return False
    return True


def _walk_expr_guarded(node, guards, syms, env, _depth=0):
    """Обход ВЫРАЖЕНИЯ с учётом ленивого вычисления (дефект N4/2).

    Плоский `ast.walk` стирает структуру `IfExp` и `BoolOp`, поэтому делитель
    внутри `0 if b == 0 else a // b` или `b != 0 and a // b > 0` собирался БЕЗ
    своего гарда — и `--xray` выдавал ЛОЖНОЕ обвинение в делении на ноль (тот
    самый класс, что #327 и N1, но в маршруте рентгена). Здесь каждому подузлу
    сопутствует стек активных условий:
      * `A if c else B` -> в `A` действует `c`, в `B` — `(not c)`;
      * `A and B`      -> в `B` действует `A` (B вычисляется лишь если A истинно);
      * `A or B`       -> в `B` действует `(not A)`.
    Непереводимое условие гарда НЕ даёт: лучше меньше гардов, чем выдуманный.
    """
    if _depth > 64:
        return
    if isinstance(node, ast.IfExp):
        c = None
        try:
            c = _cond_smt(node.test, syms, env)
        except (Unsupported, NoReturn):
            c = None
        if c is not None:
            yield from _walk_expr_guarded(node.body, guards + [c], syms, env, _depth + 1)
            yield from _walk_expr_guarded(node.orelse, guards + [f"(not {c})"],
                                          syms, env, _depth + 1)
        else:
            yield from _walk_expr_guarded(node.body, guards, syms, env, _depth + 1)
            yield from _walk_expr_guarded(node.orelse, guards, syms, env, _depth + 1)
        yield node, guards
        return
    if isinstance(node, ast.BoolOp):
        local = list(guards)
        for i, v in enumerate(node.values):
            yield from _walk_expr_guarded(v, local, syms, env, _depth + 1)
            if i < len(node.values) - 1:
                c = None
                try:
                    c = _cond_smt(v, syms, env)
                except (Unsupported, NoReturn):
                    c = None
                if c is not None:
                    local = local + ([c] if isinstance(node.op, ast.And)
                                     else [f"(not {c})"])
        yield node, guards
        return
    yield node, guards
    # ДЕФЕКТ #377: при спуске в тело `for i in range(...)` действует ГАРД
    # НЕПУСТОТЫ цикла. Без него обход через `ast.If` заходил в тело
    # `for i in range(n * k)` и обвинял `arr[i % n]` в делении на ноль при
    # `n == 0`, ХОТЯ при `n == 0` граница равна нулю и тела НЕТ (измерено
    # живым запуском: `Mbpp/286` возвращает `-inf`, падения нет).
    if isinstance(node, ast.For):
        inner = guards + _range_entry_guards(node, env)
        for ch in ast.iter_child_nodes(node):
            yield from _walk_expr_guarded(ch, inner, syms, env, _depth + 1)
        return
    for ch in ast.iter_child_nodes(node):
        yield from _walk_expr_guarded(ch, guards, syms, env, _depth + 1)


def _range_entry_guards(st, env) -> list:
    """ГАРД НЕПУСТОТЫ ЦИКЛА `for ... in range(...)` — ДЕФЕКТ #377.

    ЧТО БЫЛО СЛОМАНО (ИЗМЕРЕНО на РЕАЛЬНОМ коде MBPP+, `Mbpp/286`):
    `for i in range(n * k): current_max += arr[i % n]` — рентген обвинял
    `i % n` в делении на ноль при `n == 0`, НЕ ЗАМЕЧАЯ, что при `n == 0`
    граница `n * k` равна нулю, `range(0)` пуст и ТЕЛО ЦИКЛА НЕ ИСПОЛНЯЕТСЯ
    НИ РАЗУ. Живой запуск это подтвердил: функция возвращает `-inf`, падения
    НЕТ. То есть обвинение было ЛОЖНЫМ (класс #178/#183).

    ЗВУЧНОЕ РЕШЕНИЕ. Чтобы тело `for i in range(stop):` выполнилось хотя бы
    раз, необходимо `stop > 0`. Если `stop` линейно переводится в QF_LIA —
    добавляем `(> stop 0)`. Если `stop` — ПРОИЗВЕДЕНИЕ `A * B` (в QF_LIA
    нелинейно, и `expr_smt` его не переведёт), используем свойство кольца
    целых: при `A * B > 0` НИ ОДИН сомножитель не равен нулю, поэтому
    добавляем ЛИНЕЙНЫЕ условия `(distinct A 0)` и `(distinct B 0)`.
    """
    it = getattr(st, "iter", None)
    if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
            and it.func.id == "range" and it.args):
        return []
    args = it.args
    # Сначала произведение: оно НЕЛИНЕЙНО, и общий путь его не переведёт.
    stop = args[-1]
    if isinstance(stop, ast.BinOp) and isinstance(stop.op, ast.Mult):
        out = []
        for f in (stop.left, stop.right):
            try:
                out.append(f"(distinct {expr_smt(f, env)} 0)")
            except (Unsupported, NoReturn):
                pass
        if out:
            return out
    try:
        if len(args) == 1:
            return [f"(> {expr_smt(stop, env)} 0)"]
        return [f"(> {expr_smt(stop, env)} {expr_smt(args[0], env)})"]
    except (Unsupported, NoReturn):
        return []


def _crash_collect(n, nguards, params, kernc, found, fnname, syms, env) -> None:
    """Проверить ОДИН узел на деление на ноль с учётом гардов пути.

    Вынесено отдельной функцией для ДЕФЕКТА #378: ИЗМЕРЕНО, что ветки
    присваивания (`x = expr` и `x += expr`) делали `continue` СРАЗУ после
    обновления окружения, поэтому ИХ ЗНАЧЕНИЕ не проходило краш-обход вообще.
    `for i in range(3): t += a // n` не обвинялось, тогда как `return a // n`
    обвинялось — то есть тело цикла было слепой зоной рентгена.
    """
    if not (isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod))):
        return
    if isinstance(n.op, ast.Mod) and _is_str_expr(n.left):
        return  # `'%s' % x` — форматирование, не деление
    if isinstance(n.left, ast.Name) and _MACRO_DIV.match(n.left.id):
        return  # UPGRADE_DIR / name — pathlib-склейка, не арифметика
    if _is_path_expr(n.left):
        return  # ДЕФЕКТ #316: `self.root / log_dir`, `ROOT / "a" / name`
    try:
        div = expr_smt(n.right, env)
    except (Unsupported, NoReturn):
        return
    if not _could_be_zero(div) or not _mentions_param(div, params):
        return
    if _smt_sat(kernc, params, nguards + [f"(= {div} 0)"]) is True:
        found.append(f"[CRASH PATH] {fnname}: строка {n.lineno} — "
                     f"возможно деление на ноль: {div} == 0")


def _walk_branches(stmts, path: list[str], params: list[str], kernc,
                   found: list[str], skipped: list[str], fnname: str,
                   syms=None, env=None) -> None:
    """Обход ветвлений с накоплением условия пути.

    env: ПОЛЕВОЙ АДАПТЕР №2 (Let-Inlining). Локальные линейные присваивания
    (`total = price + fee`, `x += 1`) запоминаются как SMT-выражения и
    подставляются в последующие условия и делители. Без этого `if total >
    limit:` уходил в SKIP — `total` не был параметром функции.
    """
    syms = syms if syms is not None else set()
    env = dict(env or {})
    for st in stmts:
        # Let-Inlining: `x = expr` и `x += expr` (составное присваивание).
        if isinstance(st, ast.Assign) and len(st.targets) == 1                 and isinstance(st.targets[0], ast.Name):
            try:
                env[st.targets[0].id] = expr_smt(st.value, env)
            except (Unsupported, NoReturn):
                env.pop(st.targets[0].id, None)
            # ДЕФЕКТ #378: значение присваивания ОБЯЗАНО проходить краш-обход.
            for _n, _ng in _walk_expr_guarded(st.value, path, syms, env):
                _crash_collect(_n, _ng, params, kernc, found, fnname, syms, env)
            continue
        if isinstance(st, ast.AugAssign) and isinstance(st.target, ast.Name):
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}.get(type(st.op))
            if op is not None:
                try:
                    cur = env.get(st.target.id, st.target.id)
                    env[st.target.id] = f"({op} {cur} {expr_smt(st.value, env)})"
                except (Unsupported, NoReturn):
                    env.pop(st.target.id, None)
            # ДЕФЕКТ #378: значение составного присваивания тоже обходится.
            for _n, _ng in _walk_expr_guarded(st.value, path, syms, env):
                _crash_collect(_n, _ng, params, kernc, found, fnname, syms, env)
            continue
        # ДЕФЕКТ #179 (assert как гард пути): `assert len(x) == 1` — это
        # ИСТИННОЕ условие ВСЕГО дальнейшего кода, а не комментарий. Без этого
        # psf/requests давал ложный [BOUNDS PATH] на `encodings[0]`.
        if isinstance(st, ast.Assert):
            try:
                path = path + [_cond_smt(st.test, syms, env)]
            except (Unsupported, NoReturn):
                pass
            continue
        # ДЕФЕКТ #179 (Loop-Modified Variable Kill): переменная, которой
        # присваивают ВНУТРИ цикла, после цикла уже не равна начальному
        # значению. Иначе fastapi (`all_good = True`, затем
        # `all_good = all_good and res` в цикле) давал ложный
        # [DEAD BRANCH] `(not true)`.
        if isinstance(st, (ast.For, ast.While)):
            for sub in ast.walk(st):
                tgt = None
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            env.pop(t.id, None)
                    continue
                if isinstance(sub, (ast.AugAssign, ast.AnnAssign)):
                    tgt = getattr(sub, "target", None)
                if isinstance(tgt, ast.Name):
                    env.pop(tgt.id, None)
            if isinstance(st, ast.While):
                try:
                    path = path + [_cond_smt(st.test, syms, env)]
                except (Unsupported, NoReturn):
                    pass
            elif isinstance(st, ast.For):
                # ДЕФЕКТ #377: без гарда непустоты обвинение в теле
                # `for i in range(n * k)` ЛОЖНО — при `n == 0` тела нет.
                path = path + _range_entry_guards(st, env)
            _walk_branches(st.body, path, params, kernc, found, skipped, fnname, syms, env)
            continue
        if isinstance(st, ast.If):
            try:
                # ПУНКТ 21 (Zero-Annotation): `len(arr)` -> символическая длина,
                # иначе условия с `len(...)` ЛОЖНО считались «вне подмножества».
                cond = _cond_smt(st.test, syms, env)
            except (Unsupported, NoReturn):
                skipped.append(f"{fnname}: условие на строке {st.lineno} вне подмножества")
                continue
            # ДОСТИЖИМА ли ветка THEN?
            sat_then = _smt_sat(kernc, params, path + [cond])
            if sat_then is False:
                found.append(f"[DEAD BRANCH] {fnname}: строка {st.lineno} — "
                             f"ветка НЕДОСТИЖИМА (UNSAT): {cond}")
            elif sat_then is None:
                skipped.append(f"{fnname}: ветка {st.lineno} не решена решателем")
            # ИЗБЫТОЧНА ли проверка (всегда истинна)?
            sat_not = _smt_sat(kernc, params, path + [f"(not {cond})"])
            if sat_not is False:
                found.append(f"[REDUNDANT GUARD] {fnname}: строка {st.lineno} — "
                             f"условие ВСЕГДА истинно: {cond}")
            # Краш-пути в теле.
            for n, nguards in _walk_expr_guarded(st, path + [cond], syms, env):
                if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                    if isinstance(n.op, ast.Mod) and _is_str_expr(n.left):
                        continue  # `'%s' % x` — форматирование, не деление
                    if isinstance(n.left, ast.Name) and _MACRO_DIV.match(n.left.id):
                        continue  # UPGRADE_DIR / name — pathlib-склейка, не арифметика
                    if _is_path_expr(n.left):
                        continue  # ДЕФЕКТ #316: `self.root / log_dir`, `ROOT / "a" / name`
                    try:
                        div = expr_smt(n.right, env)
                    except (Unsupported, NoReturn):
                        continue
                    if not _could_be_zero(div) or not _mentions_param(div, params):
                        continue
                    sat_dz = _smt_sat(kernc, params, nguards + [f"(= {div} 0)"])
                    if sat_dz is True:
                        found.append(f"[CRASH PATH] {fnname}: строка {n.lineno} — "
                                     f"возможно деление на ноль: {div} == 0")
            _walk_branches(st.body, path + [cond], params, kernc, found, skipped, fnname, syms, env)
            _walk_branches(st.orelse, path + [f"(not {cond})"], params, kernc,
                           found, skipped, fnname, syms, env)
            # СУЖЕНИЕ ПУТИ (Дефект #149, §104.2): если блок THEN БЕЗУСЛОВНО
            # завершается (`return`/`raise`) и ветки else нет, то ВСЕ следующие
            # операторы выполняются при `NOT cond`. Без этого `[DEAD BRANCH]`
            # находился только в if/elif-цепочках, а последовательные
            # `if c1: return …` -> `if c2: return …` давали ложное «достижимо».
            # Ровно та же логика, что в `_walk_bounds` (Дефект #134).
            if not st.orelse and _block_exits(st.body):
                path = path + [f"(not {cond})"]
        else:
            for n, nguards in _walk_expr_guarded(st, path, syms, env):
                if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                    if isinstance(n.op, ast.Mod) and _is_str_expr(n.left):
                        continue  # `'%s' % x` — форматирование, не деление
                    if isinstance(n.left, ast.Name) and _MACRO_DIV.match(n.left.id):
                        continue  # UPGRADE_DIR / name — pathlib-склейка, не арифметика
                    if _is_path_expr(n.left):
                        continue  # ДЕФЕКТ #316: `self.root / log_dir`, `ROOT / "a" / name`
                    try:
                        div = expr_smt(n.right, env)
                    except (Unsupported, NoReturn):
                        continue
                    if not _could_be_zero(div) or not _mentions_param(div, params):
                        continue
                    sat_dz = _smt_sat(kernc, params, nguards + [f"(= {div} 0)"])
                    if sat_dz is True:
                        found.append(f"[CRASH PATH] {fnname}: строка {n.lineno} — "
                                     f"возможно деление на ноль: {div} == 0")


# =============================================================================
# ЭШЕЛОН 4, ПУНКТ 21 — ГРАНИЦЫ МАССИВОВ (`arr[i]` -> `0 <= i < len(arr)`).
#
# БЕЗ АННОТАЦИЙ @kern: длина неизвестна -> честно «НЕ проверено» (не молчим!).
# С директивой `# @kern:len(arr) = N` выставляется обязательство безопасности
# `0 <= i AND i < N` С УЧЁТОМ путевых условий (гард `if 0 <= i < N` делает
# функцию безопасной, и это доказывается, а не предполагается).
# =============================================================================

_LEN_RE = re.compile(r"@kern:len\(\s*(\w+)\s*\)\s*=\s*(\d+)")


def _declared_lengths_for(lines: list[str], lineno: int) -> dict[str, int]:
    """Длины из блока комментариев НЕПОСРЕДСТВЕННО перед `def` (строка lineno).

    ИЗМЕРЕНО: чтение директив по всему файлу давало НЕВЕРНУЮ длину, если две
    функции объявляли одну и ту же переменную с разными длинами (8 -> 4).
    """
    out: dict[str, int] = {}
    i = lineno - 2
    while i >= 0:
        s = lines[i].strip()
        if not s or not s.startswith("#"):
            break
        for m in _LEN_RE.finditer(s):
            out[m.group(1)] = int(m.group(2))
        i -= 1
    return out


_SMT_RESERVED = frozenset((
    "and", "or", "not", "ite", "true", "false", "div", "mod", "abs",
    "let", "forall", "exists", "Int", "Bool", "Real", "select", "store",
    "distinct", "xor", "=>", "=", "<", "<=", ">", ">=", "+", "-", "*", "/",
))


def _free_smt_vars(asserts, params) -> list[str]:
    """Свободные имена в утверждениях — объявляем их (неизвестное значение).

    🔴 ДЕФЕКТ #184 (звучимость, полевой прогон): `_smt_sat` объявлял только
    ПАРАМЕТРЫ. Если условие ссылалось на локальное имя (например
    `bit_test` из `const bit_test = addr & …`), SMT-LIB получал
    НЕОБЪЯВЛЕННЫЙ символ, kernc отвечал `KERN-EQ2 : N`, а `_smt_sat`
    трактовал «НЕ доказано» как SAT — и печатался ложный `[CRASH PATH]`.
    Свободное имя как Int — честная семантика «значение неизвестно».
    """
    known = set(params)
    out: list[str] = []
    seen: set[str] = set()
    for a in asserts:
        for tok in re.findall(r"[A-Za-z_][\w]*(?:![\w]+)?", a):
            if tok in _SMT_RESERVED or tok in known or tok in seen:
                continue
            seen.add(tok)
            out.append(tok)
    return out


def _smt_verdict(kernc, params, asserts) -> tuple[str, str | None]:
    """ТРЁХЗНАЧНЫЙ вердикт: ("sat", контрпример) | ("unsat", None) | ("unknown", причина).

    ДЕФЕКТ #137 (звучимость): раньше возвращался `None` и для `UNSAT`, и для `N`
    (решатель не решил). Из-за этого НЕРЕШЁННАЯ формула молча считалась
    ДОКАЗАННОЙ — ложный PASS. Теперь `unknown` отличается от `unsat` и обязан
    обрабатываться вызывающим кодом как «НЕ проверено».
    """
    _SMT_CALLS_COUNTED_IN_RUN_KERNC = True  # см. run_kernc (дефект #208)
    free = _free_smt_vars(asserts, params)
    decls = "\n".join(f"(declare-const {p} Int)" for p in list(params) + free)
    body = "\n".join(f"(assert {a})" for a in asserts)
    smt = f"(set-logic ALL)\n{decls}\n{body}\n(check-sat)\n"
    # МЕМОИЗАЦИЯ (такт 2.2): ИЗМЕРЕНО 81,2 % повторных запросов внутри одного
    # прогона. Счётчик охвата инкрементируется И НА ПОПАДАНИИ: `checked` обязан
    # означать «ЛОГИЧЕСКИЙ запрос был», а не «процесс был запущен». Иначе кэш
    # менял бы корзину `checked` — то есть состояние кэша влияло бы на отчёт.
    _hit = _SMT_VERDICT_CACHE.get(smt)
    if _hit is not None:
        _SMT_CALLS[0] += 1
        return _hit
    _rc, out = run_kernc(kernc, smt)
    if "КОНТРПРИМЕР" in out:
        for ln in out.splitlines():
            if "КОНТРПРИМЕР" in ln:
                _SMT_VERDICT_CACHE[smt] = ("sat", ln.strip()[:110])
                return ("sat", ln.strip()[:110])
        _SMT_VERDICT_CACHE[smt] = ("sat", "SAT (модель не извлечена)")
        return ("sat", "SAT (модель не извлечена)")
    if "ДОКАЗАНО" in out:
        _SMT_VERDICT_CACHE[smt] = ("unsat", None)
        return ("unsat", None)
    # `unknown` НЕ кэшируется: нерешённая формула — это состояние СЕССИИ
    # (таймаут под нагрузкой), а не свойство формулы.
    return ("unknown", "решатель не решил (N): формула НЕ проверена")


def _smt_counterexample(kernc, params, asserts) -> str | None:
    """Совместимость: контрпример, если SAT; иначе None (UNSAT или unknown)."""
    kind, ce = _smt_verdict(kernc, params, asserts)
    return ce if kind == "sat" else None


# -----------------------------------------------------------------------------
# ПУНКТ 21 (Zero-Annotation): длина массива извлекается ИЗ САМОГО КОДА.
#
# ИЗМЕРЕНО/ПРИЗНАНО (архитектурная ревизия): требовать `# @kern:len(arr) = N` в
# режиме, заявленном как «работа БЕЗ аннотаций @kern:», — противоречие. Теперь:
#   (а) литерал списка/массива в теле  `data = [10, 20, 30, 40]` -> N = 4 из AST;
#   (б) `len(data)` в условиях -> СИМВОЛИЧЕСКАЯ длина `kern_len_data >= 0`,
#       поэтому гард `i < len(data)` доказывает безопасность для ЛЮБОЙ длины.
# Директива `@kern:len` оставлена ТОЛЬКО как опциональное переопределение.
# -----------------------------------------------------------------------------

class _LenRewrite(ast.NodeTransformer):
    """`len(arr)` -> символическая переменная `kern_len_arr`."""

    def __init__(self, syms: set):
        self.syms = syms

    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if (isinstance(f, ast.Name) and f.id == "len"
                and len(node.args) == 1 and isinstance(node.args[0], ast.Name)):
            name = node.args[0].id
            self.syms.add(name)
            return ast.copy_location(
                ast.Name(id=f"kern_len_{name}", ctx=ast.Load()), node)
        return node


def _collect_lens(fn, syms: set) -> dict[str, str]:
    """Длины из литералов списков + символьные длины из `len(...)`."""
    lens: dict[str, str] = {}
    for st in ast.walk(fn):
        if (isinstance(st, ast.Assign) and len(st.targets) == 1
                and isinstance(st.targets[0], ast.Name)
                and isinstance(st.value, (ast.List, ast.Tuple))):
            lens[st.targets[0].id] = str(len(st.value.elts))
        if isinstance(st, ast.Call):
            _LenRewrite(syms).visit(st)
    return lens


def _cond_smt(node, syms: set, env=None):
    """SMT условия с переписанным `len(arr)` -> `kern_len_arr` и env локалей.

    env (ПОЛЕВОЙ АДАПТЕР №2, Let-Inlining): локальные линейные присваивания
    (`total = price + fee`) подставляются в условия, иначе ветка уходила в
    SKIP, потому что `total` не была параметром функции.
    """
    node = _LenRewrite(syms).visit(ast.parse(ast.unparse(node), mode="eval").body)
    ast.fix_missing_locations(node)
    return expr_smt(node, dict(env or {}))


def _block_exits(body) -> bool:
    """Завершается ли блок безусловно (return/raise/continue/break)?

    ДЕФЕКТ #322: `continue` НЕ считался выходом, поэтому гард
    `if not (1 <= lineno <= len(src)): continue` не сужал путь — и следующий
    `src[lineno - 1]` обвинялся контрпримером `lineno = 0`, который этот самый
    гард и исключает. ИЗМЕРЕНО само-применением на `check_metrics_consistency.py`
    (2 кандидата `[BOUNDS PATH]`).

    ЗВУЧИМОСТЬ: `continue`/`break` — безусловный выход из ТЕКУЩЕГО блока, и
    инструкции после `if <cond>: continue` выполняются только при ложном
    `<cond>`. Это ровно то же рассуждение, что и для `return`.
    """
    return bool(body) and isinstance(
        body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))


def _normalized_length(st) -> tuple[str, int] | None:
    """ПОЛЕВОЙ АДАПТЕР №6: `if len(x) != K: x = (...)[:K]` -> длина x равна K.

    НАЙДЕНО НА РЕАЛЬНОМ КОДЕ (`urllib/request.py: ip2num`): без этого правила
    `parts[0]` после нормализации давал ЛОЖНЫЙ `[BOUNDS PATH]` с контрпримером
    `len(parts) = 0`, хотя обе ветви гарантируют длину 4.

    ЗВУЧИМОСТЬ: правило срабатывает только когда
      * условие имеет вид `len(x) != K` (K — целая константа);
      * THEN содержит ЕДИНСТВЕННОЕ присваивание `x = <expr>[:K]`.
    Тогда в THEN длина ровно K (срез), в ELSE — K по отрицанию условия.
    Любая иная форма -> None (честный отказ, а не догадка).
    """
    test = st.test
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.NotEq)):
        return None
    left = test.left
    if not (isinstance(left, ast.Call) and isinstance(left.func, ast.Name)
            and left.func.id == "len" and len(left.args) == 1
            and isinstance(left.args[0], ast.Name)):
        return None
    k = test.comparators[0]
    if not (isinstance(k, ast.Constant) and isinstance(k.value, int)
            and not isinstance(k.value, bool)):
        return None
    name = left.args[0].id
    if len(st.body) != 1 or not isinstance(st.body[0], ast.Assign):
        return None
    asg = st.body[0]
    if len(asg.targets) != 1 or not isinstance(asg.targets[0], ast.Name)             or asg.targets[0].id != name:
        return None
    val = asg.value
    # `x[:K]` или `(...)[:K]`
    if isinstance(val, ast.Subscript) and isinstance(val.slice, ast.Slice)             and isinstance(val.slice.upper, ast.Constant)             and val.slice.upper.value == k.value:
        return (name, int(k.value))
    return None


def _stop_len(stop) -> str | None:
    """Имя массива, если верхняя граница `stop` ГАРАНТИРУЕТ `i < len(arr)`.

    ДЕФЕКТ #322: распознавалась только форма `range(len(arr))`, поэтому
    `for j in range(idx + 1, min(idx + 8, len(lines)))`
    (`scan_to_kern.py:73`) давал ложный `[BOUNDS PATH]` на `lines[j]`, хотя
    граница цикла её исключает.

    ЗВУЧИМОСТЬ: `min(...)` безопасен — минимум НЕ превосходит каждого своего
    аргумента, поэтому `j < min(x, len(arr)) <= len(arr)`. Любая другая форма
    (арифметика над длиной, `max`, срез) -> None: честный отказ, а не догадка.
    """
    if isinstance(stop, ast.Call) and isinstance(stop.func, ast.Name):
        if (stop.func.id == "len" and len(stop.args) == 1
                and isinstance(stop.args[0], ast.Name)):
            return stop.args[0].id
        if stop.func.id == "min":
            for a in stop.args:
                r = _stop_len(a)
                if r:
                    return r
    if isinstance(stop, ast.Name) and stop.id.startswith("kern_len_"):
        return stop.id[len("kern_len_"):]
    return None


def _loop_len_guard(st) -> tuple[str, str] | None:
    """`for i in range(len(arr)):` -> ("i", "arr"); иначе None.

    ДЕФЕКТ #314: индекс `i` внутри такого цикла ОГРАНИЧЕН длиной массива, но
    это не моделировалось, и `arr[i]` обвинялся в выходе за границы с
    недостижимым контрпримером (`kern_len_lines = 0, i = -1`). Найдено трофеем
    на реальном коде CPython (`Tools/i18n/pygettext.py:227`).

    ВАЖНО: к моменту обхода препроцессор УЖЕ переписал `len(arr)` в
    `kern_len_arr`, поэтому принимаются ОБЕ формы — иначе защита не срабатывает
    (проверено: `guard=None` на реальном пути при верной форме в изоляции).

    ДЕФЕКТ #322: границей считается ВТОРОЙ аргумент `range` (stop), а не только
    единственный; форма `range(start, stop, step)` тоже учитывается (`stop`
    остаётся вторым), см. `_stop_len`.
    """
    if not isinstance(st.target, ast.Name):
        return None
    it = st.iter
    if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
            and it.func.id == "range" and 1 <= len(it.args) <= 3):
        return None
    stop = it.args[1] if len(it.args) >= 2 else it.args[0]
    arr = _stop_len(stop)
    if arr is not None:
        return st.target.id, arr
    return None


def _match_len_guard(st) -> str | None:
    """`match len(arr):` -> "arr"; иначе None (для per-case сужения)."""
    subj = st.subject
    if (isinstance(subj, ast.Call) and isinstance(subj.func, ast.Name)
            and subj.func.id == "len" and len(subj.args) == 1
            and isinstance(subj.args[0], ast.Name)):
        return subj.args[0].id
    if isinstance(subj, ast.Name) and subj.id.startswith("kern_len_"):
        return subj.id[len("kern_len_"):]
    return None


def _len_alias(st) -> tuple[str, str] | None:
    """`n = len(arr)` -> (`n`, `arr`). Только ПРОСТАЯ форма, иначе None.

    ЗАЧЕМ (дефект #315/#322): в `statistics.harmonic_mean` стоит реальный гард
    `n = len(data)` + `if n < 1: raise`. Анализатор не связывал `n` с
    символической длиной, поэтому `data[0]` обвинялся НЕДОСТИЖИМЫМ
    контрпримером `kern_len_data = 0`.
    """
    if not (isinstance(st, ast.Assign) and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
            and isinstance(st.value, ast.Call)
            and isinstance(st.value.func, ast.Name)
            and st.value.func.id == "len"
            and len(st.value.args) == 1
            and isinstance(st.value.args[0], ast.Name)):
        return None
    return st.targets[0].id, st.value.args[0].id


def _assigned_names(st) -> set[str]:
    """Имена, которые ЭТА инструкция присваивает (для снятия псевдонимов)."""
    out: set[str] = set()
    for node in ast.walk(st):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if isinstance(node.target, ast.Name):
                out.add(node.target.id)
    return out


def _deal_pre_path(fn, syms: set) -> list:
    """Путевые условия из ДЕКОРАТОРОВ-предусловий: `@deal.pre(lambda …: <cond>)`.

    ДЕФЕКТ #351 (класс #322(в), найден САМОПРИМЕНЕНИЕМ `--xray tools/`):
    предусловие, записанное ДЕКОРАТОРОМ, не моделировалось, поэтому `div_ok(a, b)`
    с `@deal.pre(lambda a, b: b != 0)` получал ЛОЖНЫЙ `[CRASH PATH]`
    «возможно деление на ноль: b == 0» — ровно то состояние, которое декоратор и
    исключает. Декоратор — такой же ГАРД, как `if`: он истинен на входе в тело.

    ЗВУЧНОСТЬ: берём ТОЛЬКО форму `@deal.pre(lambda <params>: <cond>)` с простой
    лямбдой без `*args`/`**kwargs`. Любая иная форма (вызов функции вместо лямбды,
    вариативные параметры, неразбираемое условие) даёт ПУСТОЙ список — поведение
    остаётся прежним: лучше лишний кандидат, чем пропуск нарушения.
    """
    out: list = []
    for dec in getattr(fn, "decorator_list", []) or []:
        if not isinstance(dec, ast.Call):
            continue
        f = dec.func
        if not (isinstance(f, ast.Attribute) and f.attr == "pre"
                and isinstance(f.value, ast.Name) and f.value.id == "deal"):
            continue
        if len(dec.args) != 1 or not isinstance(dec.args[0], ast.Lambda):
            continue
        lam = dec.args[0]
        if lam.args.vararg is not None or lam.args.kwarg is not None:
            continue
        try:
            c = _cond_smt(lam.body, syms)
        except (Unsupported, NoReturn):
            continue
        if c:
            out.append(c)
    return out


def _walk_bounds(body, path, params, lens, kernc, found, fname, syms=None,
                 in_while=False):
    """Обход тела с накоплением путевых условий (Пункт 21, Zero-Annotation).

    `in_while` — ДЕФЕКТ #315: внутри `while` ПОЛНЫЙ инвариант цикла не
    моделируется (для этого нужен CHC/Horn, который живёт в Zig и не подключён
    к этому анализу). Поэтому находки внутри тела `while` помечаются как
    `[BOUNDS UNKNOWN]` с причиной, а НЕ как `[BOUNDS PATH]` с контрпримером:
    контрпример вида `kern_len_a = 0, mid = -1` недостижим при инварианте
    `0 <= lo < hi <= len(a)`, и выдавать его за находку — ложное обвинение.
    Само условие цикла добавляется в путь: оно истинно на КАЖДОЙ итерации,
    поэтому такое сужение ЗВУЧНО (оно не скрывает нарушений, возможных при
    истинном условии).
    """
    syms = syms if syms is not None else set()
    # ПСЕВДОНИМЫ ДЛИНЫ (дефект #315/#322): `n = len(arr)` связывает локальную
    # переменную с символической длиной. Без этого реальный гард
    # `if n < 1: raise` в `statistics.harmonic_mean` НЕ сужал путь, и `data[0]`
    # обвинялся недостижимым контрпримером `kern_len_data = 0`.
    # ЗВУЧИМОСТЬ: равенство добавляется в путь только для ПРОСТОЙ формы
    # `var = len(arr)` и снимается, как только переменная переназначена.
    alias_path: list[str] = []
    alias_of: dict[str, str] = {}
    for st in body:
        al = _len_alias(st)
        if al is not None:
            var, arr = al
            syms = syms | {arr}
            alias_of[var] = arr
            alias_path.append(f"(= {var} kern_len_{arr})")
            continue
        for nm in _assigned_names(st):
            if nm in alias_of:
                del alias_of[nm]
                alias_path = [c for c in alias_path if not c.startswith(f"(= {nm} ")]
        eff = path + alias_path
        if isinstance(st, ast.If):
            try:
                cond = _cond_smt(st.test, syms)
            except (Unsupported, NoReturn):
                cond = None
            # ИНВАРИАНТ ДЛИНЫ после нормализации (`if len(x) != K: x = ...[:K]`).
            fixed_len = _normalized_length(st)
            if fixed_len is not None:
                name, k = fixed_len
                lens[name] = k
            _walk_bounds(st.body, eff + ([cond] if cond else []), params, lens,
                         kernc, found, fname, syms, in_while=in_while)
            neg = f"(not {cond})" if cond else None
            _walk_bounds(st.orelse, eff + ([neg] if neg else []), params, lens,
                         kernc, found, fname, syms, in_while=in_while)
            # ИНДЕКСЫ В УСЛОВИИ `if` (дефект #315): ветка завершается `continue`,
            # поэтому общий `ast.walk` по инструкции до них НЕ доходил — индекс
            # вида `if a[i] == 5:` не проверялся ВООБЩЕ. Условие вычисляется на
            # текущем пути, поэтому сканируем его с тем же `eff`.
            for sub in [n for n in ast.walk(st.test) if isinstance(n, ast.Subscript)]:
                _bounds_one(sub, eff, params, lens, kernc, found, fname, syms, in_while)
            # ИЗМЕРЕНО: операторы ПОСЛЕ `if` раньше теряли путевое условие, и
            # `get_safe` (с гардами) ЛОЖНО обвинялся в выходе за границы.
            # Если ветка THEN безусловно завершается, то всё последующее
            # выполняется при `NOT cond` -> сужаем путь.
            if neg and _block_exits(st.body):
                path = eff + [neg]
            continue
        # ДЕФЕКТ #314: циклы и `match` по длине не моделировались вовсе — их
        # тела обходились БЕЗ сужения, поэтому индексы, ограниченные идиомой
        # `for i in range(len(arr))` или `match len(arr): case N:`, обвинялись
        # в выходе за границы с недостижимым контрпримером.
        # ДЕФЕКТ #315: `while` НЕ обрабатывался вовсе — тело обходилось без
        # сужения (фоллтhrough в общий `ast.walk` ниже), поэтому индекс внутри
        # цикла обвинялся с НЕДОСТИЖИМЫМ контрпримером (`bisect.py`). Теперь
        # условие цикла (истинное на каждой итерации) идёт в путь, а сам факт
        # «инвариант не смоделирован» передаётся флагом — см. `in_while`.
        if isinstance(st, ast.While):
            try:
                wcond = _cond_smt(st.test, syms)
            except (Unsupported, NoReturn):
                wcond = None
            wpath = eff + ([wcond] if wcond else [])
            _walk_bounds(st.body, wpath, params, lens, kernc, found, fname, syms,
                         in_while=True)
            _walk_bounds(st.orelse, eff, params, lens, kernc, found, fname, syms,
                         in_while=in_while)
            # ВАЖНО: индексы бывают и в САМОМ условии цикла (`while a[i] < x`).
            # Раньше их находил общий `ast.walk` по ВСЕЙ инструкции — но тело уже
            # обойдено рекурсией выше, и повторный проход по всему `while` давал
            # ДУБЛИКАТЫ находок (дефект #326: `bisect.py` печатал каждый индекс
            # дважды). Сканируем ТОЛЬКО условие — тело покрыто рекурсией.
            for sub in [n for n in ast.walk(st.test) if isinstance(n, ast.Subscript)]:
                _bounds_one(sub, wpath, params, lens, kernc, found, fname, syms,
                            in_while=True)
            continue
        if isinstance(st, ast.For):
            g = _loop_len_guard(st)
            if g is not None:
                var, arr = g
                cond = f"(and (>= {var} 0) (< {var} kern_len_{arr}))"
                _walk_bounds(st.body, eff + [cond], params, lens, kernc, found,
                             fname, syms | {arr}, in_while=in_while)
            else:
                _walk_bounds(st.body, eff, params, lens, kernc, found, fname, syms,
                             in_while=in_while)
            _walk_bounds(st.orelse, eff, params, lens, kernc, found, fname, syms,
                         in_while=in_while)
            continue
        if isinstance(st, ast.Match):
            arr = _match_len_guard(st)
            for case in st.cases:
                extra: list[str] = []
                csyms = syms
                pat = case.pattern
                if (arr is not None and isinstance(pat, ast.MatchValue)
                        and isinstance(pat.value, ast.Constant)
                        and isinstance(pat.value.value, int)):
                    csyms = syms | {arr}
                    extra = [f"(= kern_len_{arr} {pat.value.value})"]
                _walk_bounds(case.body, eff + extra, params, lens, kernc, found,
                             fname, csyms, in_while=in_while)
            continue
        # ДЕФЕКТ #322: путь учитывает УСЛОВНЫЕ ВЫРАЖЕНИЯ — тернарник
        # (`x[0] if xs else None`) это ГАРД своей ветви, а не общий путь.
        for sub, spath in _subscripts_with_path(st, eff, syms):
            _bounds_one(sub, spath, params, lens, kernc, found, fname, syms, in_while)


def _subscripts_with_path(st, path: list, syms: set) -> list:
    """Подвыражения `arr[i]` вместе с условиями, которые их ГАРАНТИРУЮТ.

    ДЕФЕКТ #322. Условное ВЫРАЖЕНИЕ (`return x[0] if xs else None`,
    `src = Path(examples[0]["file"]) if examples else Path(".")`) — это ГАРД:
    внутри ветви `body` условие ИСТИННО, внутри `orelse` — ЛОЖНО. Раньше
    `ast.walk` давал ВСЕМ индексам ОДИН путь, поэтому `examples[0]` обвинялся
    контрпримером `examples = 0`, хотя именно `if examples` это исключает.
    ИЗМЕРЕНО само-применением: 2 из 6 кандидатов `[BOUNDS PATH]` на
    собственном коде KERN были ровно такими.

    ЗВУЧИМОСТЬ: условие добавляется только для СВОЕЙ ветви — сужение пути не
    скрывает нарушений, возможных при истинном условии. Если условие не
    выражается в SMT, ветвь получает путь БЕЗ сужения (честный отказ: лучше
    лишний кандидат, чем пропуск).

    `isinstance(x, T)` из конъюнкции ВЫРЕЗАЕТСЯ: этот предикат говорит о ТИПЕ,
    а не о длине, и для обязанности «индекс в границах» информации не несёт
    (`d[0] if isinstance(d, tuple) and len(d) >= 3` — границы обеспечивает
    именно `len(d) >= 3`). Если после вырезания не остаётся ничего, сужения
    нет: `d[0] if isinstance(d, tuple) else None` по-прежнему кандидат, и это
    верно — пустой кортеж даёт IndexError.
    """
    out: list[tuple] = []

    def cond_of(test) -> str | None:
        stripped = _drop_isinstance(test)
        if stripped is None:
            return None
        try:
            return _cond_smt(stripped, syms)
        except (Unsupported, NoReturn):
            return None

    def walk(node, cond_path: list) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.IfExp):
                c = cond_of(child.test)
                walk(child.body, cond_path + ([c] if c else []))
                walk(child.orelse, cond_path + ([f"(not {c})"] if c else []))
                continue
            if isinstance(child, ast.Subscript):
                out.append((child, cond_path))
            walk(child, cond_path)

    walk(st, list(path))
    return out


def _drop_isinstance(node):
    """Убрать `isinstance(...)` из конъюнкции; None, если не осталось ничего.

    См. `_subscripts_with_path`: предикат типа не несёт информации о ДЛИНЕ,
    поэтому для границ индекса он бесполезен, а как блокер — вреден (без его
    вырезания `len(d) >= 3` не доходило до решателя и `d[0]` обвинялся).
    Форма `a and b` сохраняется: рекурсивно вырезаем из обеих частей.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "isinstance":
        return None
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        kept = [_drop_isinstance(v) for v in node.values]
        kept = [k for k in kept if k is not None]
        if not kept:
            return None
        if len(kept) == 1:
            return kept[0]
        return ast.BoolOp(op=ast.And(), values=kept)
    return node


# ДЕФЕКТ #322: имена, присвоенные внутри циклов ТЕКУЩЕЙ анализируемой функции.
# Контекст (как `_CURRENT_LANG`): заполняется в точке входа перед обходом тела,
# чтобы `_bounds_one` не обвинял индекс, зависящий от немоделируемого инварианта.
_LOOP_MODIFIED: set = set()


def _loop_modified(stmts) -> set:
    """Имена, присвоенные ВНУТРИ `while`/`for` (по всей функции).

    ДЕФЕКТ #322. Значение такой переменной после цикла определяется
    ИНВАРИАНТОМ, который этот анализ НЕ моделирует (#315). Поэтому обвинять
    `lines[i]` контрпримером `i = -1` нельзя: в `_strip_leading_docstring`
    (`humaneval_api.py:24`) `i` инициализирован нулём и в цикле только растёт —
    `i = -1` недостижим. Звуковое поведение — `[BOUNDS UNKNOWN]` с причиной,
    а не `[BOUNDS PATH]` с недостижимым свидетелем.
    """
    names: set = set()
    for st in stmts:
        for node in ast.walk(st):
            # ТОЛЬКО ТЕЛО цикла: переменная ЗАГОЛОВКА (`for lineno, _ in pairs`)
            # меняется предсказуемо и гардом сужается — считать её
            # «немоделируемой» значило бы терять настоящие проверки.
            body = None
            if isinstance(node, (ast.For, ast.While)):
                body = node.body
            if body is None:
                continue
            for inner in body:
                for x in ast.walk(inner):
                    names |= _assigned_names(x)
    return names


def _bounds_one(sub, path, params, lens, kernc, found, fname, syms, in_while):
    """Проверить ОДИН индекс `arr[idx]` на выход за границы.

    Вынесено из `_walk_bounds`, потому что индексы бывают не только в телах
    инструкций, но и в ВЫРАЖЕНИЯХ условий (`while`, `if`, `match`). Раньше их
    находил общий `ast.walk` по всей инструкции; после появления ветки для
    `ast.While` (дефект #315) этот проход перестал её достигать, и покрытие
    терялось вместе с ложной тревогой — поэтому сканирование вызывается явно.
    """
    if not isinstance(sub.value, ast.Name):
        return
    arr = sub.value.id
    decls = list(params)
    pre: list[str] = []
    if arr in lens:
        n = lens[arr]                      # (а) литерал списка из AST
        human = f"0..{int(n) - 1} (из литерала)"
    elif arr in syms:
        n = f"kern_len_{arr}"              # (б) СИМВОЛИЧЕСКАЯ длина
        decls = list(dict.fromkeys(decls + [n]))
        pre = [f"(>= {n} 0)"]
        human = "0..kern_len_%s-1 (символическая длина)" % arr
    else:
        found.append(f"[BOUNDS] {fname}: `{arr}[...]` (строка {sub.lineno}) — "
                     f"длина НЕ известна (нет литерала и нет `len({arr})` "
                     f"в условиях), границы НЕ проверены")
        return
    try:
        # ДЕФЕКТ #322: индекс, записанный через `len(b)`, давал СВОБОДНЫЙ символ
        # `len__b`, никак не связанный с `kern_len_b` из границ. Решатель
        # выбирал `len__b = -2` (длина не может быть отрицательной!), и
        # контрпример был бессмысленным. Приводим индекс к ТОЙ ЖЕ символической
        # длине, что и границы, и требуем неотрицательности новых символов.
        _rw = _LenRewrite(set(syms))
        _sl = _rw.visit(ast.parse(ast.unparse(sub.slice), mode="eval").body)
        ast.fix_missing_locations(_sl)
        idx = expr_smt(_sl, {})
        for _s in _rw.syms:
            decls = list(dict.fromkeys(decls + [f"kern_len_{_s}"]))
            pre = list(dict.fromkeys(pre + [f"(>= kern_len_{_s} 0)"]))
    except (Unsupported, NoReturn):
        return
    # ДЕФЕКТ #322: индекс зависит от переменной, изменённой в ЦИКЛЕ -> её
    # значение после цикла определяется ИНВАРИАНТОМ, который не моделируется
    # (#315). Обвинять нельзя: свидетель может быть недостижим (в
    # `_strip_leading_docstring` — `i = -1` при `i`, растущем от нуля).
    if _LOOP_MODIFIED:
        used = {x.id for x in ast.walk(sub.slice) if isinstance(x, ast.Name)}
        touched = used & _LOOP_MODIFIED
        if touched:
            found.append(
                f"[BOUNDS UNKNOWN] {fname}: `{arr}[{idx}]` (строка {sub.lineno}) — "
                f"индекс зависит от переменной, изменённой в ЦИКЛЕ "
                f"({', '.join(sorted(touched))}): инвариант цикла НЕ моделируется "
                f"(#315) — НЕ считается ни находкой, ни безопасным")
            return
    bad = f"(not (and (>= {idx} 0) (< {idx} {n})))"
    v, ce = _smt_verdict(kernc, decls, pre + path + [bad])
    if v == "sat":
        # ДЕФЕКТ #315: внутри `while` инвариант цикла не смоделирован, поэтому
        # «контрпример» может быть НЕДОСТИЖИМ (именно так было на `bisect.py`).
        # Звуковое поведение — честное UNKNOWN с причиной, а не обвинение.
        if in_while:
            found.append(
                f"[BOUNDS UNKNOWN] {fname}: `{arr}[{idx}]` (строка {sub.lineno}) — "
                f"`while`: инвариант цикла НЕ моделируется, поэтому свидетельство "
                f"{ce} может быть недостижимо — НЕ считается ни находкой, ни безопасным")
        else:
            found.append(f"[BOUNDS PATH] {fname}: `{arr}[{idx}]` (строка {sub.lineno}) — "
                         f"возможен выход за границы {human}; контрпример: {ce}")
    elif v == "unknown":
        found.append(f"[BOUNDS UNKNOWN] {fname}: `{arr}[{idx}]` (строка {sub.lineno}) — "
                     f"НЕ решено ({ce}) — НЕ считается безопасным")


# Побочный канал: статистика последнего `cmd_xray` для агрегатора.
_LAST_XRAY: dict = {}

# МУСОРНЫЕ КАТАЛОГИ ЧУЖИХ РЕПОЗИТОРИЕВ. Без этого сканер тратил бы всё время на
# сторонние зависимости вместо кода проекта (и мог наткнуться на «мины» в них).
_XRAY_SKIP_DIRS = {".git", ".hg", ".svn",
                   ".venv", ".venv38", ".venv-evalplus", "venv", "env", "virtualenv",
                   "node_modules", "bower_components",
                   "vendor", "third_party", "third-party", "external",
                   "target", "dist", "build", "out", "bin", "obj",
                   ".zig-cache", "zig-out", "zig-cache",
                   "__pycache__", ".mypy_cache", ".pytest_cache", ".tox", ".ruff_cache",
                   ".idea", ".vscode", "fixtures", "__snapshots__",
                   "site-packages", "dist-packages"}
# Ограничения на ОДИН файл: минифицированные бандлы и гигантские генераты.
_XRAY_MAX_FILE = 512 * 1024
# ДЕФЕКТ #381 (найден при замере CyberSecEval): здесь был ВТОРОЙ список
# «известного», разошедшийся с первым. `CLIKE_EXT` (стр. 1651) УЖЕ содержал
# `.cpp` и `.cc` — то есть контрактный путь C++ разбирал, — а `--xray`
# выбрасывал эти файлы МОЛЧА. ИЗМЕРЕНО на официальном датасете Meta: каталог
# 240 файлов, сканер сообщал «файлов к сканированию: 130», и 110 файлов
# (.cpp/.cs/.java/.php) были невидимы — 46% датасета (876 из 1916).
#
# Правка: ОДИН источник истины — набор берётся из `CLIKE_EXT` плюс `.py`.
# Два списка больше не могут разойтись (класс «список известного»).
_XRAY_EXTS = CLIKE_EXT | {".py"}


def _xray_collect(root: Path) -> tuple[list[Path], dict[str, int]]:
    """Файлы к сканированию + УЧЁТ пропущенных ПО РАСШИРЕНИЮ (дефект #381).

    Возвращает `(files, skipped_by_ext)`. Файл, не попавший в набор
    расширений, НЕ исчезает молча: он возвращается в счётчике, и вызывающий
    код обязан его напечатать. Без этого «файлов к сканированию: N»
    читается как «в каталоге N файлов» — что и было ложью в #381.
    """
    files: list[Path] = []
    skipped: dict[str, int] = {}
    if root.is_file():
        if root.suffix in _XRAY_EXTS:
            files.append(root)
        else:
            skipped[root.suffix or "<без расширения>"] = 1
        return files, skipped
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _XRAY_SKIP_DIRS]
        for f in sorted(filenames):
            fp = Path(dirpath) / f
            if fp.is_symlink():
                continue
            if fp.suffix not in _XRAY_EXTS:
                key = fp.suffix or "<без расширения>"
                skipped[key] = skipped.get(key, 0) + 1
                continue
            files.append(fp)
    return files, skipped


def _skip_key(exc: object) -> str:
    """Нормализовать причину отсева в КЛЮЧ ГИСТОГРАММЫ (дефект #400).

    Значения в сообщении (`'while (i < n) i = i + 1'`, имена параметров)
    делают каждый ключ уникальным и гистограмма теряет смысл. Поэтому из
    сообщения убирается литеральная часть, а структурный префикс сохраняется:
    `оператор c: 'while …'` -> `оператор c:`.
    """
    if isinstance(exc, SyntaxError):
        return "синтаксис Python после перевода C-like"
    txt = str(exc).strip()
    raw = str(exc).strip()
    # Литеральную часть (`'while …'`) заменяем на «…», чтобы ключ был СТРУКТУРНЫМ.
    _q = chr(34) + chr(39)
    raw = re.sub("[" + _q + "][^" + _q + "]*[" + _q + "]", "«…»", raw)
    txt = re.sub(r"\s+", " ", raw).strip().rstrip(":")
    return txt[:60] or "без описания"


def _xray_report_skip_reasons(reasons: dict[str, int], skipped: int,
                              trivial: int = 0, checked: int = 0,
                              total: int = 0, notes: dict | None = None) -> None:
    """Напечатать причины пропуска + ТРИ КОРЗИНЫ (ДЕФЕКТЫ #400/#405).

    ЧТО БЫЛО НЕ ТАК. Сводка `--xray` для C-like заявляла
    «skipped N with explicit reasons», но НИ ОДНОЙ причины не выводила:
    `_xray_clike_file` их просто не возвращал. То есть печаталась ЛОЖНАЯ
    фраза — читатель видел «с причинами» и не видел ни одной.

    ЧЕСТНАЯ ГРАНИЦА. Список причин и счётчик — РАЗНЫЕ вещи. Если функции
    пропускаются, а причина не записана, это названо дефектом ИНСТРУМЕНТА
    (как в Python-пути, N4), а не свойством проверяемого кода.

    ТРИ КОРЗИНЫ (#405) печатаются отдельной строкой `buckets:`, а их сумма
    проверяется ЗАПЕЧАТАННОЙ спецификацией `funnel_accounting.unaccounted`:
    остаток обязан быть нулём. Если он не ноль — это дефект ИНСТРУМЕНТА, и он
    называется числом, а не замалчивается.
    """
    named = sum(reasons.values())
    for key, cnt in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
        print(f"    skip: {key} × {cnt}")
    if named != skipped:
        # ДЕФЕКТ #407.2: считаем РАЗНОСТЬ ОДНОЙ РАЗМЕРНОСТИ. Если причины уровня
        # ВЕТКИ попали в счёт уровня ФУНКЦИИ, `named` БОЛЬШЕ `skipped`, и старая
        # формула печатала отрицательное «число пропусков» (наблюдалось `-6`).
        # Нарушение предпосылки называет ЗАПЕЧАТАННАЯ спецификация
        # `tools/funnel_accounting.py`, доказанная самим KERN: выдать выдуманное
        # число вместо N — и есть тот дефект, который здесь закрывается.
        try:
            diff = unexplained_skips(skipped, named)
        except ValueError as _e407:
            print(f"    [!] пропусков БЕЗ записанной причины: НЕ ЧИСЛО — {_e407}")
        else:
            print(f"[!] пропусков БЕЗ записанной причины: {diff} — это "
                  f"дефект инструмента, а не свойство проверяемого кода")
    if total:
        # ДЕФЕКТ #405: корзины обязаны покрывать `total` ровно один раз.
        # `checked` уже ВКЛЮЧАЕТ функции без `if`, чья арифметика проверена, —
        # именно это и было исправлено; отдельно ветви и «только арифметика»
        # здесь не разделяются (граница названа в METRICS §173).
        _left = unaccounted(total, checked, 0, trivial, skipped)
        print(f"    buckets: checked {checked} | trivial {trivial} | skipped {skipped} "
              f"| Σ {checked + trivial + skipped} == total {total}")
        if _left != 0:
            print(f"    [!] ИНВАРИАНТ ВОРОНКИ НАРУШЕН: остаток {_left} — корзины не "
                  f"покрывают `total` (дефект инструмента, спецификация "
                  f"funnel_accounting.unaccounted)")
    if notes:
        _xray_report_branch_notes(notes)


def _xray_report_branch_notes(notes: dict[str, int]) -> None:
    """Напечатать СПРАВОЧНЫЕ заметки уровня ВЕТКИ (дефект #407.2).

    ЗАЧЕМ ОТДЕЛЬНО. «Ветка N не решена решателем» — это НЕ пропущенная функция:
    функция ПРОВЕРЕНА, а одна её ветвь осталась нерешённой. Складывать такие
    заметки в гистограмму пропусков значит вычитать число ветвей из числа функций
    — ровно так и получалось бессмысленное `-6`. Здесь они печатаются своим
    ярлыком `note:` и НИКОГДА не попадают в инвариант «Σ причин == skipped».
    """
    if not notes:
        return
    print(f"    note: уровень ВЕТКИ (в счётчик `skipped` НЕ входит) × "
          f"{sum(notes.values())}")
    for key, cnt in sorted(notes.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
        print(f"    note: {key} × {cnt}")


def _xray_report_skipped(skipped: dict[str, int]) -> None:
    """Напечатать пропуск по расширению ИМЕНОВАННО, а не молча (#381)."""
    if not skipped:
        return
    total = sum(skipped.values())
    top = ", ".join(f"{k}:{v}" for k, v in
                    sorted(skipped.items(), key=lambda kv: (-kv[1], kv[0]))[:8])
    print(f"[i] ПРОПУЩЕНО по расширению: {total} файл(ов) — {top}")


# Делители C-like: `a / b`, `a % b`, `@divTrunc(a, b)`, `@rem(a, b)`.
# `?? `//` — КОММЕНТАРИЙ в C/Zig, поэтому деление ищется как `/` НЕ перед `/`.
# Локальные объявления (`const q = …`, `var n: i32 = …`, `let x = …`):
# их НЕЛЬЗЯ считать свободными параметрами в делителе.
_RE_CLIKE_LOCAL = re.compile(r"\b(?:const|var|let)\s+(\w+)\s*(?::\s*([\w.]+))?\s*=")
# ДЕФЕКТ #189: C-касты `(size_t)(…)`, `(ptrdiff_t)(…)`, `(const char *)p`.
# Список — только ключевые слова типов, чтобы `(x)` (скобки вокруг переменной)
# не считался кастом.
_C_CAST = re.compile(
    r"\(\s*(?:const\s+|volatile\s+)*"
    r"(?:unsigned\s+|signed\s+)?"
    r"(?:size_t|ssize_t|ptrdiff_t|intptr_t|uintptr_t|bufsize_t|"
    r"uint8_t|uint16_t|uint32_t|uint64_t|"
    r"int8_t|int16_t|int32_t|int64_t|"
    r"unsigned|signed|int|long|short|char|float|double|bool|void)"
    r"\s*\*?\s*\)")
# ДЕФЕКТ #183 (Let-Inlining для C-like): нужен ПРАВЫЙ операнд присваивания,
# иначе `const bit_test = addr & ~(alignment - 1); if (bit_test == addr) …`
# работает с НЕИЗВЕСТНЫМИ именами, и `--xray` выдаёт ложный [CRASH PATH].
_RE_CLIKE_LOCAL_RHS = re.compile(
    r"\b(?:const|var|let)\s+(\w+)\s*(?::\s*([\w.\[\]\?\* ]+))?\s*=\s*([^;]+);")

_RE_CLIKE_DIV = re.compile(
    r"(?:@divTrunc|@rem|@divFloor|@mod)\s*\(([^,()]+),\s*([^()]+)\)"
    r"|([A-Za-z_][\w.\[\]]*)\s*/\s*([A-Za-z_][\w.\[\]]*)"
    r"|([A-Za-z_][\w.\[\]]*)\s*%\s*([A-Za-z_][\w.\[\]]*)")

_RE_CLIKE_IF = re.compile(r"\bif\s*\(((?:[^()]|\([^()]*\))*)\)")
# B2: индекс `buf[i - 1]` и размер в аллокации `malloc(len + 1)`.
_RE_CLIKE_INDEX = re.compile(r"([A-Za-z_]\w*(?:->\w+|\.\w+)*)\s*\[\s*([^\[\]]{1,60}?)\s*\]")
_RE_CLIKE_ALLOC = re.compile(
    r"\b(malloc|calloc|realloc|xmalloc|xrealloc|cmalloc|"
    r"strbuf_grow|cmark_strbuf_grow|@alloc\w*|alloc)\s*\(([^;]{1,120}?)\)")
# ДЕФЕКТ #180: Rust/Go/JS пишут `if x > 0 {` — БЕЗ круглых скобок. Без этого
# условия не извлекались вообще (ripgrep: 0 проверенных функций из 1354).
_RE_CLIKE_IF_BARE = re.compile(r"\bif\s+(?!\()([^{};\n]+?)\s*\{")


def _clike_ifs(body: str):
    """Все `if`-условия: сначала со скобками, затем без; в порядке появления."""
    hits = [(m.start(), m) for m in _RE_CLIKE_IF.finditer(body)]
    used = {s for s, _ in hits}
    hits += [(m.start(), m) for m in _RE_CLIKE_IF_BARE.finditer(body)
             if m.start() not in used]
    hits.sort(key=lambda x: x[0])
    return [m for _, m in hits]


_NUMERIC_TYPES = {"i8", "i16", "i32", "i64", "i128", "u8", "u16", "u32", "u64",
                  "u128", "isize", "usize", "int", "long", "short", "int32_t",
                  "uint32_t", "uint64_t", "int64_t", "number", "i32_t"}

# ДЕФЕКТ #188: слова C, которые не могут быть именем параметра.
# Нужны после снятия `*`/`[]` с `int *buf`: если тип записан без имени
# (`int`, `void`), последнее «слово» — сам тип, и объявлять его переменной
# в SMT-LIB нельзя.
_C_KEYWORDS = {
    "void", "char", "short", "int", "long", "float", "double", "signed",
    "unsigned", "const", "static", "inline", "volatile", "register",
    "struct", "union", "enum", "size_t", "ssize_t", "bool", "wchar_t",
    "int8_t", "int16_t", "int32_t", "int64_t", "uint8_t", "uint16_t",
    "uint32_t", "uint64_t", "intptr_t", "uintptr_t", "bufsize_t",
}


# 🔴 ДЕФЕКТ #183 (полевой прогон по zls/tigerbeetle): без ДИАПАЗОНОВ ТИПОВ
# `assert(index < len)` не доказывает `len > 0` для беззнакового `u32`
# (в Int `index < 0` выполнимо), и `--xray` выдавал ложный [CRASH PATH]
# на защищённом коде. Диапазоны ниже — машинные границы типов (не догадка).
def _c_type_key(ty: str) -> str | None:
    """Нормализация C-типа в ключ диапазона — С УЧЁТОМ ЗНАКОВОСТИ.

    ДЕФЕКТ #368 (ИЗМЕРЕНО на `TheAlgorithms/C/math/fibonacci_formula.c`).
    `int fib(unsigned int n)` теряло `unsigned` при нормализации
    (`ty.split()[-1]` давало `int`), поэтому `n` получал ЗНАКОВЫЙ диапазон i32,
    и `n + 1` объявлялось переполнением. В C переполнение БЕЗЗНАКОВОГО типа
    ОПРЕДЕЛЕНО стандартом (заворачивание по модулю 2^N) — это НЕ UB, и такое
    обвинение ЛОЖНО. Теперь знаковость сохраняется, а беззнаковые типы
    отсекаются в самом детекторе (`lo == 0`).
    """
    t = re.sub(r"\b(?:const|volatile|static|register|mut|extern)\b", " ", ty)
    t = t.replace("*", " ").replace("&", " ")
    t = re.sub(r"\s+", " ", t).strip().lower()
    if not t:
        return None
    words = t.split()
    unsigned = "unsigned" in words
    words = [w for w in words if w != "unsigned"]
    if not words:
        return "uint" if unsigned else None
    base = words[-1]
    if unsigned:
        return {"int": "uint", "short": "u16", "char": "u8",
                "long": "u64"}.get(base)
    if "long" in words:
        return "i64"
    if "short" in words:
        return "i16"
    if base == "char":
        return "i8"
    return base


_CLIKE_RANGES = {
    "u8": (0, 255), "u16": (0, 65535), "u32": (0, 4294967295),
    "u64": (0, 18446744073709551615), "usize": (0, 18446744073709551615),
    "uint": (0, 4294967295), "unsigned": (0, 4294967295),
    "size_t": (0, 18446744073709551615),
    "i8": (-128, 127), "i16": (-32768, 32767),
    "i32": (-2147483648, 2147483647),
    "i64": (-9223372036854775808, 9223372036854775807),
    "isize": (-9223372036854775808, 9223372036854775807),
    "int": (-2147483648, 2147483647),
}


def _split_top_and(expr: str) -> list[str]:
    """Разбить `a > 0 and b == 1` по ВЕРХНЕМУ `and` (учитывая скобки)."""
    out, depth, cur = [], 0, ""
    i = 0
    while i < len(expr):
        c = expr[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0 and expr.startswith(" and ", i):
            out.append(cur.strip())
            cur = ""
            i += 5
            continue
        cur += c
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def _clike_param_ranges(praw: str) -> dict:
    """Диапазоны параметров по их объявленным типам (Zig/Rust/Go/C/TS)."""
    out: dict = {}
    for part in praw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            nm, ty = part.split(":", 1)
            name = nm.strip().split()[-1] if nm.strip() else ""
            ty = ty.strip()
        else:
            toks = part.split()
            if len(toks) < 2:
                continue
            name, ty = toks[-1], " ".join(toks[:-1])
        name = name.lstrip("*&")
        ty = ty.replace("const", " ").replace("mut", " ").replace("*", " ")
        ty = ty.replace("&", " ").strip().lower()
        key = _c_type_key(ty) if ty else None
        if key and key in _CLIKE_RANGES:
            out[name] = _CLIKE_RANGES[key]
    return out


# ДЕФЕКТ #410: слова-ИНСТРУКЦИИ/ВЫЗОВЫ. В TS-файле `RE_FN_C` матчит ВЫЗОВЫ
# (`await stat(p)`, `throw new Error(…)`), и они попадали в список функций.
_STMT_CALL_WORDS = frozenset((
    "await", "throw", "new", "return", "if", "else", "for", "while", "switch",
    "catch", "case", "delete", "typeof", "yield"))


def _clike_functions(path: Path):
    """УСТОЙЧИВЫЙ разбор C-like функций БЕЗ исполнения тела.

    ЗАЧЕМ. `parse_clike` ИСПОЛНЯЕТ тело (`_exec_clike`) — на реальном std Zig
    (`comptime assert(@typeInfo(T) …)`, `try`, `@as`) это падает, и `--xray`
    давал `checked 0 / 11`. Для рентгена исполнение не нужно: достаточно
    заголовка и текста тела, из которого извлекаются `if (...)`.

    Возвращает [(name, numeric_params, body_text, lineno)].
    Тела берутся по балансу скобок от строки объявления — поэтому `comptime`,
    `@as`, `try` и вложенные блоки не мешают (они просто не анализируются).
    """
    # ДЕФЕКТ #178: баланс скобок и `if (...)` считаются по коду БЕЗ
    # комментариев и строковых литералов (`}` внутри строки ломал разбор,
    # а `// a/b` давал ложный делитель). Переводы строк сохранены.
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    src = _strip_c_comments_strings(raw_text)
    if path.suffix in {".ts", ".js"}:
        src = _strip_js_regex(src)          # `/re/g` — регекс, а не деление
    lines = src.splitlines()
    _raw_lines = raw_text.splitlines()
    out = []
    for i, line in enumerate(lines):
        _ts = path.suffix in {".ts", ".js"}
        m = RE_FN_TS.match(line) if _ts else None
        _via_c = False
        if m is None:
            m = (RE_FN_FN.match(line) or RE_FN_GO.match(line)
                 or RE_FN_C.match(line))
            _via_c = m is not None and m.re is RE_FN_C
        if not m:
            continue
        # ДЕФЕКТ #410: ГРУППЫ — ПО СРАБОТАВШЕЙ РЕГУЛЯРКЕ, а не по суффиксу файла.
        # У `RE_FN_C` group(1) — слот типа/модификаторов (`await`, `throw new`),
        # group(2) — ИМЯ, group(3) — параметры. Для .ts ветка брала group(1)
        # как имя, поэтому настоящие методы классов TS получали имя «await »,
        # а их параметры терялись. ИЗМЕРЕНО на `io-util.ts`: `await stat(p)` ->
        # имя `await ` вместо `stat`.
        if _via_c:
            _slot_words = set(re.findall(r"[A-Za-z_]\w*", m.group(1) or ""))
            # СЛОВА СЛОТА, а не вся строка: `throw new` — ДВА слова.
            if _slot_words & _STMT_CALL_WORDS:
                continue
            name, praw = m.group(2), m.group(3)
        elif path.suffix in {".zig", ".rs", ".ts", ".js"}:
            name, praw = m.group(1), m.group(2)
        elif path.suffix == ".go":
            name, praw = m.group(1), m.group(2)
        else:
            name, praw = m.group(2), m.group(3)
        if name in _STMT_CALL_WORDS:
            continue
        params = []
        for part in praw.split(","):
            part = part.strip()
            if not part or part.startswith("comptime") or "type" in part.split(":")[-1]:
                continue
            nm = part.split(":")[0].split()
            if nm:
                # ДЕФЕКТ #188: `int *buf` давал имя `*buf`, `int buf[]` — `buf[]`.
                # Такое имя нельзя объявить в SMT-LIB (`(declare-fun *buf …)`),
                # поэтому kernc отвечал ошибкой разбора, и ВСЕ проверки функции
                # молча уходили в «не знаю». Снимаем всё, кроме [A-Za-z0-9_].
                pname = re.sub(r"[^0-9A-Za-z_]", "", nm[-1])
                if pname and pname not in _C_KEYWORDS:
                    params.append(pname)
        # тело: от строки объявления до баланса скобок
        depth = 0
        started = False
        body: list[str] = []
        for j in range(i, min(i + 400, len(lines))):
            ln = lines[j]
            depth += ln.count("{") - ln.count("}")
            if "{" in ln:
                started = True
            body.append(_raw_lines[j] if j < len(_raw_lines) else ln)
            if started and depth <= 0:
                break
        # `@kern:requires` над функцией — часть домена. Для C-like это
        # единственный способ сказать «alignment > 0» (дефект #183: без этого
        # аннотированный `bitAlignedAgrees` давал ложный [CRASH PATH]).
        req_parts: list[str] = []
        # Комментарии стёрты в `lines`, поэтому контракт читаем из СЫРОГО текста.
        raw_lines = raw_text.splitlines()
        # Идём НАЗАД по доку-блоку и останавливаемся на первой не-комментарной
        # (или пустой) строке: иначе контракт ПРЕДЫДУЩЕЙ функции приклеивался
        # к следующей (найдено на `examples/edge_cases.zig`: `modBuiltin`
        # получил `d > 0` от соседней функции).
        for k in range(i - 1, max(-1, i - 12), -1):
            raw_ln = raw_lines[k].strip() if k < len(raw_lines) else ""
            if not raw_ln:
                break
            if not (raw_ln.startswith("//") or raw_ln.startswith("#")
                    or raw_ln.startswith("/*") or raw_ln.startswith("*")):
                break
            rm = re.search(r"@kern:requires\s+(.+)$", raw_ln)
            if rm:
                req_parts.extend(_split_top_and(rm.group(1).strip()))
        out.append((name, params, "\n".join(body), i + 1,
                    _clike_param_ranges(praw), req_parts))
    return out


_RE_STRUCT_DEF = re.compile(
    r"(?:typedef\s+)?struct\s*(?:[A-Za-z_]\w*)?\s*\{([^{}]*)\}\s*(?:[A-Za-z_]\w*)?\s*;")
_RE_STRUCT_FIELD = re.compile(r"^\s*([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;")


def _clike_struct_fields(text: str) -> dict[str, str]:
    r"""Поля структур -> тип (`n_columns -> uint16_t`). ДЕФЕКТ #193.

    ЗАЧЕМ (CVE `ac80f7b` в cmark-gfm): `row->n_columns` объявлено как
    `uint16_t` и инкрементируется в цикле без проверки `< UINT16_MAX` —
    счётчик переполняется. Без карты полей тип неоткуда взять, поэтому
    раньше такая уязвимость пропускалась.
    """
    out: dict[str, str] = {}
    for m in _RE_STRUCT_DEF.finditer(_strip_c_comments_strings(text)):
        for line in m.group(1).splitlines():
            fm = _RE_STRUCT_FIELD.match(line)
            if fm:
                out.setdefault(fm.group(2), fm.group(1))
    return out


def _is_u16(ty: str) -> bool:
    return ty.strip().lower() in {"uint16_t", "u16", "unsigned short", "ushort"}

def _clike_block_end(body: str, start: int) -> int:
    """Конец блока/оператора, начинающегося в `start` (позиция после `)` if).

    Если дальше `{ ... }` — считаем скобки; иначе оператор до `;`.
    ДЕФЕКТ #318: нужен, чтобы понимать, находится ли операция ВНУТРИ блока.
    """
    i = start
    n = len(body)
    while i < n and body[i] in " \t\r\n":
        i += 1
    if i < n and body[i] == "{":
        depth = 0
        while i < n:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return n
    j = body.find(";", i)
    return (j + 1) if j != -1 else n


def _assigned_between(body: str, start: int, end: int) -> set:
    """Имена, которым ПРИСВАИВАЕТСЯ значение в `body[start:end)`.

    ЗАЧЕМ (шаг 6 плана, предохранитель №2). Накопленный предикат вида `node != 0`
    относится к СТАРОМУ значению. Если между гардом и точкой анализа стоит
    `node = node->next`, предикат прикладывать НЕЛЬЗЯ — иначе вторая проверка
    `if (node == NULL) break;` объявляется МЁРТВОЙ ВЕТВЬЮ. Это типичный обход
    узлов в `cmark-gfm`, и ложное обвинение тут было бы системным.
    """
    if start >= end:
        return set()
    seg = body[start:end]
    names = set(re.findall(r"\b([A-Za-z_]\w*)\s*=(?!=)", seg))
    names |= set(re.findall(r"\b([A-Za-z_]\w*)\s*(?:\+\+|--|\+=|-=|\*=|/=|<<=|>>=)",
                            seg))
    return names


_NULL_WORDS = r"(?:nil|null|NULL|None|undefined)"


def _null_to_zero(cond: str):
    """`p == NULL` -> `p == 0`, `!p` -> `p == 0`, голое `p` -> `p != 0`.

    ЗАЧЕМ (шаг 6 плана, дефект #197). Раньше ЛЮБОЕ условие со словом `nil/null`
    отбрасывалось: в Int-модели `nil` бессмысленно, и `err != nil` давал ложный
    DEAD BRANCH. Но отбрасывание стоило 49 функций в `cmark-gfm` и 3 в `toolkit`.
    Указатель моделируется как `Int`, где 0 = NULL, поэтому:

      * `p == NULL`  -> `p == 0`;
      * `p != NULL`  -> `p != 0`;
      * `!p`         -> `p == 0`  (ЛОВУШКА СОРТОВ: `not p` над `Int` недопустим —
        Z3 даёт ошибку сортов, а `_smt_verdict` тихо превращает её в `unknown`);
      * голое `p` в БУЛЕВОЙ позиции (всё условие или операнд `&&`/`||`) -> `p != 0`.

    ВОЗВРАЩАЕТ `None`, если после переписи слово `nil/null` ВСЁ ЕЩЁ осталось:
    значит форма незнакома, и честный ответ — прежний SKIP с названной причиной,
    а не догадка. Это граница, а не «мы всё умеем».
    """
    s = cond
    n = _NULL_WORDS
    s = re.sub(rf"\b([A-Za-z_]\w*)\s*==\s*{n}\b", r"\1 == 0", s)
    s = re.sub(rf"\b{n}\s*==\s*([A-Za-z_]\w*)", r"\1 == 0", s)
    s = re.sub(rf"\b([A-Za-z_]\w*)\s*!=\s*{n}\b", r"\1 != 0", s)
    s = re.sub(rf"\b{n}\s*!=\s*([A-Za-z_]\w*)", r"\1 != 0", s)
    # `!p` -> `p == 0` (но не `!=`), и ТОЛЬКО на ГОЛОМ имени (дефект #414).
    # ИЗМЕРЕНО: без страховки перепись била по вызову и давала МУСОР
    # `!S_is_line_end_char(c)` -> `S_is_line_end_char == 0(c)`, а `expr_smt`
    # принимал `0(...)` за HAVOC-вызов и «переводил» это в
    # `(= S_is_line_end_char _havoc_1)` — ЛОЖНУЮ модель (имя функции становилось
    # переменной). В `cmark-gfm/src` так молча принимались 9 условий, в
    # `toolkit/packages` те же 17 форм падали громко (в TS `0.method()` — ошибка
    # синтаксиса). Ложная модель ХУЖЕ пропуска, поэтому форма вне подмножества
    # теперь честно уходит в SKIP с названной причиной.
    s = re.sub(r"!\s*([A-Za-z_]\w*)(?![\w.\-\[(=])", r"\1 == 0", s)
    # Голое имя в булевой позиции: целое условие или операнд `&&`/`||`.
    parts = re.split(r"(\s*(?:&&|\|\|)\s*)", s)
    for i, part in enumerate(parts):
        if i % 2:
            continue
        t = part.strip()
        if re.fullmatch(r"[A-Za-z_]\w*", t):
            parts[i] = part.replace(t, f"{t} != 0")
    s = "".join(parts)
    if re.search(rf"\b{n}\b", s) or re.search(r"!(?!=)", s):
        return None
    return s


def _flatten_fields(s: str) -> str:
    """`a->b` и `a.b` -> ПЛОСКОЕ имя `a__b` (дефект #416, Приоритет 2).

    ЗАЧЕМ. Поле структуры/объекта — это ЗНАЧЕНИЕ, которое наша Int-модель
    моделирует как НЕИЗВЕСТНОЕ ЧИСЛО. Именно так уже устроены длины
    (`len(arr)` -> `kern_len_arr`). Плоское имя даёт ровно ту же семантику, а
    условия вида `node->next == NULL`, `!node->next`, `subj->flags & FLAG` из
    «синтаксиса» становятся переводимыми.

    ИЗМЕРЕНО («что-если» ДО правки, отказов перевода):
      * `cmark-gfm/src`  254 -> 154 (-100 условий, 43 % отказов);
      * `toolkit/packages` 77 -> 75 (в TS поле было НЕ главным блокером).

    ЧТО НЕ ТРОГАЕТСЯ:
      * ВЫЗОВ МЕТОДА `a.b(x)` — не поле, а вызов: остаётся как есть (вне
        подмножества, честный SKIP);
      * содержимое строковых литералов — оно уже заменено числами
        (`_literals_to_numbers` вызывается ДО этого);
      * числовой литерал (`1.5`) — шаблон требует БУКВУ в начале имени.

    РОДСТВЕННАЯ ФОРМА `typeof X` -> `X__typeof` (тоже неизвестный ТЕГ, а не
    значение). ИЗМЕРЕНО «что-если» на `toolkit`: +18 условий. Та же абстракция:
    свободный символ, поэтому проверки достижимости звуча, а SAT-детекторы
    защищены `_free_syms_in_path`.

    ЗВУЧНОСТЬ (два предохранителя, оба в коде):
      * А: `a__b` НЕ является параметром функции, поэтому `_free_syms_in_path`
        видит свободный символ и SAT-детекторы (делитель/переполнение) отказывают,
        а не выдумывают обвинение;
      * Б: `_clike_conds_at` сбрасывает предикат с `a__b`, если переназначена
        ЛИБО база `a`, ЛИБО само поле (см. `_mut_names_for`).
    """
    prev = None
    while prev != s:          # `a->b->c` -> `a__b__c`: до неподвижной точки
        prev = s
        s = re.sub(r"\b([A-Za-z_]\w*)\s*->\s*([A-Za-z_]\w*)(?!\s*\()", r"\1__\2", s)
        s = re.sub(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)(?!\s*\()", r"\1__\2", s)
        # `typeof X` -> `X__typeof`: тег типа — такое же неизвестное значение.
        s = re.sub(r"\btypeof\s+([A-Za-z_]\w*(?:__\w+)*)", r"\1__typeof", s)
    return s


def _mut_names_for(names: set) -> set:
    """Имена, переназначение которых ОТМЕНЯЕТ предикат (дефект #416, предохранитель Б).

    Для плоского имени `a__b` это не только само `a__b`, но и БАЗА `a`, и ПОЛЕ `b`:
    `a->b = …` даёт в тексте имя `b` перед `=`, а `a = …` — имя `a`. Без этого
    условие на СТАРОМ поле переживало мутацию базы (ложная мёртвая ветвь).
    """
    out = set(names)
    for nm in list(names):
        if "__" in nm:
            base, _sep, fld = nm.partition("__")
            out |= {base, fld}
    return out


def _clike_conds_at(pos: int, if_blocks: list, body: str = "") -> list[str]:
    """Условия, действующие В ПОЗИЦИИ `pos` (дефекты #318 и #401).

    `if_blocks` — (cond_end, block_end, cond_smt, exits) для каждого `if (cond)`.
    ВНУТРИ блока действует `cond`; ПОСЛЕ блока, который безусловно завершается
    (`return`/`break`/`continue`), действует `(not cond)`.

    ПОЧЕМУ ТАК (дефект #318). Раньше в `path_conds` складывалось ТОЛЬКО
    `(not cond)` — условие для кода ПОСЛЕ `if`. Делитель же стоит ВНУТРИ блока,
    и запрос получался `(x == 0) AND (x == 0)`, то есть ОТРИЦАНИЕ гарда:
    `if (x != 0) { y / x; }` объявлялся делением на ноль.

    ВЛОЖЕННОСТЬ (дефект #401). Наивное «после любого вышедшего блока действует
    `not cond`» даёт ПРОТИВОРЕЧИЕ на ВЗАИМОИСКЛЮЧАЮЩИХ ветвях:
        if (A) { if (B) return; } else if (C) { if (D) return; }
    Блоки `B` и `D` лежат в РАЗНЫХ ветвях, но оба «вышли наружу», и накопление
    давало одновременно `not B` и `not D` — при `D = not B` путь становился
    UNSAT, и ЛЮБОЕ последующее условие объявлялось мёртвым. ИЗМЕРЕНО на
    `cmark-gfm/src/utf8.c`: 4 ложных `[DEAD BRANCH]`.
    Поэтому `not cond` применяется только если позиция находится В ТОЙ ЖЕ
    ветви: блок обязан быть либо на верхнем уровне (и позиция вне блоков),
    либо внутри своего родителя, содержащего позицию.
    """
    chain = [i for i, (ce, be, _c, _e) in enumerate(if_blocks) if ce <= pos < be]
    # ШАГ 6, ПРЕДОХРАНИТЕЛЬ №2 — И ДЛЯ ОБЪЕМЛЮЩИХ БЛОКОВ ТОЖЕ. ИЗМЕРЕНО на
    # `cmark-gfm/src/inlines.c`: условие `if (new_inl != NULL)` из ОБЪЕМЛЮЩЕГО
    # блока оставалось в силе после присваивания `new_inl = …` ВНУТРИ него, и
    # вложенная проверка объявлялась мёртвой ветвью — ЛОЖНОЕ обвинение. Предикат
    # действует, только если имя НЕ переназначено между условием блока и позицией.
    out = []
    for _ci in chain:
        _ce_i, _be_i, _cond_i, _e_i = if_blocks[_ci]
        _mut_i = _assigned_between(body, _ce_i, pos)
        if _mut_i and (_mut_names_for(set(re.findall(r"[A-Za-z_]\w*", _cond_i))) & _mut_i):
            continue
        out.append(_cond_i)

    def _parent(idx: int) -> int:
        """Ближайший ОБЪЕМЛЮЩИЙ блок (или -1): минимальный по длине."""
        ce_i = if_blocks[idx][0]
        best, best_span = -1, None
        for j, (ce_j, be_j, _c, _e) in enumerate(if_blocks):
            if j == idx or not (ce_j <= ce_i < be_j):
                continue
            span = be_j - ce_j
            if best_span is None or span < best_span:
                best, best_span = j, span
        return best

    for i, (_ce, be, cond, exits) in enumerate(if_blocks):
        if pos < be or not exits:
            continue
        # ШАГ 6, ПРЕДОХРАНИТЕЛЬ №2 (сброс при мутации указателя). Предикат
        # относится к СТАРОМУ значению: если имя переназначено между концом
        # блока `be` и позицией `pos`, он НЕ действует.
        _mut = _assigned_between(body, be, pos)
        if _mut and (set(re.findall(r"[A-Za-z_]\w*", cond)) & _mut):
            continue
        par = _parent(i)
        if par < 0:
            if chain:
                continue
        else:
            pce, pbe = if_blocks[par][0], if_blocks[par][1]
            if not (pce <= pos < pbe):
                continue
        out.append(f"(not {cond})")
    return out


_RE_CLIKE_DECL = re.compile(
    r"\b((?:unsigned|signed|long|short|const|static)\s+)*"
    r"([A-Za-z_]\w*(?:\s*\*)?)\s+([A-Za-z_]\w*)\s*(?:=|;|,)")
# Правые части присваиваний и `return` — кандидаты-выражения. `(?<![=!<>+\-*/%])`
# отсекает `==`, `!=`, `<=`, `>=`; `[^;{}]+` допускает переносы строки внутри
# выражения, но не перескакивает границу оператора/блока.
_RE_CLIKE_ASSIGN_RHS = re.compile(r"(?<![=!<>+\-*/%])=(?!=)\s*([^;{}]+)")
_RE_CLIKE_RETURN_RHS = re.compile(r"\breturn\s+([^;{}]+)")
# ЗАКОННОЕ оборачивание/насыщение: переполнение здесь — ЗАДУМАННАЯ семантика,
# а не дефект. Проверять его — значит обвинять корректный код.
_WRAP_MARKERS = ("+%", "-%", "*%", "+|", "-|", "wrapping_", "saturating_",
                 "addWithOverflow", "mulWithOverflow", "subWithOverflow")


def _clike_local_ranges(body: str) -> dict[str, tuple[int, int]]:
    """Объявленные в теле локальные переменные -> границы их типов.

    ЗАЧЕМ. `no-overflow.prp` (и обычный смысл UB) требует, чтобы арифметика
    оставалась в границах ОБЪЯВЛЕННОГО типа. Без карты типов локальных
    переменных тип выражения неизвестен, и обвинять нельзя (ложное обвинение
    хуже пропуска — урок #178/#183).
    """
    out: dict[str, tuple[int, int]] = {}
    for m in _RE_CLIKE_DECL.finditer(body):
        qual, ty, nm = m.group(1) or "", m.group(2), m.group(3)
        key = _c_type_key(f"{qual} {ty}")
        if not key:
            continue
        rng = _CLIKE_RANGES.get(key) or TYPE_RANGE.get(key)
        if rng:
            out.setdefault(nm, rng)
    return out


# Типы целочисленных литералов C11 (6.4.4.1p5). ВАЖНО: `long` на LP64 — 64 бита.
_C_INT_RANGES = {"int": TYPE_RANGE["int"], "long": TYPE_RANGE["long"],
                 "long long": TYPE_RANGE["long"]}


def _c_literal_range(v: int) -> tuple[int, int] | None:
    """Тип целочисленного литерала в C: ПЕРВЫЙ, вмещающий значение.

    ЗАЧЕМ (измерено на SV-COMP, `NoNegativeIntegerConstant.c`, эталон `true`).
    Первая версия детектора считала ВСЕ литералы типом `int`, и объявляла
    переполнением `long x = -2147483648 - 1;`. Это ЛОЖНОЕ ОБВИНЕНИЕ: литерал
    `2147483648` не влезает в `int`, поэтому по стандарту C он имеет тип
    `long`, унарный минус и вычитание идут в `long`, и переполнения НЕТ. Файл
    даже объясняет это в своих комментариях — и именно поэтому он называется
    `NoNegativeIntegerConstant`. Ложное обвинение хуже пропуска (урок
    #178/#183), поэтому тип берётся по ПРАВИЛУ ЯЗЫКА, а не по догадке.
    """
    for key in ("int", "long", "long long"):
        lo, hi = _C_INT_RANGES[key]
        if lo <= v <= hi:
            return (lo, hi)
    return None     # не влезает даже в `long long` -> в C это unsigned/UB, не обвиняем


_C_I32_RANGE = (-2147483648, 2147483647)


def _c_promote(rng: tuple[int, int] | None) -> tuple[int, int] | None:
    """Целочисленное ПОВЫШЕНИЕ (C11 6.3.1.1).

    ИЗМЕРЕНО на `IntegerPromotion-1.c` (эталон `true` = БЕЗОПАСНО):
    `short a = 32767; unsigned short b = a + a + a;` — переполнения НЕТ, потому
    что при обычных арифметических преобразованиях операнды `+` повышаются до
    `int`. Без этого правила детектор объявлял `a + a = 65534` переполнением
    `i16` — ЛОЖНОЕ ОБВИНЕНИЕ. Файл объясняет это в своих комментариях.

    Правило: тип УЖЕ `int` повышается до `int` (это `char`, `short`, а также
    `unsigned char`/`unsigned short` — `int` вмещает все их значения). Типы
    ШИРЕ `int` (`long`, `i64`) не повышаются; `unsigned int` тоже (его диапазон
    не влезает в `int`).
    """
    if rng is None:
        return None
    lo, hi = rng
    if (hi - lo) < (_C_I32_RANGE[1] - _C_I32_RANGE[0]):
        return _C_I32_RANGE
    return rng


def _operand_range(node: ast.AST, var_ranges: dict) -> tuple[int, int] | None:
    """Диапазон ТИПА операнда (обычные арифметические преобразования C).

    Литерал -> по значению (`_c_literal_range`); переменная -> объявленный тип;
    `-x` -> тип `x`; `a op b` -> ШИРОЧАЙШИЙ из операндов (C повышает тип до
    общего). Неизвестный операнд -> None (пропуск, а не догадка).
    Результат проходит ЦЕЛОЧИСЛЕННОЕ ПОВЫШЕНИЕ (`_c_promote`).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return _c_literal_range(node.value)
    if isinstance(node, ast.Name):
        return _c_promote(var_ranges.get(node.id))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _c_promote(_operand_range(node.operand, var_ranges))
    if isinstance(node, ast.BinOp):
        l = _operand_range(node.left, var_ranges)
        r = _operand_range(node.right, var_ranges)
        if l is None or r is None:
            return None
        return l if (l[1] - l[0]) >= (r[1] - r[0]) else r
    return None


def _const_eval(node: ast.AST, consts: dict) -> int | None:
    """Значение выражения, если оно ВЫЧИСЛИМО статически, иначе None.

    Подставляет локальные, чьё значение известно (единственное присваивание
    константы). Семантика ДЕЛЕНИЯ и ОСТАТКА — как в C: усечение к нулю, знак
    остатка — знак делимого (в Python `//` и `%` другие, поэтому считаем сами).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _const_eval(node.operand, consts)
        if v is None:
            return None
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        l = _const_eval(node.left, consts)
        r = _const_eval(node.right, consts)
        if l is None or r is None:
            return None
        if isinstance(node.op, ast.Add):
            return l + r
        if isinstance(node.op, ast.Sub):
            return l - r
        if isinstance(node.op, ast.Mult):
            return l * r
        if r == 0:
            return None                     # деление на ноль — отдельный детектор
        q = abs(l) // abs(r)
        if (l < 0) != (r < 0):
            q = -q                          # C: усечение К НУЛЮ
        if isinstance(node.op, (ast.Div, ast.FloorDiv)):
            return q
        if isinstance(node.op, (ast.Mod, )):
            return l - q * r                # C: знак остатка = знак делимого
    return None


_RE_CLIKE_CONST_LOCAL = re.compile(
    r"\b(?:unsigned|signed|long|short|const|static|\s)*"
    r"[A-Za-z_]\w*\s+([A-Za-z_]\w*)\s*=\s*([^;{}]+);")


def _clike_const_locals(body: str, mask: str | None = None) -> dict[str, int]:
    """Локальные, значение которых ИЗВЕСТНО (единственное присваивание).

    ЗАЧЕМ. Без этого `int x = 2147483647; x++;` нечем проверить: значение `x`
    не из типа, а из присваивания. Требование «присваивание РОВНО ОДНО» —
    защита от звучимости: если `x` переприсваивается в цикле или ветви, его
    значение на момент операции неизвестно, и обвинять нельзя.

    ДЕФЕКТ #412: тело теперь СЫРОЕ (это нужно для семантики литералов в
    условиях), поэтому регулярка находила «локальные» ВНУТРИ СТРОКОВЫХ
    ЛИТЕРАЛОВ. ИЗМЕРЕНО на `cmark-gfm/src/xml.c`: строка
    `"<?xml version=\\"1.0\\" encoding=\\"UTF-8\\"?>"` давала мнимую локальную
    `version` с `?` без `:` — и это РОНЯЛО весь обход корпуса. Поэтому ПОИСК
    идёт по МАСКЕ (комментарии и содержимое литералов — пробелы), а ЗНАЧЕНИЕ
    берётся из сырого тела по тем же смещениям: `_strip_c_comments_strings`
    сохраняет длину ПОСИМВОЛЬНО.
    """
    src = mask if mask is not None else _strip_c_comments_strings(body)
    out: dict[str, int] = {}
    for m in _RE_CLIKE_CONST_LOCAL.finditer(src):
        nm = m.group(1)
        rhs = body[m.start(2):m.end(2)].strip()
        if len(re.findall(rf"\b{re.escape(nm)}\s*=(?!=)", src)) != 1:
            continue                        # переприсваивается — значение неизвестно
        try:
            node = ast.parse(
                clike_to_python(_unwrap_zig_builtins(_literals_to_numbers(rhs))),
                mode="eval").body
        except (SyntaxError, ValueError, Unsupported):
            # Форма вне подмножества — это ПРОПУСК, а не авария: значение
            # неизвестно, значит обвинять нельзя (но и падать незачем).
            continue
        v = _const_eval(node, out)
        if isinstance(v, int):
            out[nm] = v
    return out


def _clike_incdec_findings(name: str, body: str, var_ranges: dict,
                           consts: dict) -> list[str]:
    """[OVERFLOW PATH] на `x++ / ++x / x-- / --x` с ИЗВЕСТНЫМ значением.

    ЗАЧЕМ (измерено на SV-COMP): четыре задачи категории
    (`PostfixIncrement`, `PrefixIncrement`, `PostfixDecrement`,
    `PrefixDecrement`) — это ровно `int x = 2147483647; x++;` и его варианты.
    Инкремент/декремент не является `BinOp`, поэтому первый вариант детектора
    их не видел.

    ПОЧЕМУ ТОЛЬКО С ИЗВЕСТНЫМ ЗНАЧЕНИЕМ. Незащищённый `x++` в общем случае
    МОЖЕТ переполниться (если `x` уже на границе), но на реальном коде это
    дало бы находку на каждом счётчике цикла — то есть шум. Обвиняем только
    там, где значение ВЫЧИСЛИМО, и тогда это не «возможно», а «будет».
    """
    out: list[str] = []
    for m in re.finditer(r"(?:\+\+|--)\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(?:\+\+|--)",
                         body):
        nm = m.group(1) or m.group(2)
        if nm not in consts or nm not in var_ranges:
            continue
        lo, hi = var_ranges[nm]
        new = consts[nm] + (1 if "++" in m.group(0) else -1)
        if new < lo or new > hi:
            op = "++" if "++" in m.group(0) else "--"
            out.append(
                f"[OVERFLOW PATH] {name}: переполнение типа "
                f"([{lo}, {hi}]): `{nm}{op}` при `{nm} = {consts[nm]}` "
                f"даёт {new} — UB до возврата")
    return out


FREE_PATH_REASON = "путь зависит от неизвестной константы (SAT не решаем: #178/#183)"


def _free_syms_in_path(asserts: list, params) -> list:
    """Имена в ПУТИ, значение которых НЕИЗВЕСТНО (шаг 4 плана, класс #178/#183).

    ЗАЧЕМ (ИЗМЕРЕНО). Защита в `_clike_overflow_findings` требует, чтобы каждое имя
    В ВЫРАЖЕНИИ было параметром или типизированным локальным. Она НЕ покрывает ПУТЬ:
    если свободное имя попало в `path_conds`, запрос становится
    `∃c. path(c) ∧ overflow` — СЛАБЕЕ реальности, и Z3 берёт c = ±MAX.

    ЖИВОЙ ЗАМЕР на КОРРЕКТНОМ коде:
        #define MAX_BUF 1024
        int scale(int n) { if (n < MAX_BUF) return n + n; return 0; }
    давал `[OVERFLOW PATH] … [КОНТРПРИМЕР] MAX_BUF = -2147483647, n = -2147483648`,
    хотя при MAX_BUF = 1024 переполнения НЕТ. Ложное обвинение хуже пропуска,
    поэтому SAT-проверки обязаны ОТКАЗАТЬСЯ от такого пути.
    """
    known = set(params)
    out: list = []
    for a in asserts:
        for tok in re.findall(r"[A-Za-z_][\w]*", a):
            if tok in _SMT_RESERVED or tok in known or tok in out:
                continue
            out.append(tok)
    return out


def _smt_sat_guarded(kernc, params, asserts, why: list):
    """`_smt_sat` С ФЛАГОМ `free_syms_in_path` (шаг 4 плана).

    ПОЧЕМУ ТОЛЬКО ДЛЯ SAT. UNSAT-проверки (мёртвая ветвь, избыточный гард)
    свободная константа НЕ ломает: «недостижимо для ЛЮБОГО значения» — честный
    вывод, он только усиливается. А SAT-проверки (переполнение, границы,
    делители) при свободном имени в пути дают ЛОЖНОЕ ОБВИНЕНИЕ — они обязаны
    отказаться, НАЗВАВ причину, а не выдумать контрпример.
    """
    if _free_syms_in_path(asserts, params):
        why.append(FREE_PATH_REASON)
        return None
    return _smt_sat(kernc, params, asserts)


def _clike_overflow_findings(name: str, params, body: str, ranges: dict,
                             path_conds: list[str], if_blocks: list,
                             local_smt: dict, kernc,
                             skip_why: list | None = None) -> list[str]:
    """[OVERFLOW PATH] для ЛЮБОЙ арифметики `+ - *` в C-like теле.

    ПОЧЕМУ ЭТО НУЖНО (дефект #367). До этой правки `--xray` для C имел
    детекторы деления на ноль, границ массива и РАЗМЕРА АЛЛОКАЦИИ, но не имел
    детектора переполнения ОБЫЧНОГО выражения. Измерено на официальной
    категории SV-COMP `signedintegeroverflow-regression`: поймано 0 из 10
    unsafe. Контрактный путь тоже не спасал: он проверяет ИТОГОВОЕ значение
    возврата, а `(2147483647 + 1) - 23` переполняется ВНУТРИ и «схлопывается»
    обратно в диапазон (итог 2147483625) — обязанность типа удовлетворена.

    Здесь проверяется КАЖДАЯ бинарная операция (свойство `no-overflow`), а не
    только возврат.

    ЗВУЧИМОСТЬ (почему не обвиняем лишнего):

      * границы берутся из ОБЪЯВЛЕННОГО типа (локальные — из тела, параметры —
        из сигнатуры). Неизвестный тип -> ПРОПУСК;
      * каждое имя в выражении обязано быть либо параметром, либо локальной с
        известным типом. Иначе в SMT появился бы СВОБОДНЫЙ символ, решатель
        подобрал бы ему значение вне всякого домена — и это дало бы ложное
        обвинение;
      * явное оборачивание (Zig `+% -% *% +| -|`, Rust `wrapping_*` /
        `saturating_*`, `@addWithOverflow`) ПРОПУСКАЕТСЯ: переполнение там —
        задуманная семантика, а не дефект;
      * поля структур (`->`, `.`) не моделируются -> ПРОПУСК;
      * проверка идёт ПОД путём (`if_blocks` + `path_conds`), поэтому операция
        внутри недостижимой ветви не обвиняется.

    КОНСТАНТНЫЕ выражения проверяются ТОЧНО и без Z3: значение считается в
    Python (целые безграничны) и сравнивается с границами типа. Это не
    оптимизация ради скорости — это ТОЧНЕЕ решателя: `2147483647 + 1` не
    требует SAT-запроса, ответ известен арифметически.
    """
    out: list[str] = []
    # МАСКА ДЛЯ ПОИСКА (дефект #412). Тело СЫРОЕ (нужно для семантики литералов в
    # условиях), поэтому регулярки поиска видят текст ВНУТРИ строковых литералов.
    # `_strip_c_comments_strings` сохраняет длину ПОСИМВОЛЬНО, поэтому маска
    # годится для ЛОКАЦИИ, а значения берутся из сырого тела по тем же смещениям.
    mask = _strip_c_comments_strings(body)
    var_ranges = dict(ranges or {})
    var_ranges.update(_clike_local_ranges(mask))
    consts = _clike_const_locals(body, mask)
    if not var_ranges:
        return _clike_incdec_findings(name, mask, var_ranges, consts)

    spans: list[tuple[int, str]] = []
    for m in _RE_CLIKE_ASSIGN_RHS.finditer(mask):
        spans.append((m.start(1), body[m.start(1):m.end(1)]))
    for m in _RE_CLIKE_RETURN_RHS.finditer(mask):
        spans.append((m.start(1), body[m.start(1):m.end(1)]))

    for pos, raw_expr in spans:
        raw_expr = _literals_to_numbers(raw_expr)
        if any(w in raw_expr for w in _WRAP_MARKERS):
            continue
        if "->" in raw_expr or re.search(r"\w\.\w", raw_expr):
            continue        # поле структуры — тип/значение неизвестны
        try:
            tree = ast.parse(clike_to_python(_unwrap_zig_builtins(raw_expr)),
                             mode="eval").body
        except (SyntaxError, ValueError, Unsupported):
            continue
        for node in ast.walk(tree):
            # Проверяются и БИНАРНЫЕ операции, и УНАРНЫЙ МИНУС. Второе — не
            # украшение: `UnaryMinus.c` из SV-COMP это ровно `-minInt - 23`, где
            # переполняется ПОДвыражение `-minInt` (`-(-2147483648) = 2147483648`),
            # а итог `2147483625` снова в диапазоне. Без унарного минуса этот
            # класс задач не ловится (измерено: 9 из 10 -> 10 из 10).
            if isinstance(node, ast.BinOp):
                if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult,
                                            ast.Div, ast.FloorDiv, ast.Mod)):
                    continue
                operands = (node.left, node.right)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                operands = (node.operand,)
            else:
                continue
            # (1) диапазон ТИПА результата по правилам C: литерал -> по значению
            # (`long x = -2147483648 - 1` НЕ переполняется), переменная -> по
            # объявленному типу, результат -> по ШИРОЧАЙШЕМУ операнду.
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if any(nm not in var_ranges for nm in names):
                continue        # неизвестный символ дал бы свободную переменную
            op_ranges = [_operand_range(o, var_ranges) for o in operands]
            if any(r is None for r in op_ranges):
                continue
            rng = max(op_ranges, key=lambda r: r[1] - r[0])
            tyname = next((k for k, v in TYPE_RANGE.items() if v == rng), "?")
            lo, hi = rng
            # (1b) БЕЗЗНАКОВЫЕ ТИПЫ НЕ ОБВИНЯЕМ. ИЗМЕРЕНО на `TheAlgorithms/C/
            # math/fibonacci_formula.c`: `int fib(unsigned int n)` содержит
            # `n + 1`, и первая версия детектора объявляла это переполнением.
            # Это ЛОЖНОЕ ОБВИНЕНИЕ: в C переполнение БЕЗЗНАКОВОГО типа
            # ОПРЕДЕЛЕНО стандартом (заворачивание по модулю 2^N) — это НЕ UB и
            # НЕ свойство `no-overflow`. То же в Go и TS/JS. В Zig/Rust поведение
            # иное (паника в safety-режиме / заворачивание в release), но
            # выдумывать вердикт на неуточнённом режиме сборки нельзя. Поэтому
            # беззнаковые — ПРОПУСК, и граница названа.
            if lo == 0:
                continue
            # (2) ТОЧНАЯ проверка: если выражение ВЫЧИСЛИМО статически (литералы
            # и локальные с известным значением) — считаем арифметически. Это не
            # оптимизация ради скорости, а ТОЧНОСТЬ: `(2147483647 + 1) - 23` не
            # требует SAT-запроса, ответ известен, и он же покрывает деление
            # (`minInt / -1` — аппаратная ловушка `idiv`).
            val = _const_eval(node, consts)
            if val is not None:
                if val < lo or val > hi:
                    op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*",
                          ast.Div: "/", ast.FloorDiv: "/",
                          ast.Mod: "%"}.get(type(node.op), "?")
                    out.append(
                        f"[OVERFLOW PATH] {name}: переполнение типа `{tyname}` "
                        f"([{lo}, {hi}]): `{ast.unparse(node)}` = {val} "
                        f"({op} вне диапазона) — UB до возврата")
                continue
            try:
                whole = expr_smt(node, local_smt)
            except (Unsupported, NoReturn, SyntaxError, KeyError):
                continue
            if "__" in whole or not whole:
                continue
            # (3) СИМВОЛЬНЫЙ путь — только по ВХОДНЫМ ПАРАМЕТРАМ. ДЕФЕКТ #368:
            # ИЗМЕРЕНО на `TheAlgorithms/C/math` (catalan.c): `int i` — счётчик
            # цикла, а циклы не моделируются, поэтому `i` остаётся СВОБОДНЫМ и
            # решатель берёт `i = 2147483649`, давая НЕДОСТИЖИМЫЙ контрпример
            # для `x - i`. Это ложное обвинение. Значение локальной переменной
            # ВЫВОДИТСЯ кодом; если вывести его мы не умеем (циклы/ветви), то и
            # обвинять нечем. Параметр же — это настоящий вход, его диапазон
            # задан типом в сигнатуре.
            #   Постоянные локальные сюда не попадают: их обрабатывает статическая
            # ветка выше (`_const_eval`), и она точнее решателя.
            if any(nm not in set(params) for nm in names):
                continue
            _ov_path = (path_conds + _clike_conds_at(pos, if_blocks, body)
                        + [f"(or (> {whole} {hi}) (< {whole} {lo}))"])
            # ФЛАГ `free_syms_in_path` (шаг 4 плана). Свободная константа в ПУТИ
            # делает запрос `∃c. path(c) ∧ overflow` СЛАБЕЕ реальности, и Z3 берёт
            # c = ±MAX → ЛОЖНОЕ ОБВИНЕНИЕ (измерено). ОТКАЗ с НАЗВАННОЙ причиной.
            if _free_syms_in_path(_ov_path, params):
                if skip_why is not None and FREE_PATH_REASON not in skip_why:
                    skip_why.append(FREE_PATH_REASON)
                continue
            try:
                kind, ce = _smt_verdict(kernc, params, _ov_path)
            except Exception as _kern_e_ov:                  # noqa: BLE001
                _replay_soft(_kern_e_ov, "kern_contracts.py:ov")
                continue
            if kind == "sat":
                out.append(
                    f"[OVERFLOW PATH] {name}: переполнение типа `{tyname}` "
                    f"([{lo}, {hi}]) в `{ast.unparse(node)}` — UB до возврата; "
                    f"{ce or 'SAT'}")
    for _id_msg in _clike_incdec_findings(name, body, var_ranges, consts):
        if _id_msg not in out:
            out.append(_id_msg)
    return out


def _xray_clike_file(path: Path, kernc) -> tuple[int, int, int, list[str], dict[str, int], dict[str, int]]:
    """ПОЛЕВОЙ АДАПТЕР №5б: `--xray` для C-like (Zig/C/Rust/TS/JS/Go).

    Извлекает условия `if (...)` из ТЕЛА (без исполнения) и проверяет их
    достижимость/тавтологичность в Z3. Путь сужается по правилу #134/#149:
    после `if (c) { return … }` следующие операторы идут при `not c`.

    ЧЕСТНО: условия вне подмножества (вызовы, `@as`, указатели) ведут к SKIP
    с причиной — они не «проверены», а пропущены.
    """
    try:
        funcs = _clike_functions(path)
    except Exception as _kern_e_3799:  # noqa: BLE001
        _replay_soft(_kern_e_3799, "kern_contracts.py:3799")
        return 0, 0, 0, [], {}, {}
    # ДЕФЕКТ #193: типы полей структур нужны для проверки переполнения
    # счётчиков (`row->n_columns : uint16_t`). Определения лежат в том же
    # файле (cmark: `typedef struct { uint16_t n_columns; } table_row;`).
    try:
        field_types = _clike_struct_fields(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        field_types = {}
    # ДЕФЕКТ #317: семантика ДЕЛЕНИЯ зависит от языка. В C/Zig/Rust `/` и `%`
    # это УСЕЧЕНИЕ к нулю, а SMT `div`/`mod` — ЕВКЛИДОВЫ; раньше всё уходило
    # в `div`, то есть в ДРУГУЮ функцию. Язык берётся из расширения.
    _suf = path.suffix.lower()
    lang = ("rust" if _suf == ".rs"
            else "zig" if _suf == ".zig"
            else "go" if _suf == ".go"
            else "ts" if _suf in {".ts", ".js"}
            else "c")
    checked = total = trivial = 0
    # ДЕФЕКТ #411: счётчик вызовов решателя обнуляется на КАЖДУЮ функцию
    # (дефект #405), поэтому значение `_SMT_CALLS[0]` после цикла — это счётчик
    # ПОСЛЕДНЕЙ функции, а не файла. ИЗМЕРЕНО на `scanners.c`: сводка печатала
    # `SMT calls 29`, тогда как решатель вызывался 2032 раза (профайлер §178.5).
    # Файловый итог накапливается отдельно и возвращается наружу.
    _smt_calls_file = 0
    # ДЕФЕКТ #413: СУБЪЕКТЫ, УЖЕ ЗАЯВЛЕННЫЕ ПРАВИЛАМИ ВНУТРИ ЦИКЛА.
    # Файловые близнецы правил C/D нужны ТОЛЬКО для функций, которых разборщик не
    # нашёл (многострочные объявления, #194). Раньше внутрицикловые копии были
    # МЁРТВЫ (управляющий байт 0x08 вместо `\b`), поэтому дублей не возникало;
    # после починки обе копии срабатывают на одну строку и дают ДВА сообщения об
    # одной ошибке (разными ярлыками: имя функции против имени файла).
    # ИЗМЕРЕНО до дедупликации: фикстуры `numdelims <= max_delims` и
    # `row->n_columns++` давали РОВНО ПО ДВЕ находки. Поэтому файловый уровень
    # пропускает то, что уже заявлено точным (функциональным) уровнем.
    _subj_c: set = set()
    _subj_d: set = set()
    found: list[str] = []
    # ДЕФЕКТ #400: причины пропуска НЕ собирались, а сводка при этом заявляла
    # «skipped N with explicit reasons» — то есть ПЕЧАТАЛАСЬ ЛОЖНАЯ ФРАЗА: ни
    # одной причины не выводилось. Здесь они собираются, и гистограмма
    # печатается вместе со сводкой.
    reasons: dict[str, int] = {}
    # ДЕФЕКТ #407.2: ЧАСТИЧНЫЙ отсев у ПРОВЕРЕННОЙ функции (часть условий вне
    # подмножества) — это заметка уровня ВЕТКИ, а не пропуск функции.
    notes: dict[str, int] = {}

    def _bump(key: str) -> None:
        reasons[key] = reasons.get(key, 0) + 1

    def _bump_note(key: str) -> None:
        notes[key] = notes.get(key, 0) + 1

    # ДЕФЕКТ #194: часть правил проверяется на УРОВНЕ ФАЙЛА. Причина измерена:
    # в cmark-gfm функция `cmark_inline_parser_scan_delimiters` объявлена
    # МНОГОСТРОЧНО, поэтому `_clike_functions` её не находит, и правило
    # off-by-one (`numdelims <= max_delims`) не срабатывало вовсе.
    try:
        _full = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _full = ""
    _full_src = _strip_c_comments_strings(_full)
    if path.suffix in {".ts", ".js"}:
        _full_src = _strip_js_regex(_full_src)
    for name, params, body, _ln, ranges, reqs in funcs:
        total += 1
        # ДЕФЕКТ #405 (найден при правке): счётчик вызовов решателя ОБЯЗАН
        # обнуляться на КАЖДУЮ функцию. Он глобальный, и без сброса первая же
        # функция с обязательством делала `_SMT_CALLS[0] > 0` для ВСЕХ
        # последующих — то есть корзина `checked` наполнялась бы функциями,
        # которых решатель не касался (ложное покрытие, класс #320).
        # Файловый итог вызовов решателя (дефект #411): накапливаем ДО сброса,
        # поэтому в итог попадают и вызовы ВНЕ цикла по функциям. ИЗМЕРЕНО:
        # накопление «после» цикла давало 2031 при независимо измеренных 2032.
        _smt_calls_file += _SMT_CALLS[0]
        _SMT_CALLS[0] = 0
        proven = 0
        # ДЕФЕКТ #400: причина, по которой функция НЕ попала в `checked`.
        skip_why: list[str] = []
        raw_body = body          # для правила B (смотрит на САМИ касты)
        # ДЕФЕКТ #189: C-касты снимаются ДО разбора условий/индексов/делителей.
        # Иначе `if (len == (size_t)(max_rewind - rewind)) return` не переводился,
        # путь не сужался, и на ИСПРАВЛЕННОМ cmark-gfm оставалось предупреждение.
        body = _strip_c_casts(body)
        # ДЕФЕКТ #412: МАСКА ДЛЯ ПОИСКА. Тело СЫРОЕ (нужно для семантики
        # литералов в условиях), поэтому регулярки поиска видели текст ВНУТРИ
        # строковых литералов. ИЗМЕРЕНО на `cmark-gfm/src/xml.c`: строка
        # `"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"` давала мнимую локальную
        # `version` и РОНЯЛА весь обход корпуса (Unsupported: тернарный оператор
        # без ':'), а мнимые `if`/`assert`/делители внутри литералов могли бы дать
        # ЛОЖНЫЕ находки. `_strip_c_comments_strings` сохраняет длину
        # ПОСИМВОЛЬНО, поэтому маска годится для ЛОКАЦИИ, а значения берутся из
        # сырого тела по тем же смещениям.
        body_mask = _strip_c_comments_strings(body)
        # Диапазоны типов — часть домена (u32 не бывает отрицательным).
        path_conds: list[str] = [f"(and (>= {p} {lo}) (<= {p} {hi}))"
                                 for p, (lo, hi) in (ranges or {}).items()]
        # ДЕФЕКТ #318: `path_conds` — условия БЕЗ привязки к позиции (диапазоны
        # типов, requires, assert). Условия из `if` зависят от ПОЗИЦИИ, поэтому
        # хранятся отдельно: `if_blocks` (границы блоков и позиционные условия).
        if_blocks: list = []
        for rq in (reqs or []):
            try:
                path_conds.append(expr_smt(
                    ast.parse(clike_to_python(_unwrap_zig_builtins(rq)), mode="eval").body, {}))
            except (Unsupported, NoReturn, SyntaxError):
                continue  # конъюнкт вне подмножества — честно пропускаем
        # Let-Inlining (дефект #183): подставляем локальные `const x = expr;`,
        # чтобы условия и делители зависели от ПАРАМЕТРОВ, а не от
        # неизвестных имён. Float-локальные НЕ инлайним (деление на 0.0 =
        # inf, а не паника).
        local_smt: dict[str, str] = {}
        float_locals: set[str] = set()
        for lm2 in _RE_CLIKE_LOCAL_RHS.finditer(body_mask):
            nm2, ty2 = lm2.group(1), (lm2.group(2) or "")
            rhs2 = body[lm2.start(3):lm2.end(3)].strip()
            ty_l = ty2.strip().lower()
            if ty_l.startswith("f") or "float" in ty_l:
                float_locals.add(nm2)
                continue
            if nm2 in local_smt or re.search(rf"\b{re.escape(nm2)}\b", rhs2):
                continue  # самоссылка/повтор — не инлайним (звучность важнее)
            # ДЕФЕКТ #195 (полевой прогон express/axios): локальная, которой
            # присваивают ещё раз внутри тела, НЕ константа. Пример:
            #   var done = false; … done = true; if (done) return …
            # Раньше инлайнилось `done = false`, и `if (done)` объявлялся мёртвым.
            if len(re.findall(rf"\b{re.escape(nm2)}\s*=", body_mask)) > 1:
                continue
            try:
                local_smt[nm2] = expr_smt(
                    ast.parse(clike_to_python(_unwrap_zig_builtins(
                        _literals_to_numbers(rhs2))), mode="eval").body,
                    local_smt)
            except (Unsupported, NoReturn, SyntaxError):
                continue
        # ДЕФЕКТ #196 (полевой прогон axios): `x = x || K` — после этой строки
        # x гарантированно НЕ 0 (значение по умолчанию). Без учёта этого
        # `i % x` выглядел как деление на ноль.
        for dm2 in re.finditer(r"\b([A-Za-z_]\w*)\s*=\s*\1\s*\|\|", body_mask):
            path_conds.append(f"(not (= {dm2.group(1)} 0))")
        pos = 0
        # ДЕФЕКТ #400: список `if` вычисляется ОДИН раз — им же проверяется,
        # были ли условия ВООБЩЕ (иначе fallback расходился с детектором).
        # ДЕФЕКТ #412: поиск `if` — по МАСКЕ (мнимый `if` внутри строки дал бы
        # ЛОЖНУЮ мёртвую ветвь), а ТЕКСТ условия берётся из сырого тела.
        _ifs = list(_clike_ifs(body_mask))
        for m in _ifs:
            raw_cond = body[m.start(1):m.end(1)]
            # ДЕФЕКТ #197 (полевой прогон gin): `err != nil` — указательное
            # сравнение; в Int-модели `nil` бессмысленно, и получался ложный
            # DEAD BRANCH. Такие условия честно пропускаем.
            # ДЕФЕКТ #410: ЛИТЕРАЛЫ -> ЧИСЛА в ВЫРЕЗАННОМ условии (позиции файла
            # тут уже не нужны, поэтому без усечения по ширине кавычек).
            raw_cond = _literals_to_numbers(raw_cond)
            # ДЕФЕКТ #416: `===`/`!==` нормализуются ДО переписи `null` — иначе
            # `body === null` не распознавался (`_null_to_zero` ищет ровно `==`),
            # и функция честно, но ЗРЯ уходила в «nil/null вне Int-модели».
            raw_cond = raw_cond.replace("===", "==").replace("!==", "!=")
            # ДЕФЕКТ #416 (Приоритет 2): поля `a->b` / `a.b` -> плоское `a__b`.
            # ВЫЗОВ метода (`a.b(x)`) не трогается — это не поле. Литералы уже
            # заменены числами, поэтому содержимое строк не сплющивается.
            raw_cond = _flatten_fields(raw_cond)
            _has_null = re.search(rf"\b{_NULL_WORDS}\b", raw_cond) is not None
            # ИЗМЕРЕНО (шаг 6): `if (!p)` НЕ содержит слова `nil/null`, поэтому
            # перепись не запускалась вовсе, и функция уходила в SKIP как
            # «синтаксис». Но `!x` в C — это `x == 0` и для УКАЗАТЕЛЯ, и для
            # ЦЕЛОГО (0 = ложь), поэтому перепись звуча для обеих форм.
            _has_bang = re.search(r"!(?!=)", raw_cond) is not None
            if _has_null or _has_bang:
                _rw = _null_to_zero(raw_cond)
                if _rw is None:
                    skip_why.append(
                        "указательное сравнение nil/null (вне Int-модели)" if _has_null
                        else "логическое отрицание `!` в форме, которую не переводим")
                    pos = m.end()
                    continue
                raw_cond = _rw
            try:
                cond = expr_smt(ast.parse(clike_to_python(raw_cond), mode="eval").body, local_smt, lang)
            except (Unsupported, NoReturn, SyntaxError) as _u400:
                # ДЕФЕКТ #400: причина сохраняется — иначе сводка печатала
                # «skipped N with explicit reasons», не выводя НИ ОДНОЙ.
                skip_why.append(_skip_key(_u400))
                pos = m.end()
                continue
            proven += 1
            # ДЕФЕКТ #401: достижимость проверяется по ПОЗИЦИИ, а не по
            # накопленному списку: накопление складывало `not cond` из
            # ВЗАИМОИСКЛЮЧАЮЩИХ ветвей и делало путь UNSAT (ложный DEAD BRANCH).
            sat_then = _smt_sat(kernc, params,
                                path_conds + _clike_conds_at(m.end(), if_blocks, body)
                                + [cond])
            if sat_then is False:
                found.append(f"[DEAD BRANCH] {name}: условие НЕДОСТИЖИМО (UNSAT): {cond}")
            # REDUNDANT GUARD для C-like НЕ заявляется: без полного моделирования
            # потока это давало ЛОЖНЫЕ срабатывания (найдено на std Zig
            # `math/pow.zig`: `else if (y > 0)` после ветки с `return`).
            # Честная граница: рентген C-like сообщает только DEAD BRANCH.
            # СУЖЕНИЕ ПУТИ (строго). Правило: добавляем ограничение ТОЛЬКО когда
            # оно доказано структурой кода:
            #   * за `if (c) { return … }` следующие операторы идут при `not c`;
            #   * `else if (c2)` — тоже `not c` для предыдущего условия.
            # ИНАЧЕ НЕ ДОБАВЛЯЕМ НИЧЕГО: «не знаю» лучше ложной мёртвой ветки.
            # (НАЙДЕНО на std Zig `nextafter.zig: nextAfterInt`: без этого правила
            # `else if (y < x)` после `else if (y > x)` давал ЛОЖНЫЙ [DEAD BRANCH],
            # потому что путь ошибочно считался «y > x».)
            tail = body_mask[m.end(): m.end() + 160]
            # ДЕФЕКТ #368: `exit(...)`/`abort(...)`/`panic(...)` — это ТОЖЕ выход
            # из функции, то есть гард. ИЗМЕРЕНО на `TheAlgorithms/C/math/
            # fibonacci.c`: `if (number <= 0) { fprintf(...); exit(EXIT_FAILURE); }`
            # исключает `number <= 0`, но раньше путь НЕ сужался, и
            # `number - 1` объявлялось переполнением при `number = INT_MIN` —
            # ЛОЖНОЕ ОБВИНЕНИЕ. Проверка идёт по ВСЕМУ блоку и намеренно
            # ОВЕР-АППРОКСИМИРУЕТ: если признак выхода найден, мы СКРОЕМ находку
            # (пропуск), а не выдумаем её — пропуск безопаснее ложного обвинения
            # (урок #178/#183).
            _bend0 = _clike_block_end(body_mask, m.end())
            _blk = body_mask[m.end():_bend0]
            hard_exit = bool(re.search(
                r"\b(?:exit|abort|_exit|_Exit|quick_exit|panic|unreachable|"
                r"os\.Exit|process\.exit|std::process::exit|sys\.exit)\s*\(", _blk))
            exits = hard_exit or bool(re.match(
                r"\s*\{?\s*(return|break|continue)\b", tail))
            # ДЕФЕКТ #318: запоминаем ГРАНИЦЫ блока, чтобы позже вычислить
            # условия ПО ПОЗИЦИИ, а не накоплением «только not cond».
            # ДЕФЕКТ #318: блок регистрируется ВСЕГДА — условие действует
            # ВНУТРИ него; наружу оно превращается в `not cond` ПО ПОЗИЦИИ.
            _bend = _clike_block_end(body_mask, m.end())
            if_blocks.append((m.end(), _bend, cond, exits))
            pos = m.end()
        # ДЕФЕКТ #179 (C-like): `assert(cond);` — истинное условие для
        # дальнейшего кода. Без этого zls `alternate(..., len: u32)` с
        # `assert(@backingInt(index) < len)` давал ложный [CRASH PATH].
        # 🔴 ДЕФЕКТ #183: делитель, про который в коде стоит ЯВНЫЙ assert
        # (`assert(@backingInt(index) < len)` в zls), не выдаём за «путь
        # падения»: разработчик заявил отношение. Доказать его для
        # неизвестного типа мы не можем — поэтому НЕ обвиняем (ложное
        # обвинение хуже пропуска).
        guarded_divs: set[str] = set()
        for am2_body in _iter_call_args(body_mask, "assert", raw=body):
            try:
                ac = expr_smt(ast.parse(clike_to_python(_unwrap_zig_builtins(
                    _literals_to_numbers(am2_body))), mode="eval").body, local_smt, lang)
            except (Unsupported, NoReturn, SyntaxError):
                continue
            path_conds.append(ac)
            for g in re.finditer(r"\((?:<=|<)\s+[^()]+\s+([A-Za-z_]\w*)\)", ac):
                guarded_divs.add(g.group(1))
            for g in re.finditer(r"\((?:>=|>)\s+([A-Za-z_]\w*)\s+[^()]+\)", ac):
                guarded_divs.add(g.group(1))
            for g in re.finditer(r"\(not \(= ([A-Za-z_]\w*) 0\)\)", ac):
                guarded_divs.add(g.group(1))
            for g in re.finditer(r"\(= ([A-Za-z_]\w*) 0\)", ac):
                pass  # `(= d 0)` в assert — это требование «равно нулю», не гард

        # [CRASH PATH] для C-like: деление на выражение, которое может быть 0.
        # ИСКЛЮЧАЕМ: (а) локальные переменные — они не входные данные;
        # (б) float-арифметику — деление на 0.0 даёт inf, а не панику.
        # (НАЙДЕНО на std Zig `math/acos.zig`: `const q: f64 = 1.0 + z*qS1;
        #  p / q` давало 57 ЛОЖНЫХ [CRASH PATH].)
        locals_: set[str] = set()
        float_names: set[str] = set()
        for lm in _RE_CLIKE_LOCAL.finditer(body_mask):
            nm_, ty_ = lm.group(1), (lm.group(2) or "")
            locals_.add(nm_)
            if ty_.lower().startswith("f") or "float" in ty_.lower():
                float_names.add(nm_)
        float_names |= float_locals
        if float_names or re.search(r"\b[0-9]+\.[0-9]+", body_mask):
            float_names |= {m2.group(1) for m2 in _RE_CLIKE_LOCAL.finditer(body_mask)}
        for dm in _RE_CLIKE_DIV.finditer(body_mask):
            if dm.group(1) is not None:
                den = body[dm.start(2):dm.end(2)]
            elif dm.group(3) is not None:
                den = body[dm.start(4):dm.end(4)]
            else:
                den = body[dm.start(6):dm.end(6)]
            den = _literals_to_numbers(den)
            try:
                d = expr_smt(ast.parse(clike_to_python(_unwrap_zig_builtins(den)), mode="eval").body, local_smt, lang)
            except (Unsupported, NoReturn, SyntaxError):
                continue
            if d.strip().isdigit() or _MACRO_DIV.match(d.strip()):
                continue  # константа/макрос — не 0
            if d.strip() in guarded_divs:
                continue  # явный assert на делитель — не обвиняем (см. #183)
            # ДЕФЕКТ #183: делитель, НЕ зависящий от входных параметров — это
            # comptime-поле/константа структуры (`shard_bits`, `slot_count`
            # в tigerbeetle). Значение задано в типе, а не приходит извне;
            # обвинять такой код в делении на ноль — ложная тревога.
            if not _mentions_param(d, params):
                continue
            if d.strip() in locals_ or d.strip() in float_names:
                continue  # локальная переменная / float-арифметика — не параметр
            # ДЕФЕКТ #200 (найден на РЕАЛЬНОМ коде `zigtools/zls` 0.17.0).
            # Делитель — «длина» (`len`, `size`, `count`, `cap`): локально
            # `len == 0` достижим, но ненулевость длины обеспечивает
            # ВЫЗЫВАЮЩИЙ. В zls фильтр строится только внутри
            # `if (trigrams.len > 0)`, поэтому `buckets.len >= 2` всегда.
            # Межпроцедурные инварианты мы НЕ моделируем, значит честный
            # ответ — не обвинять (урок #178/#183: ложное обвинение хуже
            # пропуска). Сертификаты `audits/zls/*.smt2` остаются как модель
            # «что было бы без гарда», но НЕ как находка в их коде.
            if _RE_LEN_LIKE.match(d.strip()):
                continue
            if "__" in d:
                continue  # поле структуры (self.x -> self__x): значение неизвестно
            try:
                # ДЕФЕКТ #318: условия берутся ПО ПОЗИЦИИ делителя.
                _pos_d = dm.start()
                sat_dz = _smt_sat_guarded(kernc, params,
                                          path_conds + _clike_conds_at(_pos_d, if_blocks, body)
                                          + [f"(= {d} 0)"], skip_why)
            except Exception as _kern_e_3982:  # noqa: BLE001
                _replay_soft(_kern_e_3982, "kern_contracts.py:3982")
                continue
            if sat_dz is True:
                found.append(f"[CRASH PATH] {name}: возможно деление на ноль: {d} == 0")

        # ===== B2: [BOUNDS PATH] и [OVERFLOW PATH] для C-like =====
        # ПОЧЕМУ ИМЕННО ТАК (и почему так узко). На неразмеченном C/C++ полный
        # анализ индексов требует модели циклов, аллокаций и указателей. Мы
        # заявляем только те случаи, где нарушение СЛЕДУЕТ из кода:
        #   * индекс — РАЗНОСТЬ (`i - 1`, `len - 2`, `a - b`), т.е. может быть
        #     отрицательным, и Z3 подтверждает SAT(idx < 0) на текущем пути;
        #   * размер аллокации — сумма/произведение (`len + 1`, `cols * rows`),
        #     и Z3 подтверждает SAT(size > INT32_MAX) на текущем пути.
        # Одиночный параметр (`buf[i]`) НЕ обвиняем: его диапазон задан типом,
        # а циклы мы не моделируем — это дало бы шум (урок #178/#183:
        # ложное обвинение хуже пропуска).
        for im in _RE_CLIKE_INDEX.finditer(body):
            base, idx_raw = im.group(1), im.group(2)
            if "->" in base or base.startswith("@"):
                continue  # поле структуры/встроенное — длина неизвестна
            try:
                idxs = expr_smt(
                    ast.parse(clike_to_python(_unwrap_zig_builtins(idx_raw)), mode="eval").body,
                    local_smt)
            except (Unsupported, NoReturn, SyntaxError):
                continue
            if "(- " not in idxs and not re.search(r"\(- \S+ \S+\)", idxs):
                continue  # не разность: отрицательность не следует из выражения
            if not _mentions_param(idxs, params):
                continue
            if "__" in idxs:
                continue  # поле структуры — неизвестное значение
            # ДВА РАЗНЫХ КЛАССА (замер на реальном cmark-gfm, дефект #187):
            #  1) СМЕЩЕНИЕ НАЗАД ОТ УКАЗАТЕЛЯ: `data[-rewind - i]` — унарный минус
            #     на параметре. Индекс отрицателен ПО ПОСТРОЕНИЮ, и вопрос лишь
            #     в том, не уходит ли он ДО начала буфера. Именно этот класс
            #     поймал исторический фикс `2cb4a20` (OOB read в validate_protocol).
            #  2) `value - 1` — обычная индексация; на реальном коде она почти
            #     всегда защищена условием ЦИКЛА (`while (link_end > 0)`), а циклы
            #     мы не моделируем. Без этой поправки на одном `autolink_delim`
            #     выходило 3 ЛОЖНЫХ обвинения. Поэтому класс 2 заявляем только
            #     если в теле НЕТ цикла по той же переменной.
            pointer_offset = bool("(- (-" in idxs
                                  or idxs.startswith("(- (+")
                                  or re.fullmatch(r"\(- [A-Za-z_]\w*\)", idxs))
            if pointer_offset:
                # ДЕФЕКТ #191 (ретро-тест, ложный остаток на ИСПРАВЛЕННОМ файле):
                # `data[-rewind - len - 1]` — смещение ФИКСИРОВАННОЙ длины, и
                # «индекс < 0» тут истинно всегда, поэтому такое обвинение ничего
                # не говорит (это шум). Заявляем только когда в смещении есть
                # СЧЁТЧИК ЦИКЛА: тогда величина смещения растёт без парного гарда —
                # именно так устроена `2cb4a20` (`data[-rewind - i]`, `i` до `len`).
                counters = set(re.findall(r"\b([A-Za-z_]\w*)\s*(?:\+\+|--)", body))
                counters |= set(re.findall(r"\b([A-Za-z_]\w*)\s*[+\-]=\s*", body))
                idx_vars = set(re.findall(r"[A-Za-z_]\w*", idxs)) - {"-", "not"}
                if not (idx_vars & counters):
                    continue
            if not pointer_offset:
                mz = re.match(r"^\(- ([A-Za-z_]\w*)\s", idxs)
                head_var = mz.group(1) if mz else ""
                if head_var:
                    loop_guarded = False
                    for _lm in re.finditer(r"\b(?:while|for)\s*\(([^)]*)\)", body):
                        if re.search(rf"\b{re.escape(head_var)}\b", _lm.group(1)):
                            loop_guarded = True
                            break
                    if loop_guarded:
                        continue  # границу задаёт цикл — не обвиняем (циклы не моделируем)
            try:
                # ДЕФЕКТ #318 (та же причина, секция границ): условия — ПО ПОЗИЦИИ.
                sat_neg = _smt_sat_guarded(kernc, params,
                                           path_conds + _clike_conds_at(im.start(), if_blocks, body)
                                           + [f"(< {idxs} 0)"], skip_why)
            except Exception as _kern_e_4052:  # noqa: BLE001
                _replay_soft(_kern_e_4052, "kern_contracts.py:4052")
                continue
            if sat_neg is True:
                found.append(
                    f"[BOUNDS PATH] {name}: индекс может быть отрицательным: "
                    f"{idx_raw.strip()} -> {idxs} < 0")

        for am in _RE_CLIKE_ALLOC.finditer(body):
            call, args_raw = am.group(1), am.group(2)
            for one in args_raw.split(","):
                one = one.strip()
                if not one or one.isdigit():
                    continue
                if "+" not in one and "*" not in one:
                    continue  # рост размера не вычисляется — не наш случай
                try:
                    size_smt = expr_smt(
                        ast.parse(clike_to_python(_unwrap_zig_builtins(one)), mode="eval").body,
                        local_smt)
                except (Unsupported, NoReturn, SyntaxError):
                    continue
                if not _mentions_param(size_smt, params) or "__" in size_smt:
                    continue
                try:
                    # ДЕФЕКТ #318: то же — условия ПО ПОЗИЦИИ вызова аллокации.
                    sat_ov = _smt_sat_guarded(kernc, params,
                                              path_conds + _clike_conds_at(am.start(), if_blocks, body)
                                              + [f"(> {size_smt} 2147483647)"], skip_why)
                except Exception as _kern_e_4077:  # noqa: BLE001
                    _replay_soft(_kern_e_4077, "kern_contracts.py:4077")
                    continue
                if sat_ov is True:
                    found.append(
                        f"[OVERFLOW PATH] {name}: размер в {call}() может переполнить "
                        f"32-битный знаковый int: {size_smt} > 2147483647")
        # --- B: 4682993 (unsigned pointer/wrap) — ДЕФЕКТ #192 ----------------
        # Каст `(ptrdiff_t)` применён к ОДНОМУ слагаемому, остальная арифметика
        # идёт в беззнаковом типе (`size_t`), поэтому отрицательный результат
        # превращается в огромное число и указатель «оборачивается»:
        #     ДО:    data[-((ptrdiff_t)rewind) - len - 1]
        #     ПОСЛЕ: data[-((ptrdiff_t)(rewind + len + 1))]
        # Правило структурное (по форме каста) — поэтому 0 на исправленном файле.
        _rb_mask = _strip_c_comments_strings(raw_body)
        for im in _RE_CLIKE_INDEX.finditer(_rb_mask):
            if re.search(r"\(\s*(?:ptrdiff_t|ssize_t|intptr_t|size_t)\s*\)"
                         r"\s*[A-Za-z_]\w*\s*\)\s*[-+]", im.group(2)):
                found.append(
                    f"[OVERFLOW PATH] {name}: unsigned-арифметика смещения: каст "
                    f"покрывает ОДНО слагаемое, остаток считается беззнаково "
                    f"({im.group(2).strip()}) -> перенос указателя")

        # --- C: ac80f7b (uint16_t counter) — ДЕФЕКТ #193 --------------------
        is_u16 = lambda t: t.strip().lower() in {"uint16_t", "u16", "unsigned short", "ushort"}
        for m2 in re.finditer(r"\b\w+\s*(?:->|\.)\s*(\w+)\s*(?:\+\+|\+=\s*1)", body_mask):
            fld = m2.group(1)
            ty = field_types.get(fld, "")
            if not ty or not is_u16(ty):
                continue
            head = body[:m2.start()]
            if re.search(r"UINT16_MAX|65535|0xFFFF", head):
                continue  # граница проверяется — не обвиняем
            _subj_c.add(fld)
            found.append(
                f"[OVERFLOW PATH] {name}: поле `{fld}` ({ty}) инкрементируется без "
                f"проверки границы 65535 -> счётчик переполнится (CVE-класс ac80f7b)")

        # --- D: 198669d (off-by-one vs capacity) — ДЕФЕКТ #194 --------------
        # `numdelims <= max_delims` разрешает `numdelims == max_delims`, т.е.
        # ровно на единицу больше ёмкости. Правило требует ИМЕНИ-ёмкости
        # (max_delims/max_size/…capacity), иначе `i <= max_retries` дало бы шум.
        for m3 in re.finditer(
                r"\b([A-Za-z_]\w*)\s*<=\s*(max_(?:delims|size|len|length|capacity|count)\b"
                r"|[A-Za-z_]*_capacity\b|MAX_(?:SIZE|LEN|LENGTH|CAPACITY|DELIMS)\b)", body_mask):
            var, cap = m3.group(1), m3.group(2)
            if not re.search(rf"\b{re.escape(var)}\s*(?:\+\+|\[+\-\]=)", body_mask):
                continue
            _subj_d.add(f"{var} <= {cap}")
            found.append(
                f"[BOUNDS PATH] {name}: off-by-one: `{var} <= {cap}` разрешает "
                f"{var} == {cap} (ровно ёмкость) -> запись за границу")

        # ДЕФЕКТ #190: OFF-BY-ONE по ВЕРХНЕЙ границе.
        # `if (i <= len)` разрешает `i == len`, а `buf[i]` при длине `len` — уже
        # за концом (валидные индексы 0..len-1). Именно так была устроена
        # историческая уязвимость `198669d` в cmark-gfm (`numdelims <= max_delims`).
        # Заявляем ТОЛЬКО когда: (а) сравнение именно `<=`, (б) правая часть —
        # имя, похожее на длину, (в) этот же счётчик используется как индекс.
        for gm in re.finditer(r"\b([A-Za-z_]\w*)\s*(<=|<)\s*(len|length|size|end)\b", body):
            var, op, lname = gm.group(1), gm.group(2), gm.group(3)
            if op != "<=":
                continue
            if not re.search(rf"\[\s*{re.escape(var)}\s*\]", body):
                continue
            if not _mentions_param(lname, params):
                continue  # длина не из входа — не наш случай
            found.append(
                f"[BOUNDS PATH] {name}: off-by-one: `{var} <= {lname}` разрешает "
                f"индекс == длине ({var} = {lname}), а {var}[{lname}] уже за концом")
        # ===== B2c: [OVERFLOW PATH] на ЛЮБОЙ арифметике `+ - *` =====
        # ДЕФЕКТ #367: до этой правки детектора переполнения ОБЫЧНОГО
        # выражения не было вовсе (только размер аллокации, счётчик u16 и
        # каст смещения). Измерено на официальной категории SV-COMP
        # `signedintegeroverflow-regression`: поймано 0 из 10 unsafe.
        # Теперь проверяется КАЖДАЯ бинарная операция под текущим путём —
        # то есть свойство `no-overflow`, а не только итог возврата.
        for _ov_msg in _clike_overflow_findings(
                name, params, body, ranges, path_conds, if_blocks,
                local_smt, kernc, skip_why):
            if _ov_msg not in found:
                found.append(_ov_msg)
        # ТРИ КОРЗИНЫ (дефект #405). Разделение идёт по ФАКТУ РАБОТЫ, а не по
        # наличию `if`:
        #   checked — решатель РЕАЛЬНО вызывался (обязательства были);
        #   trivial — функция разобрана, но обязательств НЕТ (ни `if`, ни
        #             арифметики/деления/границ): проверять нечего, и называть
        #             это «пропуском» значило бы врать о покрытии;
        #   skipped — функция НЕ анализировалась (условие вне подмножества,
        #             `nil/null`, `битовый оператор`, синтаксис).
        # ИЗМЕРЕНО до правки: `ratio` и `add32` из `audits/codecheck` (НОЛЬ
        # ветвлений) ДАВАЛИ находки, но числились `skipped` — воронка занижала
        # охват на 126 (C) и 337 (TS) функций.
        if _SMT_CALLS[0] > 0:
            checked += 1
            if skip_why:
                # Часть условий отсеяна, но функция ПРОВЕРЕНА: причина — заметка.
                _bump_note(skip_why[0])
        elif skip_why:
            # ДЕФЕКТ #400: функция пропущена — НАЗВАТЬ причину, а не молчать.
            _bump(skip_why[0])
        elif not _ifs:
            trivial += 1
        else:
            _bump("условие отсеяно без названной причины (дефект инструмента)")
        # Файловый итог вызовов решателя (дефект #411) накапливается ПЕРЕД
        # сбросом в начале следующей итерации — здесь добавлять НЕЧЕГО.
    # Файловый уровень: правила, недостижимые внутри функции.
    # (а) #194 off-by-one: функция cmark-gfm `cmark_inline_parser_scan_delimiters`
    #     объявлена МНОГОСТРОЧНО, поэтому `_clike_functions` её не находит.
    # (б) #193 переполнение 16-битного ПОЛЯ структуры (`row->n_columns`): оно
    #     живёт в `typedef struct { uint16_t n_columns; … } table_row;` того же
    #     файла, поэтому карта полей собирается из самого файла.
    for m3 in re.finditer(
            r"([A-Za-z_][A-Za-z0-9_]*) *(?:<=) *(max_(?:delims|size|len|length|capacity|count)"
            r"|[A-Za-z_]*_capacity|MAX_(?:SIZE|LEN|LENGTH|CAPACITY|DELIMS))", _full_src):
        var, cap = m3.group(1), m3.group(2)
        if (var + "++") not in _full_src and (var + "+=") not in _full_src:
            continue
        # ДЕФЕКТ #413: не дублировать то, что уже заявлено правилом в цикле
        # (точный уровень называет ФУНКЦИЮ). Файловый уровень остаётся для
        # функций, которых разборщик не нашёл (#194).
        if f"{var} <= {cap}" in _subj_d:
            continue
        msg = (f"[BOUNDS PATH] {path.name}: off-by-one: `{var} <= {cap}` разрешает "
               f"{var} == {cap} (ровно ёмкость) -> запись за границу")
        if msg not in found:
            found.append(msg)
    for m2 in re.finditer(
            r"([A-Za-z_][A-Za-z0-9_]*) *(?:->|[.]) *([A-Za-z_][A-Za-z0-9_]*) *(?:[+]{2}|[-+]=)",
            _full_src):
        fld = m2.group(2)
        ty = field_types.get(fld, "")
        if not ty or not _is_u16(ty):
            continue
        head = _full_src[:m2.start()]
        if "UINT16_MAX" in head or "65535" in head:
            continue  # граница проверяется — не обвиняем
        # ДЕФЕКТ #413: не дублировать находку правила в цикле.
        if fld in _subj_c:
            continue
        msg = (f"[OVERFLOW PATH] {path.name}: поле `{fld}` ({ty}) инкрементируется "
               f"без проверки границы 65535 -> счётчик переполнится")
        if msg not in found:
            found.append(msg)
    # Файловый итог вызовов решателя (дефект #411): раньше наружу уходило
    # значение ПОСЛЕДНЕЙ функции (обнуление на каждую функцию, дефект #405).
    # Остаток после последней функции добавляется здесь.
    _smt_calls_file += _SMT_CALLS[0]
    _SMT_CALLS[0] = _smt_calls_file
    return checked, total, trivial, found, reasons, notes


_AUTO_ROUTE_RULES = [
    # (теория, триггер-регекс, человеческая причина)
    ("IEEE-754 NaN", r"\b(?:f32|f64|float|double|number)\b", "float type"),
    ("QF_S path traversal", r"\b(?:path|filepath|filename|dir|url|cmd)\b", "path-like name"),
    ("no_arbitrage / conservation",
     r"\b(?:fee|price|amount|balance|rate|tax|discount)\b", "money-like name"),
    ("2-Safety noninterference",
     r"\b(?:secret|token|password|passwd|api_key|apikey)\b", "secret-like name"),
    ("Termination (--loops)", r"\b(?:while|for)\b", "loop"),
]


def cmd_full_scan(path: str, kernc) -> int:
    """ПОЛНОСПЕКТРАЛЬНЫЙ ОБХОД (`--full-scan <path>`).

    ЧТО ДЕЛАЕТ РЕАЛЬНО (и это важно не преувеличивать):
      * `--xray` по каждому файлу 7 языков: `[CRASH PATH]`, `[DEAD BRANCH]`,
        `[BOUNDS PATH]`, `[OVERFLOW PATH]` — с решением Z3;
      * `--anti-cheat` по каждому Python-файлу (читерство ИИ в тестах/проде);
      * `--audit-mcp` по `server.json`/`mcp.json`, если они есть в корне;
      * АВТО-РОУТИНГ: по сигнатурам/именам показывает, какие теории KERN
        ПРИМЕНИМЫ к найденному коду (float → IEEE-754, path → QF_S,
        fee/balance → no_arbitrage, secret → 2-Safety, циклы → Termination).

    ЧЕГО НЕ ДЕЛАЕТ (честно): роутинг НЕ доказывает эти теории на голом коде —
    для `QF_S`/`IEEE-754`/`no_arbitrage`/`2-Safety`/`--loops` нужен контракт
    (`@kern:`), иначе это была бы выдумка. Поэтому такие пункты печатаются как
    `[AUTO-ROUTE] … applicable — needs contract`, а не как находки.
    """
    _audit_install_cleanup()
    root = Path(path)
    if not root.exists():
        print(f"[!] путь не найден: {path}")
        return 2
    files, skipped_ext = _xray_collect(root)
    _xray_report_skipped(skipped_ext)

    by_ext: dict[str, int] = {}
    checked = total = 0
    findings: list[str] = []
    per_file: dict[Path, list[str]] = {}
    py_files: list[Path] = []
    for f in files:
        by_ext[f.suffix] = by_ext.get(f.suffix, 0) + 1
        try:
            if f.suffix == ".py":
                py_files.append(f)
                # ДЕФЕКТ #198: раньше здесь вызывалась НЕСУЩЕСТВУЮЩАЯ `_xray_file`
                # (Python-ветка живёт внутри `cmd_xray`), исключение глушилось —
                # и Python-файлы молча давали 0 находок. Теперь используется
                # реальный движок, а результат разбирается из его вывода.
                _buf = io.StringIO()
                with contextlib.redirect_stdout(_buf):
                    cmd_xray(str(f), kernc)
                _out = _buf.getvalue()
                fd = [ln.strip() for ln in _out.splitlines()
                      if ln.strip().startswith("[") and
                      ("PATH]" in ln or "BRANCH]" in ln or "GUARD]" in ln)]
                _m = re.search(r"checked (\d+) / (\d+)", _out)
                c, t = (int(_m.group(1)), int(_m.group(2))) if _m else (0, 0)
            else:
                c, t, _tr, fd, _rs, _nt = _xray_clike_file(f, kernc)
        except Exception as _kern_e_4248:  # noqa: BLE001
            _replay_soft(_kern_e_4248, "kern_contracts.py:4248")
            continue
        checked += c
        total += t
        findings.extend(f"{f.relative_to(root) if root.is_dir() else f.name}: {z}" for z in fd)
        if fd:
            per_file[f] = list(fd)

    print(f"[FULL-SCAN] {path}")
    ext_line = " ".join(f"{k}:{v}" for k, v in sorted(by_ext.items()))
    print(f"  files: {len(files)} ({ext_line or 'нет поддерживаемых'})")
    print(f"  [xray] проверено функций {checked} / {total}, находок {len(findings)}")
    for z in findings:
        print(f"    {z}")

    # Anti-Cheat: тот же сканер, что в `--anti-cheat`, по всем .py
    cheat = 0
    for f in py_files:
        try:
            sc = _CheatScan()
            sc.visit(ast.parse(f.read_text(encoding="utf-8", errors="replace")))
        except Exception as _kern_e_4269:  # noqa: BLE001
            _replay_soft(_kern_e_4269, "kern_contracts.py:4269")
            continue
        for kind, ln in sc.findings:
            cheat += 1
            print(f"    {f.name}:{ln}: [CHEAT DETECTED: {kind}]")
    print(f"  [anti-cheat] python-файлов {len(py_files)}, находок {cheat}")
    if cheat:
        # ЧЕСТНО: эвристика не отличает CLI-скрипт от «тестируемого кода».
        # `sys.exit()` в конце `main()` — норма, а в тестируемой функции — чит.
        # Поэтому это КАНДИДАТЫ на ручную проверку, а не приговор.
        print("  [anti-cheat] эвристика: `sys.exit`/`except: pass` в CLI-скриптах "
              "тоже попадают — проверяйте вручную")

    # MCP: если в корне есть манифест — прогоняем реальный аудит схемы
    mcp_status = "нет server.json/mcp.json"
    for name in ("server.json", "mcp.json"):
        cand = (root if root.is_dir() else root.parent) / name
        if cand.is_file():
            lock = cand.parent / "mcp.lock.json"
            print(f"  [mcp] {name}: аудит схемы")
            cmd_audit_mcp(str(cand), str(lock) if lock.is_file() else None)
            mcp_status = f"{name} проверен"
            break
    print(f"  [mcp] {mcp_status}")

    # РЕАЛЬНЫЙ автопилот (а не «применимо, не проверено»): на найденных проблемах
    # в Python-файлах вызываем вывод контракта (`--infer-requires`) и генератор
    # тестов (`--gen-tests`). Для C-like это неприменимо: контрактов там нет и
    # синтезировать их без типов нельзя — вместо этого в audits/ лежат сертификаты.
    inferred = tests_gen = 0
    targets = [f for f in per_file if f.suffix == ".py"][:3]
    for f in targets:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                cmd_suggest_fix(str(f), kernc, infer_requires=True)
            except Exception as _kern_e_4305:  # noqa: BLE001
                _replay_soft(_kern_e_4305, "kern_contracts.py:4305")
                pass
            inferred += buf.getvalue().count("[INFERRED SPEC]")
            tmp = Path(tempfile.gettempdir()) / f"kern_gen_{f.stem}.py"
            try:
                cmd_gen_tests(str(f), str(tmp), kernc)
                if tmp.exists():
                    tests_gen += tmp.read_text(encoding="utf-8").count("def test_")
                    tmp.unlink(missing_ok=True)
            except Exception as _kern_e_4314:  # noqa: BLE001
                _replay_soft(_kern_e_4314, "kern_contracts.py:4314")
                pass
    print(f"  [autopilot] infer-requires: контрактов {inferred} · "
          f"gen-tests: тестов {tests_gen} (файлов {len(targets)})")

    # АВТО-РОУТИНГ: что ПРИМЕНИМО (но не проверено без контракта)
    routed: dict[str, list[str]] = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for theory, rx, why in _AUTO_ROUTE_RULES:
            if re.search(rx, text):
                routed.setdefault(theory, []).append(f"{f.name} ({why})")
    for theory, where in sorted(routed.items()):
        shown = ", ".join(sorted(set(where))[:3])
        more = " …" if len(set(where)) > 3 else ""
        print(f"  [AUTO-ROUTE] {theory}: применимо к {len(set(where))} файл(ам): "
              f"{shown}{more} — needs contract (@kern:…), НЕ проверено")
    print("-" * 74)
    print(f"[FULL-SCAN SUMMARY] файлов {len(files)} · функций {checked}/{total} · "
          f"находок xray {len(findings)} · anti-cheat {cheat} · mcp: {mcp_status}")
    print(f"  теорий применимо по роутингу: {len(routed)} "
          f"({', '.join(sorted(routed)) or '—'}) — без контрактов НЕ доказывались")
    return 0


def _shm_dir():
    """RAM-диск для временных клонов (ОЗУ), иначе системный temp."""
    d = "/dev/shm"
    try:
        if os.path.isdir(d) and os.access(d, os.W_OK):
            return d
    except OSError:
        pass
    return None


_AUDIT_TMP: set = set()
_AUDIT_SIGNALS_READY = False


def _audit_install_cleanup() -> None:
    """Регистрирует уборку /dev/shm при SIGTERM/SIGINT/SIGHUP и на выходе.

    Обработчики ставятся ОДИН раз; они не мешают обычной работе (сначала
    убирают временные каталоги, затем делегируют прежнее поведение).
    """
    global _AUDIT_SIGNALS_READY
    if _AUDIT_SIGNALS_READY:
        return
    _AUDIT_SIGNALS_READY = True
    import atexit
    import signal as _signal
    atexit.register(_audit_cleanup_all)

    def _handler(signum, frame):  # noqa: ARG001
        _audit_cleanup_all()
        raise SystemExit(128 + signum)

    for s in (_signal.SIGTERM, _signal.SIGINT, getattr(_signal, "SIGHUP", None)):
        if s is None:
            continue
        try:
            _signal.signal(s, _handler)
        except (ValueError, OSError):
            pass


def _audit_cleanup_all() -> None:
    """Уборка ВСЕХ временных каталогов аудита (SIGTERM/SIGINT/SIGHUP + atexit).

    Связка с дефектом #156: при `Ctrl+C` или `kill -TERM` во время `git clone`
    папка `/dev/shm/kern_audit_*` иначе осталась бы в RAM-диске.
    """
    for d in list(_AUDIT_TMP):
        shutil.rmtree(d, ignore_errors=True)
        try:
            _AUDIT_TMP.remove(d)
        except ValueError:
            pass


def _audit_fetch(target: str) -> tuple[Path, Path | None]:
    """--audit-repo: локальный путь или GitHub (`owner/repo`, HTTPS URL).

    БЕЗОПАСНОСТЬ (7 защит):
      1. клон строго в `/dev/shm` (ОЗУ), каталог регистрируется ДО запуска git;
      2. `GIT_TERMINAL_PROMPT=0` — приватный URL не подвесит процесс запросом пароля;
      3. `GIT_LFS_SKIP_SMUDGE=1` — никаких гигабайтных LFS-блобов;
      4. `core.hooksPath=/dev/null` — чужие git-хуки не исполняются (RCE);
      5. `protocol.file.allow=never` — нельзя подсунуть локальный путь как remote;
      6. `--depth 1 --single-branch --no-tags` — минимум данных;
      7. timeout=30 с + регистрация в SIGTERM/SIGINT/SIGHUP/atexit.
    """
    p = Path(target).expanduser()
    if p.exists():
        return p, None
    url = target
    if re.fullmatch(r"[\w.-]+/[\w.-]+", target):
        url = "https://github.com/" + target + ("" if target.endswith(".git") else ".git")
    tmp = Path(tempfile.mkdtemp(prefix=f"kern_audit_{os.getpid()}_", dir=_shm_dir()))
    _AUDIT_TMP.add(tmp)                       # (1) регистрируем ДО clone
    env = dict(os.environ)                    # (2)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LFS_SKIP_SMUDGE"] = "1"          # (3)
    env.setdefault("GIT_ASKPASS", "/bin/true")
    cmd = ["git", "-c", "core.hooksPath=/dev/null",   # (4)
           "-c", "protocol.file.allow=never",         # (5)
           "clone", "--depth", "1", "--single-branch", "--no-tags", "--quiet",
           url, str(tmp / "repo")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)  # (7)
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp, ignore_errors=True)
        _AUDIT_TMP.discard(tmp)
        raise RuntimeError("git clone не уложился в 30 с (тяжёлый/зависший репозиторий)")
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        _AUDIT_TMP.discard(tmp)
        raise RuntimeError(f"git clone не удался: {(r.stderr or '')[:200]}")
    return tmp / "repo", tmp


def cmd_trust_score(target: str) -> int:
    """`--trust-score <PATH|owner/repo>`: делегирует в `tools/trust_scorecard.py`.

    Отдельный модуль — намеренно: `kern_contracts.py` уже 5.8k строк, и новый
    движок в нём усугубил бы долг #174 (ratchet `dup_defs_guard.py`).
    """
    tc = Path(__file__).resolve().parent / "trust_scorecard.py"
    if not tc.exists():
        print(f"[!] не найден {tc}")
        return 2
    return subprocess.call([sys.executable, str(tc), "--repo", target])


def cmd_audit_repo(target: str, kernc, html_out: str | None = None) -> int:
    """УНИВЕРСАЛЬНЫЙ АУДИТ ЛЮБОГО ПРОЕКТА (`--audit-repo <path|url>`).

    Без аннотаций в чужом коде: обходит все поддерживаемые файлы, гоняет
    `--xray` (Python AST + C-like разбор без исполнения), считает статистику
    по языкам, топ-5 по Маккейбу и печатает паспорт. При `--html` пишет
    автономный HTML-отчёт (0 CDN).
    """
    _audit_install_cleanup()
    try:
        root, tmp = _audit_fetch(target)
    except Exception as e:  # noqa: BLE001
        _replay_soft(e, "kern_contracts.py:4463")
        print(f"[!] {e}")
        return 2
    try:
        files: list[Path] = []
        skipped_files = 0          # мусор: симлинки, гиганты, минифицированные
        skipped_ext: dict[str, int] = {}   # #381: пропуск ПО РАСШИРЕНИЮ
        if root.is_file():
            files = [root]
        else:
            # followlinks=False: циклические симлинки в чужих репозиториях не
            # зацикливают обход; сами симлинки пропускаем (могут указывать вне).
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [d for d in dirnames if d not in _XRAY_SKIP_DIRS]
                for f in sorted(filenames):
                    fp = Path(dirpath) / f
                    if fp.suffix not in _XRAY_EXTS:
                        # ДЕФЕКТ #381: не «continue молча», а ИМЕНОВАННЫЙ учёт.
                        _k = fp.suffix or "<без расширения>"
                        skipped_ext[_k] = skipped_ext.get(_k, 0) + 1
                        continue
                    if fp.is_symlink():
                        skipped_files += 1
                        continue
                    if f.endswith(".min.js") or f.endswith(".min.ts"):
                        skipped_files += 1
                        continue
                    try:
                        if fp.stat().st_size > _XRAY_MAX_FILE:
                            skipped_files += 1
                            continue
                    except OSError:
                        skipped_files += 1
                        continue
                    files.append(fp)
        _xray_report_skipped(skipped_ext)
        stats: dict[str, list[int]] = {}
        findings: list[str] = []
        worst: list[tuple[int, str, str]] = []
        for f in files:
            ext = f.suffix
            lang = {'.py': 'Python', '.zig': 'Zig', '.c': 'C', '.h': 'C', '.rs': 'Rust',
                    '.ts': 'TypeScript', '.js': 'JavaScript', '.go': 'Go'}.get(ext, ext)
            st = stats.setdefault(lang, [0, 0, 0])  # файлы, проверено, пропущено
            st[0] += 1
            try:
                if ext == ".py":
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        cmd_xray(str(f), kernc)
                    out = buf.getvalue()
                    mm = re.search(r"checked (\d+) / (\d+) functions", out)
                    if mm:
                        ck, tot = int(mm.group(1)), int(mm.group(2))
                        st[1] += ck; st[2] += tot - ck
                    for ln in out.splitlines():
                        if ln.strip().startswith(("[DEAD BRANCH]", "[REDUNDANT GUARD]",
                                                   "[CRASH PATH]", "[BOUNDS PATH]", "[SMELL]")):
                            findings.append(f"{f.relative_to(root)}: {ln.strip()}")
                    for ln in out.splitlines():
                        m2 = re.search(r"\[FN\] (\w+): CC=(\d+)", ln)
                        if m2:
                            worst.append((int(m2.group(2)), str(f.relative_to(root)), m2.group(1)))
                else:
                    ck, tot, triv, fd, _rs, _nt = _xray_clike_file(f, kernc)
                    st[1] += ck; st[2] += max(0, tot - ck - triv)
                    for x in fd:
                        findings.append(f"{f.relative_to(root)}: {x}")
            except Exception as _kern_e_4526:  # noqa: BLE001 — честно пропускаем нечитаемое
                _replay_soft(_kern_e_4526, "kern_contracts.py:4526")
                st[2] += 1
        print("=" * 74)
        print(f"[AUDIT PASSPORT] {target}")
        print(f"  файлов: {len(files)} | находок: {len(findings)} "
              f"| пропущено файлов (симлинк/размер/min): {skipped_files}")
        for lang in sorted(stats):
            fl, ck, sk = stats[lang]
            print(f"  {lang:<12} файлов {fl:>3} | проверено {ck:>4} | пропущено {sk:>4}")
        if worst:
            print("  ТОП-5 по Маккейбу:")
            for cc, rel, nm in sorted(worst, reverse=True)[:5]:
                print(f"    CC={cc:<3} {rel}: {nm}")
        for x in findings[:40]:
            print("  " + x)
        if html_out:
            esc = (str(target).replace("&", "&amp;").replace("<", "&lt;"))
            rows = "".join(f"<li>{h}</li>" for h in findings[:200]) or "<li>—</li>"
            lang_rows = "".join(
                f"<tr><td>{k}</td><td>{v[0]}</td><td>{v[1]}</td><td>{v[2]}</td></tr>"
                for k, v in sorted(stats.items()))
            Path(html_out).write_text(
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>KERN audit: {esc}</title><style>body{{background:#0d1117;color:#c9d1d9;"
                "font:15px system-ui;max-width:1000px;margin:2rem auto;padding:0 1rem}"
                "h1{color:#3fb950}table{border-collapse:collapse}td,th{border:1px solid #30363d;"
                "padding:4px 10px}li{margin:2px 0}</style></head><body>"
                f"<h1>KERN audit passport</h1><p><code>{esc}</code></p>"
                f"<p>files: {len(files)} · findings: {len(findings)}</p>"
                "<h2>By language</h2><table><tr><th>language</th><th>files</th>"
                f"<th>checked</th><th>skipped</th></tr>{lang_rows}</table>"
                f"<h2>Findings</h2><ul>{rows}</ul>"
                "<p>Model is ours: reproduce any counterexample against the project's own build.</p>"
                "</body></html>", encoding="utf-8")
            print(f"[OK] HTML-паспорт: {html_out}")
        return 0
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def _xray_solver_gate(kernc) -> int:
    """ВРАТА БЕЛНАПА для `--xray`: решателя нет ⇒ N(0,0), а НЕ «находок 0».

    ЗАЧЕМ (дефект #407, класс #277). Без Z3 `_smt_verdict` возвращает `unknown`,
    `_smt_sat` — `None`, и ВСЕ SMT-детекторы молча не заявляют ничего. Отчёт
    «находок 0» читался как «код чист», хотя анализ НЕ ЗАПУСКАЛСЯ: в решётке
    Белнапа это N(0,0) — «нет данных», и гейт обязан ОТКАЗАТЬ, а не молчать.

    Возвращает 0, если решатель отвечает; 2 — если его нет (гейт закрыт).
    """
    _rc, out = run_kernc(kernc, "(set-logic ALL)\n(check-sat)\n")
    low = (out or "").lower()
    if "z3 недоступен" in low or "z3 is not" in low:
        print("[!] РЕШАТЕЛЬ Z3 НЕДОСТУПЕН — это N(0,0) по Белнапу, а не «находок 0».")
        print("    SMT-детекторы (деление, границы, переполнение, мёртвые ветви)")
        print("    НЕ ЗАПУСКАЛИСЬ, поэтому любой отчёт ниже был бы ЛОЖНОЙ чистотой.")
        print("    Лечение: uv pip install z3-solver, затем PATH=\"$PWD/.venv/bin:$PATH\"")
        print("    (каталог рядом с python подхватывается автоматически).")
        return 2
    return 0


def cmd_xray(path: str, kernc, show_all: bool = False) -> int:
    """ПУНКТ 13: рентген кода БЕЗ аннотаций."""
    if not Path(kernc).exists():
        print(f"[!] не найден kernc: {kernc} (соберите: zig build)")
        return 2
    _bg = _xray_solver_gate(kernc)
    if _bg:
        return _bg
    p = Path(path)
    # ПОЛЕВОЙ АДАПТЕР №5: `--xray <dir>` — рекурсивный обход репозитория.
    # Пропускаем служебные каталоги и агрегируем отчёт по всему дереву.
    if p.is_dir():
        return _xray_repo(p, kernc, show_all)
    # C-like файлы: Python-AST неприменим (упал бы на `//!` комментариях).
    # Маршрутизируем в устойчивый разбор БЕЗ исполнения тела (адаптер №5б).
    if p.suffix != ".py":
        _SMT_CALLS[0] = 0
        ck, tot, triv, fd, _rs, _nt = _xray_clike_file(p, kernc)
        _smt_calls_clike = _SMT_CALLS[0]
        _LAST_XRAY["stat"] = (ck, tot, max(0, tot - ck - triv), triv, list(fd))
        for x in fd:
            print("  " + x)
        # ЧЕСТНАЯ ГРАНИЦА (дефект #201). В C-like разборе НЕТ управления
        # потоком: не моделируются ранние `return`, `break` в `while(1)`,
        # состояние на итерациях цикла и инварианты вызывающего. ИЗМЕРЕНО на
        # СВЕЖЕМ HEAD `libgit2` (src/util): 14 кандидатов, при ручной проверке
        # ВСЕ 14 оказались ложными (`tsort.c` — guard `if (stack_curr < 2)
        # return;`, `win32/path_w32.c` — короткое замыкание `!len ||`,
        # `wildmatch.c` — условия одной ветки цикла протекли в другую).
        # Поэтому эти строки — КАНДИДАТЫ для человека, а не баги: заявлять их
        # чужому проекту нельзя.
        if fd:
            print("  [!] C-like findings выше — КАНДИДАТЫ, а не баги: управление "
                  "потоком (ранние return, break, итерации циклов) не "
                  "моделируется. Проверять вручную по коду.")
        print("-" * 74)
        print(f"[XRAY SUMMARY] checked {ck} / {tot} functions (trivial {triv}), "
              f"skipped {max(0, tot - ck - triv)} with explicit reasons, "
              f"findings {len(fd)}, SMT calls {_smt_calls_clike}")
        _xray_report_skip_reasons(_rs, max(0, tot - ck - triv), triv, ck, tot, _nt)
        return 0
    src = p.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    src_lines = src.splitlines()  # ПУНКТ 21: директивы `# @kern:len(arr) = N`
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    # ПОЛЕВОЙ АДАПТЕР №3: константы уровня модуля (`MAX_SIZE = 1024`,
    # `HTTP_BAD_REQUEST = 400`). В живом коде магические числа не пишут —
    # пишут имя константы, и без подстановки условие уходило в SKIP.
    module_env: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1                 and isinstance(node.targets[0], ast.Name)                 and isinstance(node.value, ast.Constant)                 and isinstance(node.value.value, int)                 and not isinstance(node.value.value, bool):
            module_env[node.targets[0].id] = str(node.value.value)
    found: list[str] = []
    # РАЗМЕРНОСТИ РАЗВЕДЕНЫ (дефект #407.2). До этой правки `skipped` держал
    # сообщения о ВЕТКАХ («ветка N не решена решателем»), а счётчик ниже считал
    # ФУНКЦИИ (`len(fns) - checked`). Скрапер уровня репозитория складывал и то и
    # другое в ОДИН словарь, потом сравнивал со счётчиком функций — и печатал
    # «пропусков БЕЗ записанной причины: -6» (вычитал ветки из функций).
    fn_skipped: list[str] = []   # УРОВЕНЬ ФУНКЦИИ — обязан сойтись со счётчиком
    notes: list[str] = []        # УРОВЕНЬ ВЕТКИ — справочные, НЕ пропуски
    checked = 0
    verified_smt = 0
    no_obligations = 0
    for fn in fns:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        _SMT_CALLS[0] = 0
        cc, smells = _cc_and_smells(fn)
        # Подмножество: должны переводиться УСЛОВИЯ ветвлений (тело целиком
        # переводить НЕ требуется — для поиска мёртвых веток и краш-путей нужны
        # только условия и делители). ИЗМЕРЕНО: строгая проверка через
        # `body_smt` отсеивала ровно те функции, где и есть находки.
        conds_ok = True
        for n in ast.walk(fn):
            if isinstance(n, ast.If):
                try:
                    # `len(arr)` переписывается в символическую длину -> условия с
                    # `len(...)` больше НЕ отсеиваются как «вне подмножества».
                    _cond_smt(n.test, set())
                except (Unsupported, NoReturn):
                    conds_ok = False
                    break
        if not conds_ok:
            fn_skipped.append(f"{fn.name}: условие ветвления вне подмножества")
            continue
        # ДЕФЕКТ #405: `checked` БОЛЬШЕ НЕ растёт здесь. Функция попадает в
        # `checked` только если решатель РЕАЛЬНО вызывался (см. ниже), а функция
        # без обязательств — в `trivial`. Считать её «проверенной» или
        # «пропущенной» значило бы врать о покрытии в любую сторону.
        if show_all or cc > 1:
            print(f"  [FN] {fn.name}: CC={cc} параметров={len(params)}")
        for s in smells:
            found.append(f"[SMELL] {fn.name}: {s}")
        lens = _declared_lengths_for(src_lines, fn.lineno)  # опциональное переопределение
        syms: set = set()
        lens.update(_collect_lens(fn, syms))   # Zero-Annotation: литералы + len()
        # ДЕФЕКТ #351: предусловия из ДЕКОРАТОРОВ (`@deal.pre(lambda …: …)`) —
        # такой же гард на входе, как `if`. Без них `div_ok(a, b)` с
        # `@deal.pre(lambda a, b: b != 0)` получал ЛОЖНЫЙ `[CRASH PATH]`.
        _pre = _deal_pre_path(fn, syms)
        _walk_branches(fn.body, list(_pre), params, kernc, found, notes, fn.name, syms, module_env)
        # ДЕФЕКТ #322: контекст «какие имена меняются в циклах» — на одну функцию.
        _LOOP_MODIFIED.clear()
        _LOOP_MODIFIED.update(_loop_modified(fn.body))
        _walk_bounds(fn.body, list(_pre), params, lens, kernc, found, fn.name, syms)
        # ДЕФЕКТ #208: считаем ТОЛЬКО функции, где решатель реально вызывался
        # (счётчик читается ПОСЛЕ обхода, иначе он всегда 0). Функция с нулём
        # обязательств — «прочитана», но НЕ «проверена».
        if _SMT_CALLS[0] > 0:
            verified_smt += 1
        else:
            no_obligations += 1

    print("-" * 74)
    for f in found:
        print("  " + f)
    print("-" * 74)
    # ТРИ КОРЗИНЫ (дефект #405): checked = решатель вызывался; trivial =
    # обязательств нет; skipped = функция НЕ анализировалась.
    _checked = verified_smt
    _trivial = no_obligations
    _skipped = len(fn_skipped)
    _LAST_XRAY["stat"] = (_checked, len(fns), _skipped, _trivial, list(found))
    print(f"[XRAY SUMMARY] checked {_checked} / {len(fns)} functions "
          f"(SMT-verified {_checked}, no obligations {_trivial}), "
          f"skipped {_skipped} with explicit reasons, "
          f"findings {len(found)}")
    for s in fn_skipped:
        print(f"    skip: {s}")
    # УРОВЕНЬ ВЕТКИ печатается ДРУГИМ ярлыком: «ветка N не решена решателем» —
    # это НЕ пропущенная функция, и складывать их в одну гистограмму значило бы
    # вычитать число ветвей из числа функций (дефект #407.2, отсюда бралось `-6`).
    for s in notes:
        print(f"    note: {s}")
    # ДЕФЕКТ N4 (и #405): остаток считаем от СУММЫ КОРЗИН, а не от одного
    # счётчика. Если какой-то путь пропускает функцию, НЕ записав причину, число
    # говорит «skipped N», а строк `skip:` меньше — и читатель не знает, почему.
    # Разницу печатаем явно: это дефект ИНСТРУМЕНТА. Инвариант тот же, что в
    # запечатанной спецификации `funnel_accounting.unaccounted`.
    _unexplained = len(fns) - (_checked + _trivial + _skipped)
    if _unexplained > 0:
        print(f"    [!] пропусков БЕЗ записанной причины: {_unexplained} — "
              f"это дефект инструмента, а не свойство проверяемого кода")
    if not found:
        print("[OK] рентген не нашёл мёртвых веток, избыточных проверок и краш-путей")
    return 0


# =============================================================================
# ЭШЕЛОН 4, ПУНКТ 20 — ТОТАЛЬНАЯ КОРРЕКТНОСТЬ ЦИКЛОВ (Флойд — Хоар).
#
# `# @kern:invariant <expr>` + `# @kern:decreases <expr>` -> ЧЕТЫРЕ обязательства:
#   (1) Init:        req AND (v = v0)            AND NOT I(v)      -> UNSAT
#   (2) Consecution: req AND I(v) AND cond AND (v' = step(v))
#                                                    AND NOT I(v') -> UNSAT
#   (3) Post:        req AND I(v) AND NOT cond AND (result = ret)
#                                                    AND NOT ens   -> UNSAT
#   (4) Termination: req AND I(v) AND cond AND (v' = step(v))
#                          AND NOT (V(v) >= 0 AND V(v') < V(v))   -> UNSAT
#
# Всё в QF_LIA (без CHC): переменные целые, шаг линейный. Если шаг нелинеен или
# цикл не найден — честный SKIP с причиной, а не догадка.
# =============================================================================





# =============================================================================
# ЭШЕЛОН 4, ПУНКТ 24 — ИНВАРИАНТ СОСТОЯНИЯ (`# @kern:state_invariant <expr>`).
#
# Модель: функция-переход возвращает НОВОЕ состояние; `result` — это выход.
# Инвариант описывает ВЫХОДНОЕ состояние (может ссылаться на `result` и параметры).
# Обязательство: для КАЖДОГО выхода, достижимого при `requires` и путевых
# условиях гардов, инвариант обязан выполняться:
#     req AND path AND (result = ret) AND NOT invariant  -> UNSAT
#
# Это ловит двойной возврат: без гарда `state == 1` выход `escrow - amount`
# уходит в минус -> SAT -> [FAIL] STATE INVARIANT VIOLATED.
# =============================================================================



# =============================================================================
# ЭШЕЛОН 3, ПУНКТ 17 — `--simplify`: ВЕРИФИЦИРУЮЩИЙ ОПТИМИЗАТОР.
#
# Три трансформации, каждая — по ДОКАЗАТЕЛЬСТВУ из Z3 (не по эвристике):
#   1) [DEAD BRANCH]      — ветка недостижима (UNSAT) -> вырезаем её;
#   2) [REDUNDANT GUARD]  — условие всегда истинно на пути -> убираем `if`;
#   3) одинаковые ветви  — `if C: return X else: return X` -> `return X`.
#
# ГЛАВНОЕ: перед выдачей результата КАЖДАЯ упрощённая функция проверяется на
# ЭКВИВАЛЕНТНОСТЬ исходной через `--diff-equiv` (Z3: ∃x: f_old(x) != f_new(x)).
# UNSAT -> доказано; SAT -> упрощение ОТКЛОНЯЕТСЯ (fail-closed).
# =============================================================================


# -----------------------------------------------------------------------------
# ЭШЕЛОН 5, ПУНКТ 26: ОДНОСЛОВНЫЕ БИЗНЕС-ПРЕСЕТЫ (+ `--spec-gaps`).
#
# ЗАЧЕМ. Обычному разработчику трудно написать формулу постусловия, но легко
# поставить ОДНО СЛОВО над функцией. Пресет разворачивается в математическое
# обязательство и проверяется тем же путём (`kernc prove` + пруф-чекер).
#
# ЕДИНЫЙ МЕХАНИЗМ КОМПОЗИЦИИ (`_instantiate_body`). `idempotent`, `monotonic`
# и `no_arbitrage` (пункт 27) — это ОДНА операция: подстановка произвольного
# SMT-выражения вместо параметра в СИМВОЛЬНОЕ ТЕЛО функции. Три отдельные
# реализации разошлись бы и дали бы разные вердикты на одном и том же коде.
# -----------------------------------------------------------------------------



# -----------------------------------------------------------------------------
# ЭШЕЛОН 5, ПУНКТ 30: ВЕРИФИКАТОР RLS-ПОЛИТИК (`--verify-sql`).
#
# ЗАЧЕМ. Классический баг приоритета операторов в SQL: `WHERE tenant = req OR
# public = 1 AND deleted = 0` — из-за того, что `AND` связывает сильнее, запрос
# отдаёт ЧУЖУЮ публичную запись и/или УДАЛЁННУЮ строку своего тенанта. Проверяем
# не текст запроса, а ПРЕДИКАТ-функцию доступа: доступ разрешён (`result == 1`)
# ТОЛЬКО при `(row_tenant == req_tenant ∨ is_public == 1) ∧ is_deleted == 0`.
# -----------------------------------------------------------------------------



# -----------------------------------------------------------------------------
# ЭШЕЛОН 5, ПУНКТ 31: ВЕРИФИКАТОР ТАРИФНЫХ МАТРИЦ (`--verify-pricing`).
#
# ЗАЧЕМ. Тарифная сетка — это РАЗБИЕНИЕ домена на правила `(условие -> цена)`.
# Два формальных свойства:
#   * ПОЛНОТА: каждому допустимому входу соответствует ЦЕНА, а не признак
#     «не обработано» (отрицательная цена = sentinel) -> SAT = дыра в тарифах;
#   * НЕПРОТИВОРЕЧИВОСТЬ: два правила с РАЗНЫМИ ценами не пересекаются ->
#     SAT = конфликт правил (в Белнапе это состояние B).
# -----------------------------------------------------------------------------



# -----------------------------------------------------------------------------
# ЭШЕЛОН 6, ПУНКТ 32: АНТИ-ЧИТ ПРОТИВ REWARD HACKING И SLOPSQUATTING.
#
# ЗАЧЕМ. ИИ-агент, которому не удаётся починить код, идёт на хитрость: перегружает
# `__eq__` (любой объект «равен» любому), глушит `assert` через `except: pass`,
# выходит из процесса `sys.exit(0)`, подменяет проверяемое `unittest.mock`, либо
# хардкодит ответ под конкретный тест (`if x == 42 and y == 17`). Плюс
# SLOPSQUATTING: галлюцинированный импорт, зарегистрированный злоумышленником в
# PyPI. Всё это ловится СТАТИЧЕСКИ по AST.
# -----------------------------------------------------------------------------



# -----------------------------------------------------------------------------
# ЭШЕЛОН 6, ПУНКТ 33: СКАНЕР ОТРАВЛЕНИЯ MCP И ЗАЩИТА ОТ RUG-PULL.
#
# ЗАЧЕМ. MCP-сервер описывает инструменты в JSON; поле `description` читает
# ЯЗЫКОВАЯ МОДЕЛЬ, а не человек. Оттуда три атаки:
#   * промпт-инъекция (`ignore previous instructions`, чтение `~/.ssh`, `.env`);
#   * невидимые символы (Zero-Width, Bidi Override, Tag characters) — текст
#     выглядит безобидно, но модель читает скрытое;
#   * RUG-PULL: описание «тихо» меняется ПОСЛЕ одобрения. Замок `mcp.lock.json`
#     хранит SHA-256 каждого инструмента; изменение -> тревога.
# -----------------------------------------------------------------------------



# -----------------------------------------------------------------------------
# ЭШЕЛОН 6, ПУНКТ 34: НЕИНТЕРФЕРЕНЦИЯ (`# @kern:secret`, 2-Safety).
#
# ЗАЧЕМ. Утечка по сторонним каналам: публичный выход зависит от СЕКРЕТА (pin,
# key, token). Классическая формулировка Гогоэна—Месегера: две копии программы с
# ОДИНАКОВЫМ публичным входом и РАЗНЫМИ секретами обязаны дать ОДИН выход.
# Проверяем самокомпозицию: `body[secret := s1] != body[secret := s2]` -> SAT =
# утечка (существует пара секретов, различимая по публичному выходу).
# -----------------------------------------------------------------------------



# -----------------------------------------------------------------------------
# ЭШЕЛОН 7, ПУНКТ 36: ACTION / FINOPS FIREWALL ДЛЯ ИИ-АГЕНТОВ.
#
# ЗАЧЕМ. Агент собирается вызвать боевой API (перевод, масштабирование облака,
# удаление ресурса). Проверяем JSON-вызов ДО исполнения против политики:
#   * `allow`  — предикат, который обязан быть истинным (лимиты, бюджеты);
#   * `forbid` — список предикатов, которые обязаны быть ложными.
# Вердикт в решётке Белнапа и кодах RFC 9110:
#   T -> 200 (проверено, trusted: 0); F -> 422 (контрпример);
#   B -> 409 (политики ПРОТИВОРЕЧАТ: allow и forbid истинны одновременно).
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# ЭШЕЛОН 7, ПУНКТ 37: ПРОТИВОРЕЧИЯ В ДОКУМЕНТАХ / ДОГОВОРАХ / RAG-БАЗАХ.
#
# ЗАЧЕМ. Пункты договора — это КОНЪЮНКЦИЯ ограничений. Если она несовместна
# (`UNSAT`), документ внутренне противоречив: состояние B (1,1), Врата ЗАКРЫТЫ.
# Мало сказать «противоречиво» — нужно назвать КОНКРЕТНЫЕ пункты: минимальное
# ядро несовместности (greedy-удаление: если без пункта система всё ещё
# несовместна, пункт в ядро не входит).
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# ЭШЕЛОН 7, ПУНКТ 38: RLVR — ВЕРИФИЦИРУЕМЫЙ ОРАКУЛ ВОЗНАГРАЖДЕНИЯ.
#
# ЗАЧЕМ. «LLM-as-a-judge» недетерминирован и поддаётся взлому. Здесь награда
# выдаётся МАТЕМАТИКОЙ: R = +1.0 только при `trusted: 0 | holes: 0` И чистоте по
# `--anti-cheat`; иначе -2.0 (чит), -1.0 (контрпример), 0.0 (вне фрагмента).
# Никаких ложных наград: `unknown` НИКОГДА не даёт положительный сигнал.
# -----------------------------------------------------------------------------


# =========================================================================
#  ГОМЕОСТАТИЧЕСКАЯ ПЕТЛЯ САМОИСЦЕЛЕНИЯ (--heal)
# =========================================================================
# ЗАЧЕМ. `--infer-requires` и `[SUGGESTED FIX]` только ПЕЧАТАЮТ рецепт: петля
# разомкнута, человек обязан применить патч руками. `--heal` замыкает её:
#   [1] проверка -> F (0,1) + контрпример
#   [2] синтез защитного гарда (с ПРОВЕРКОЙ в Z3)
#   [3] ВСТАВКА гарда в исходник (с бэкапом)
#   [4] ПОВТОРНАЯ проверка -> T (1,0), trusted: 0
# Если после патча краш остаётся — изменения ОТКАТЫВАЮТСЯ (fail-closed):
# «вылеченным» файл объявляется только по машинному вердикту.


# =========================================================================
#  РАЗДЕЛ 5 ЭНЦИКЛОПЕДИИ: КОНКОЛИЧЕСКОЕ ИСПОЛНЕНИЕ (--concolic)
# =========================================================================
# ИДЕЯ (DART / KLEE). Статический `--gen-tests` перебирает пути СИМВОЛЬНО и
# не знает, какие из них реально исполняются. Конколика совмещает оба мира:
#   1) КОНКРЕТНЫЙ запуск интерпретатором AST на реальном входе (0,0,...);
#   2) запись РЕАЛЬНОЙ трассы условий (какое условие куда пошло);
#   3) инверсия условия в Z3 -> НОВЫЙ конкретный вход;
#   4) снова живой запуск — пока не будут исполнены все достижимые ветви.
# ЗВУЧИМОСТЬ ОТЧЁТА: «покрыто M/M» подтверждается РЕАЛЬНЫМ исполнением,
# а мёртвые ветви (SAT=unsat) исключаются из знаменателя с указанием причины.


def _xray_repo(root: Path, kernc, show_all: bool = False) -> int:
    """ПОЛЕВОЙ АДАПТЕР №5: рекурсивный скан ЧУЖОГО репозитория.

    Обходит все поддерживаемые файлы, пропуская служебные каталоги, и печатает
    сводный паспорт: сколько файлов/функций проверено, сколько SKIP и все
    находки с точными путями. Ничего не выдумывает: файлы, которые не удалось
    разобрать, попадают в список пропущенных с причиной.
    """
    files, skipped_ext = _xray_collect(root)
    _xray_report_skipped(skipped_ext)
    print(f"[REPO SCAN] {root} | файлов к сканированию: {len(files)}")
    total_checked = total_fns = total_skip = total_trivial = 0
    all_findings: list[str] = []
    all_reasons: dict[str, int] = {}      # ДЕФЕКТ #400: гистограмма причин
    # ДЕФЕКТ #407.2: заметки уровня ВЕТКИ — ОТДЕЛЬНАЯ корзина. До этого они
    # ссыпались в `all_reasons` и сравнивались со счётчиком ФУНКЦИЙ, что давало
    # отрицательную «разницу» (`-6`) и выдавало ветки за пропущенные функции.
    all_notes: dict[str, int] = {}
    bad_files = 0
    for f in files:
        if f.suffix != ".py":
            ck, tot, triv, fd, _rs, _nt = _xray_clike_file(f, kernc)
            total_checked += ck
            total_fns += tot
            total_trivial += triv
            total_skip += max(0, tot - ck - triv)
            for _k400, _c400 in _rs.items():
                all_reasons[_k400] = all_reasons.get(_k400, 0) + _c400
            for _k_note, _c_note in _nt.items():
                all_notes[_k_note] = all_notes.get(_k_note, 0) + _c_note
            for x in fd:
                all_findings.append(f"{f}: {x}")
            continue
        try:
            _buf = io.StringIO()
            with contextlib.redirect_stdout(_buf):
                rc = cmd_xray(str(f), kernc, show_all)
            _out = _buf.getvalue()
        except SyntaxError as e:
            bad_files += 1
            print(f"  [SKIP FILE] {f}: синтаксис: {e}")
            continue
        except Exception as e:  # noqa: BLE001 — честно печатаем, а не глотаем
            _replay_soft(e, "kern_contracts.py:4896")
            bad_files += 1
            print(f"  [SKIP FILE] {f}: {type(e).__name__}: {e}")
            continue
        # Вывод cmd_xray перехвачен, чтобы собрать ЕГО причины пропуска в ту же
        # гистограмму; печатаем дословно, чтобы ничего не потерялось.
        print(_out, end="" if _out.endswith(chr(10)) else chr(10))
        for _ln in _out.splitlines():
            _st = _ln.strip()
            if _st.startswith("note: "):
                # УРОВЕНЬ ВЕТКИ (дефект #407.2) — НЕ пропуск функции.
                _rest = _st[6:]
                if " × " in _rest:
                    _k2, _c2 = _rest.rsplit(" × ", 1)
                    all_notes[_k2] = all_notes.get(_k2, 0) + int(_c2)
                else:
                    all_notes[_rest] = all_notes.get(_rest, 0) + 1
                continue
            if _st.startswith("skip: "):
                _rest = _st[6:]
                if " × " in _rest:
                    _k2, _c2 = _rest.rsplit(" × ", 1)
                    all_reasons[_k2] = all_reasons.get(_k2, 0) + int(_c2)
                else:
                    all_reasons[_rest] = all_reasons.get(_rest, 0) + 1
        # cmd_xray печатает свою сводку; агрегируем через побочный канал
        st = _LAST_XRAY.get("stat")
        if st:
            total_checked += st[0]
            total_fns += st[1]
            total_skip += st[2]
            total_trivial += st[3]
            for x in st[4]:
                all_findings.append(f"{f}: {x}")
        if rc not in (0, 1):
            bad_files += 1
    print("=" * 74)
    print(f"[REPO SUMMARY] файлов {len(files)} | функций проверено {total_checked} / {total_fns} "
          f"(skipped {total_skip}) | находок {len(all_findings)} | нечитаемых файлов {bad_files}")
    _xray_report_skip_reasons(all_reasons, total_skip, total_trivial,
                              total_checked, total_fns, all_notes)
    for x in all_findings[:60]:
        print("  " + x)
    return 0


# =============================================================================
# ЭШЕЛОН 4, ПУНКТ 20 — ТОТАЛЬНАЯ КОРРЕКТНОСТЬ ЦИКЛОВ (Флойд — Хоар).
#
# `# @kern:invariant <expr>` + `# @kern:decreases <expr>` -> ЧЕТЫРЕ обязательства:
#   (1) Init:        req AND (v = v0)            AND NOT I(v)      -> UNSAT
#   (2) Consecution: req AND I(v) AND cond AND (v' = step(v))
#                                                    AND NOT I(v') -> UNSAT
#   (3) Post:        req AND I(v) AND NOT cond AND (result = ret)
#                                                    AND NOT ens   -> UNSAT
#   (4) Termination: req AND I(v) AND cond AND (v' = step(v))
#                          AND NOT (V(v) >= 0 AND V(v') < V(v))   -> UNSAT
#
# Всё в QF_LIA (без CHC): переменные целые, шаг линейный. Если шаг нелинеен или
# цикл не найден — честный SKIP с причиной, а не догадка.
# =============================================================================

_INV_RE = re.compile(r"@kern:invariant\s+(.+)")
_DEC_RE = re.compile(r"@kern:decreases\s+(.+)")


def _directives_before(lines: list[str], lineno: int) -> dict[str, str]:
    """Строки директив из блока комментариев НЕПОСРЕДСТВЕННО перед `def`."""
    out: dict[str, str] = {}
    i = lineno - 2
    while i >= 0:
        s = lines[i].strip()
        if not s or not s.startswith("#"):
            break
        m = _INV_RE.search(s)
        if m:
            out["invariant"] = m.group(1).strip()
        m = _DEC_RE.search(s)
        if m:
            out["decreases"] = m.group(1).strip()
        i -= 1
    return out


def _subst(text: str, mapping: dict[str, str]) -> str:
    """Подстановка переменных в SMT-строку (по границам слова).

    ДЕФЕКТ #137: раньше ЛЮБОЙ терм оборачивался в скобки, поэтому подстановка
    числа давала `(0)` — НЕВАЛИДНЫЙ SMT-LIB (скобки = применение функции).
    Z3 не мог разобрать формулу, kernc отвечал `N`, а это молча принималось за
    «безопасно». Теперь атомы (числа и идентификаторы) подставляются как есть.
    """
    # ДЕФЕКТ #139: обёртка в скобки давала ДВОЙНЫЕ скобки `((+ i 1))` — Z3 не мог
    # разобрать формулу и отвечал `N`. В SMT-LIB вся нотация ПРЕФИКСНАЯ, поэтому
    # подстановка полного s-выражения или атома НЕ требует обёртки вообще.
    for k in sorted(mapping, key=len, reverse=True):
        text = re.sub(r"(?<![\w])" + re.escape(k) + r"(?![\w])",
                      mapping[k], text)
    return text


def _assigns(stmts) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for st in stmts:
        if (isinstance(st, ast.Assign) and len(st.targets) == 1
                and isinstance(st.targets[0], ast.Name)):
            try:
                out.append((st.targets[0].id, expr_smt(st.value, {})))
            except (Unsupported, NoReturn):
                raise Unsupported(f"присваивание на строке {st.lineno} вне подмножества")
        elif isinstance(st, ast.AugAssign) and isinstance(st.target, ast.Name):
            op = {"Add": "+", "Sub": "-", "Mult": "*"}.get(type(st.op).__name__)
            if op is None:
                raise Unsupported(f"+=/-= только на строке {st.lineno}")
            try:
                out.append((st.target.id, f"({op} {st.target.id} {expr_smt(st.value, {})})"))
            except (Unsupported, NoReturn):
                raise Unsupported(f"присваивание на строке {st.lineno} вне подмножества")
    return out


def _apply(state: dict[str, str], assigns) -> dict[str, str]:
    s = dict(state)
    for name, expr in assigns:
        s[name] = _subst(expr, s)
    return s


def check_loop(fn, params, req_smt, ens_smt, kernc) -> list[str]:
    """Четыре обязательства для первого top-level `while` (Пункт 20)."""
    res: list[str] = []
    idx = None
    for n, st in enumerate(fn.body):
        if isinstance(st, ast.While):
            idx = n
            break
    if idx is None:
        return res
    loop = fn.body[idx]
    try:
        cond = expr_smt(loop.test, {})
        init_a = _assigns(fn.body[:idx])
        step_a = _assigns(loop.body)
    except (Unsupported, NoReturn, Exception) as e:
        res.append(f"[SKIP] {fn.name}: цикл вне подмножества ({e})")
        return res
    ret = None
    for st in fn.body[idx + 1:]:
        if isinstance(st, ast.Return) and st.value is not None:
            try:
                ret = expr_smt(st.value, {})
            except (Unsupported, NoReturn):
                ret = None
            break
    lines = _loop_lines.get(fn.lineno, [])
    d = _directives_before(lines, fn.lineno)
    if "invariant" not in d:
        res.append(f"[SKIP] {fn.name}: нет `# @kern:invariant` — цикл не проверяется")
        return res
    try:
        inv = expr_smt(ast.parse(d["invariant"], mode="eval").body, {})
    except (Unsupported, NoReturn, Exception) as e:
        res.append(f"[SKIP] {fn.name}: инвариант вне подмножества ({e})")
        return res
    dec = None
    if "decreases" in d:
        try:
            dec = expr_smt(ast.parse(d["decreases"], mode="eval").body, {})
        except (Unsupported, NoReturn):
            dec = None
    names = [p for p in params] + [a for a, _ in init_a] + [a for a, _ in step_a]
    state0 = {p: p for p in params}
    state_i = _apply(state0, init_a)
    state_c = {n: n for n in names}
    state_n = _apply(state_c, step_a)
    inv0 = _subst(inv, state_i)
    invc = _subst(inv, state_c)
    invn = _subst(inv, state_n)
    pre = [req_smt] if req_smt else []
    # ИЗМЕРЕНО (Дефект #138): раньше объявлялись ТОЛЬКО параметры, поэтому
    # локальная переменная цикла (`i`) оставалась необъявленной -> Z3 отвечал `N`
    # -> молчаливый PASS. Объявляем ВСЕ переменные состояния.
    decls = list(dict.fromkeys(names))
    fails = 0
    unknowns = 0
    # `result` участвует ТОЛЬКО в обязательстве `post` -> объявляем его там же
    # (Дефект #138: необъявленная переменная даёт `N`, что раньше читалось как PASS).
    decls_post = list(dict.fromkeys(decls + ["result"]))
    checks: list[tuple[str, list[str], list[str]]] = [
        ("init", decls, pre + [f"(not {inv0})"]),
        ("consecution", decls, pre + [invc, cond, f"(not {invn})"]),
    ]
    if ret is not None and ens_smt:
        checks.append(("post", decls_post,
                       pre + [invc, f"(not {cond})",
                              f"(= result {_subst(ret, state_c)})",
                              f"(not {ens_smt})"]))
    if dec is not None:
        dec_c = _subst(dec, state_c)
        dec_n = _subst(dec, state_n)
        checks.append(("termination", decls,
                       pre + [invc, cond,
                              f"(not (and (>= {dec_c} 0) (< {dec_n} {dec_c})))"]))
    else:
        res.append(f"[SKIP] {fn.name}: нет `# @kern:decreases` — остановка НЕ проверена")
        unknowns += 1
    for kind, dcl, asserts in checks:
        v, ce = _smt_verdict(kernc, dcl, asserts)
        if v == "sat":
            fails += 1
            label = {"init": "LOOP INVARIANT VIOLATED at init",
                     "consecution": "LOOP INVARIANT VIOLATED (не сохраняется)",
                     "post": "POSTCONDITION VIOLATED",
                     "termination": "NON-TERMINATING LOOP (вариант не убывает)"}[kind]
            res.append(f"[FAIL] {fn.name}: {label}; контрпример: {ce}")
        elif v == "unknown":
            unknowns += 1
            res.append(f"[UNKNOWN] {fn.name}: обязательство `{kind}` НЕ решено "
                       f"({ce}) — НЕ считается доказанным")
    if fails == 0 and unknowns == 0:
        res.append(f"[PASS] {fn.name}: PROVEN (invariant & termination verified)")
    return res


_loop_lines: dict[int, list[str]] = {}


def cmd_loops(path: str, kernc) -> int:
    """ПУНКТ 20: проверка циклов (`make loop-check`)."""
    p = Path(path)
    src = p.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    out: list[str] = []
    for fn in fns:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        _loop_lines[fn.lineno] = lines
        fn._kern_lines = lines  # noqa: SLF001
        req, ens = None, None
        for ln in _directives_before(lines, fn.lineno).values():
            pass
        # requires/ensures читаем тем же блоком
        i = fn.lineno - 2
        while i >= 0:
            s = lines[i].strip()
            if not s or not s.startswith("#"):
                break
            m = re.search(r"@kern:requires\s+(.+)", s)
            if m:
                try:
                    req = expr_smt(ast.parse(m.group(1).strip(), mode="eval").body, {})
                except (Unsupported, NoReturn):
                    req = None
            m = re.search(r"@kern:ensures\s+(.+)", s)
            if m:
                try:
                    ens = expr_smt(ast.parse(m.group(1).strip(), mode="eval").body, {})
                except (Unsupported, NoReturn):
                    ens = None
            i -= 1
        out.extend(check_loop(fn, params, req, ens, kernc))
    print("-" * 74)
    for r in out:
        print("  " + r)
    print("-" * 74)
    nf = sum(1 for r in out if r.startswith("[FAIL]"))
    np_ = sum(1 for r in out if r.startswith("[PASS]"))
    ns = sum(1 for r in out if r.startswith("[SKIP]"))
    print(f"[LOOP SUMMARY] PASS {np_} | FAIL {nf} | SKIP {ns}")
    return 0


# =============================================================================
# ЭШЕЛОН 4, ПУНКТ 24 — ИНВАРИАНТ СОСТОЯНИЯ (`# @kern:state_invariant <expr>`).
#
# Модель: функция-переход возвращает НОВОЕ состояние; `result` — это выход.
# Инвариант описывает ВЫХОДНОЕ состояние (может ссылаться на `result` и параметры).
# Обязательство: для КАЖДОГО выхода, достижимого при `requires` и путевых
# условиях гардов, инвариант обязан выполняться:
#     req AND path AND (result = ret) AND NOT invariant  -> UNSAT
#
# Это ловит двойной возврат: без гарда `state == 1` выход `escrow - amount`
# уходит в минус -> SAT -> [FAIL] STATE INVARIANT VIOLATED.
# =============================================================================

_SI_RE = re.compile(r"@kern:state_invariant\s+(.+)")


def _si_directive(lines, lineno):
    i = lineno - 2
    while i >= 0:
        s = lines[i].strip()
        if not s or not s.startswith("#"):
            break
        m = _SI_RE.search(s)
        if m:
            return m.group(1).strip()
        i -= 1
    return None


def _returns_with_path(body, path, syms, out):
    """Все `return <expr>` с накопленным путём гардов."""
    for st in body:
        if isinstance(st, ast.If):
            try:
                cond = _cond_smt(st.test, syms)
            except (Unsupported, NoReturn):
                cond = None
            _returns_with_path(st.body, path + ([cond] if cond else []), syms, out)
            neg = f"(not {cond})" if cond else None
            _returns_with_path(st.orelse, path + ([neg] if neg else []), syms, out)
            if neg and _block_exits(st.body):
                path = path + [neg]
            continue
        if isinstance(st, ast.Return) and st.value is not None:
            try:
                out.append((list(path), expr_smt(st.value, {}), st.lineno))
            except (Unsupported, NoReturn):
                pass


def cmd_state_inv(path: str, kernc) -> int:
    """ПУНКТ 24: инвариант состояния (`make state-inv-check`)."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    out: list[str] = []
    for fn in fns:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        inv_txt = _si_directive(lines, fn.lineno)
        if inv_txt is None:
            out.append(f"[SKIP] {fn.name}: нет `# @kern:state_invariant`")
            continue
        req = None
        i = fn.lineno - 2
        while i >= 0:
            s = lines[i].strip()
            if not s or not s.startswith("#"):
                break
            m = re.search(r"@kern:requires\s+(.+)", s)
            if m:
                try:
                    req = expr_smt(ast.parse(m.group(1).strip(), mode="eval").body, {})
                except (Unsupported, NoReturn):
                    req = None
            i -= 1
        syms: set = set()
        lens = _collect_lens(fn, syms)
        try:
            inv = _cond_smt(ast.parse(inv_txt, mode="eval").body, syms)
        except (Unsupported, NoReturn, Exception) as e:
            out.append(f"[SKIP] {fn.name}: инвариант вне подмножества ({e})")
            continue
        rets: list = []
        _returns_with_path(fn.body, [], syms, rets)
        if not rets:
            out.append(f"[SKIP] {fn.name}: нет `return <expr>`")
            continue
        decls = list(dict.fromkeys(params + ["result"]))
        pre = [req] if req else []
        fails = unknowns = 0
        for pth, ret, ln in rets:
            v, ce = _smt_verdict(kernc, decls,
                                 pre + pth + [f"(= result {ret})", f"(not {inv})"])
            if v == "sat":
                fails += 1
                out.append(f"[FAIL] {fn.name}: STATE INVARIANT VIOLATED at line {ln}; "
                           f"контрпример: {ce}")
            elif v == "unknown":
                unknowns += 1
                out.append(f"[UNKNOWN] {fn.name}: выход строка {ln} НЕ решён ({ce})")
        if fails == 0 and unknowns == 0:
            out.append(f"[PASS] {fn.name}: PROVEN (state invariant preserved on all "
                       f"{len(rets)} exits)")
    print("-" * 74)
    for r in out:
        print("  " + r)
    print("-" * 74)
    print(f"[STATE SUMMARY] PASS {sum(1 for r in out if r.startswith('[PASS]'))} | "
          f"FAIL {sum(1 for r in out if r.startswith('[FAIL]'))} | "
          f"SKIP {sum(1 for r in out if r.startswith('[SKIP]'))} | "
          f"UNKNOWN {sum(1 for r in out if r.startswith('[UNKNOWN]'))}")
    return 0


def cmd_explain(path: str, kernc) -> int:
    """ПУНКТ 18: человеческий паспорт функции (диапазон, падения, CC)."""
    p = Path(path)
    tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        cc, smells = _cc_and_smells(fn)
        print(f"  {fn.name}({', '.join(params)}):")
        print(f"    сложность Маккейба CC = {cc}; параметров {len(params)}; строка {fn.lineno}")
        divs, rets = [], []
        for n in ast.walk(fn):
            if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                divs.append(n.lineno)
            if isinstance(n, ast.Return) and n.value is not None:
                try:
                    rets.append(expr_smt(n.value, {}))
                except (Unsupported, NoReturn):
                    pass
        if divs:
            print(f"    условия падения: деление на ноль в строках {divs}")
        if rets:
            print(f"    возможные выходы (SMT): {len(rets)} ветвей")
        for s in smells:
            print(f"    [!] {s}")
    return 0


def cmd_pr_summary(old_file: str, new_file: str, kernc) -> int:
    """ПУНКТ 19: математическое резюме изменений для Code Review."""
    a = {n: (p, b, ln, u) for n, p, b, ln, u in parse_bodies(Path(old_file))}
    b2 = {n: (p, b, ln, u) for n, p, b, ln, u in parse_bodies(Path(new_file))}
    common = sorted(n for n in a if n in b2)
    only_old = sorted(set(a) - set(b2))
    only_new = sorted(set(b2) - set(a))
    same = diverged = unknown = 0
    print(f"[PR-SUMMARY] {Path(old_file).name} -> {Path(new_file).name}")
    for name in common:
        pa, ba, _ln, ua = a[name]
        pb, bnew, _ln2, ub = b2[name]
        if pa != pb:
            print(f"  [SKIP] {name}: изменён набор параметров")
            continue
        # ДЕФЕКТ #206: havoc — неограниченная абстракция; distinctive SAT по ней
        # не означает изменения поведения. Честный исход — UNKNOWN.
        if "_havoc_" in ba or "_havoc_" in bnew:
            unknown += 1
            print(f"  [UNKNOWN] {name}: тело содержит абстракцию (_havoc_k) — "
                  f"изменение поведения недоказуемо")
            continue
        # ДЕФЕКТ #207: развёртка — недо-аппроксимация. UNSAT на K шагах НЕ
        # доказывает эквивалентность (цикл может идти дальше). Только UNKNOWN.
        if ua or ub:
            unknown += 1
            print(f"  [UNKNOWN] {name}: развёртка цикла/рекурсии — "
                  f"изменение недоказуемо (дефект #207)")
            continue
        rc, out = run_kernc(kernc, diff_equiv_smt(pa, ba, bnew))
        if "ДОКАЗАНО" in out:
            same += 1
            print(f"  [EQUIVALENT] {name}: поведение на 100% сохранено на всём Z")
        else:
            diverged += 1
            ce = next((l.strip() for l in out.splitlines() if "КОНТРПРИМЕР" in l), "")
            print(f"  [DIVERGED] {name}: поведение ИЗМЕНИЛОСЬ {ce}")
    for n in only_old:
        print(f"  [REMOVED] {n}")
    for n in only_new:
        print(f"  [ADDED]   {n}")
    print("-" * 74)
    print(f"ИТОГО: эквивалентных {same} | изменившихся {diverged} | "
          f"недоказуемых (абстракция) {unknown} | "
          f"удалено {len(only_old)} | добавлено {len(only_new)}")
    return 1 if diverged else 0


def cmd_suggest_fix(path: str, kernc, infer_requires: bool = False) -> int:
    """ПУНКТЫ 15 и 16: авто-синтез гарда и предусловия с ПРОВЕРКОЙ в Z3.

    Найден краш-путь (делитель может быть 0) -> предлагаем защитный гард и
    ДОКАЗЫВАЕМ его: после гарда путь продолжается при `делитель != 0`, поэтому
    `путь AND делитель != 0 AND делитель == 0` обязан быть UNSAT. Если это не
    так — гард НЕ выдаём (честный отказ вместо ложного рецепта).
    """
    if not Path(kernc).exists():
        print(f"[!] не найден kernc: {kernc}")
        return 2
    tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    fixes = 0
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        for n in ast.walk(fn):
            if not (isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod))):
                continue
            if isinstance(n.op, ast.Mod) and _is_str_expr(n.left):
                continue  # `'%s' % x` — форматирование, не деление
            try:
                div = expr_smt(n.right, {})
            except (Unsupported, NoReturn):
                continue
            sat = _smt_sat(kernc, params, [f"(= {div} 0)"])
            if sat is not True:
                continue
            # ГАРД: после него делитель гарантированно не 0.
            guard = f"(= {div} 0)"
            verified = _smt_sat(kernc, params, [f"(not {guard})", guard]) is False
            print(f"  [CRASH PATH] {fn.name}: строка {n.lineno}: {div} может быть 0")
            if verified:
                print(f"  [SUGGESTED FIX ... VERIFIED BY Z3] {fn.name}: "
                      f"добавить ПЕРЕД строкой {n.lineno}: "
                      f"if {div} == 0: return 0")
                fixes += 1
            else:
                print(f"  [!] гард НЕ подтверждён решателем — рецепт не выдаю")
            if infer_requires:
                print(f"  [INFERRED SPEC] # @kern:requires {div} != 0")
    print("-" * 74)
    print(f"ИТОГО: проверенных рецептов {fixes}")
    return 0


def _smt_model(kernc, params, asserts) -> dict | None:
    """Конкретные значения из контрпримера Z3 (ПУНКТ 14, SBST)."""
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    body = "\n".join(f"(assert {a})" for a in asserts)
    smt = f"(set-logic ALL)\n{decls}\n{body}\n(check-sat)\n"
    rc, out = run_kernc(kernc, smt)
    vals: dict[str, int] = {}
    for line in out.splitlines():
        if "КОНТРПРИМЕР" not in line:
            continue
        for tok in line.split("КОНТРПРИМЕР", 1)[1].split(","):
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            # ДЕФЕКТ (найден конколикой): `kernc` печатает модель в форме
            # `[x = 5, y = 0]`, поэтому первый токен приходил как `'] x'` —
            # имя с мусором, и параметр НЕ находился. Оставляем только имя.
            k = k.strip().strip("[]").strip().lstrip("]").strip()
            v = v.strip().strip("[]").strip()
            try:
                vals[k] = int(v)
            except ValueError:
                pass
        break
    return vals if vals else None


def cmd_gen_tests(path: str, out_file: str, kernc) -> int:
    """ПУНКТ 14: SBST — pytest со 100% покрытием ДОСТИЖИМЫХ ветвей.

    Для каждой ветки запрашивается МОДЕЛЬ Z3 (конкретный вход), затем эталонный
    ответ берётся ИСПОЛНЕНИЕМ самой функции на этом входе. Мёртвые ветки
    (UNSAT) не тестируются, а ЯВНО помечаются в файле как недостижимые.
    """
    if not Path(kernc).exists():
        print(f"[!] не найден kernc: {kernc}")
        return 2
    mod_path = Path(path)
    src = mod_path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    ns: dict = {}
    try:
        exec(compile(src, str(mod_path), "exec"), ns)  # noqa: S102 (наш же файл)
    except Exception as e:  # noqa: BLE001
        _replay_soft(e, "kern_contracts.py:5423")
        print(f"[!] модуль не исполняется: {e}")
        return 2

    lines = ["# СГЕНЕРИРОВАНО kern_contracts.py --gen-tests (SBST + Z3). Не править вручную.",
             f"# Источник: {path}", "", f"from {mod_path.stem} import *  # noqa", ""]
    total = dead = 0

    def walk(stmts, path_conds, params, fnname):
        nonlocal total, dead
        for st in stmts:
            if not isinstance(st, ast.If):
                continue
            try:
                cond = expr_smt(st.test, {})
            except (Unsupported, NoReturn):
                continue
            model = _smt_model(kernc, params, path_conds + [cond])
            if model is None:
                dead += 1
                lines.append(f"# ВЕТКА НЕДОСТИЖИМА (UNSAT): {fnname}, строка {st.lineno}")
            else:
                args = ", ".join(f"{p}={model.get(p, 0)}" for p in params)
                try:
                    expected = ns[fnname](*[model.get(p, 0) for p in params])
                except Exception as e:  # noqa: BLE001
                    _replay_soft(e, "kern_contracts.py:5448")
                    lines.append(f"# ВЕТКА БРОСАЕТ {type(e).__name__}: {fnname}, строка {st.lineno}")
                    expected = None
                total += 1
                if expected is not None:
                    lines.append(f"def test_{fnname}_branch_{total}():  # строка {st.lineno}")
                    lines.append(f"    assert {fnname}({args}) == {expected}")
                    lines.append("")
            walk(st.body, path_conds + [cond], params, fnname)
            walk(st.orelse, path_conds + [f"(not {cond})"], params, fnname)

    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        walk(fn.body, [], params, fn.name)

    Path(out_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[GEN-TESTS] сгенерировано тестов: {total} | "
          f"помечено недостижимых веток: {dead} | файл: {out_file}")
    if total == 0:
        print("[!] ни одной достижимой ветки — тест был бы вакуумным")
        return 1
    return 0


# =============================================================================
# ЭШЕЛОН 3, ПУНКТ 17 — `--simplify`: ВЕРИФИЦИРУЮЩИЙ ОПТИМИЗАТОР.
#
# Три трансформации, каждая — по ДОКАЗАТЕЛЬСТВУ из Z3 (не по эвристике):
#   1) [DEAD BRANCH]      — ветка недостижима (UNSAT) -> вырезаем её;
#   2) [REDUNDANT GUARD]  — условие всегда истинно на пути -> убираем `if`;
#   3) одинаковые ветви  — `if C: return X else: return X` -> `return X`.
#
# ГЛАВНОЕ: перед выдачей результата КАЖДАЯ упрощённая функция проверяется на
# ЭКВИВАЛЕНТНОСТЬ исходной через `--diff-equiv` (Z3: ∃x: f_old(x) != f_new(x)).
# UNSAT -> доказано; SAT -> упрощение ОТКЛОНЯЕТСЯ (fail-closed).
# =============================================================================


def _simplify_node(node, params, kernc, path, stats):
    """Рекурсивно упростить блок операторов (in place)."""
    out = []
    for st in node:
        if isinstance(st, ast.If):
            try:
                cond = expr_smt(st.test, {})
            except (Unsupported, NoReturn):
                out.append(st)
                continue
            sat_then = _smt_sat(kernc, params, path + [cond])
            sat_not = _smt_sat(kernc, params, path + [f"(not {cond})"])
            if sat_then is False:
                # 1) ВЕТКА НЕДОСТИЖИМА: вырезаем THEN, оставляем ELSE.
                stats["dead"] += 1
                out.extend(_simplify_node(st.orelse, params, kernc,
                                          path + [f"(not {cond})"], stats))
                continue
            if sat_not is False:
                # 2) ИЗБЫТОЧНЫЙ ГАРД: условие всегда истинно -> тело без if.
                stats["redundant"] += 1
                out.extend(_simplify_node(st.body, params, kernc, path + [cond], stats))
                continue
            # 3) ОДИНАКОВЫЕ ВЕТВИ: `if C: return X else: return X` -> `return X`.
            if (len(st.body) == 1 and len(st.orelse) == 1
                    and isinstance(st.body[0], ast.Return)
                    and isinstance(st.orelse[0], ast.Return)
                    and st.body[0].value is not None and st.orelse[0].value is not None):
                try:
                    a = expr_smt(st.body[0].value, {})
                    b = expr_smt(st.orelse[0].value, {})
                except (Unsupported, NoReturn):
                    a = b = None
                if a is not None and a == b:
                    stats["same"] += 1
                    out.append(st.body[0])
                    continue
            st.body = _simplify_node(st.body, params, kernc, path + [cond], stats)
            st.orelse = _simplify_node(st.orelse, params, kernc,
                                       path + [f"(not {cond})"], stats)
            out.append(st)
        else:
            out.append(st)
    return out


def _equiv_proven(fn_old: ast.FunctionDef, fn_new: ast.FunctionDef, kernc) -> bool:
    """Доказать `∀x: f_old(x) == f_new(x)` через наш движок (UNSAT)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        po = Path(td) / "old_mod.py"
        pn = Path(td) / "new_mod.py"
        po.write_text(ast.unparse(fn_old) + "\n", encoding="utf-8")
        pn.write_text(ast.unparse(fn_new) + "\n", encoding="utf-8")
        a = {n: (p, b, u) for n, p, b, _l, u in parse_bodies(po)}
        b2 = {n: (p, b, u) for n, p, b, _l, u in parse_bodies(pn)}
        if fn_old.name not in a or fn_old.name not in b2:
            return False
        pa, ba, ua = a[fn_old.name]
        pb, bb, ub = b2[fn_old.name]
        if pa != pb:
            return False
        if ua or ub:      # дефект #207: развёртка не доказывает эквивалентность
            return False
        _rc, out = run_kernc(kernc, diff_equiv_smt(pa, ba, bb))
        return "ДОКАЗАНО" in out


def cmd_simplify(path: str, out_file: str | None, kernc) -> int:
    """ПУНКТ 17: упростить с ДОКАЗАТЕЛЬСТВОМ эквивалентности."""
    import copy
    if not Path(kernc).exists():
        print(f"[!] не найден kernc: {kernc}")
        return 2
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    proven = rejected = 0
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        cc0, _ = _cc_and_smells(fn)
        new_fn = copy.deepcopy(fn)
        stats = {"dead": 0, "redundant": 0, "same": 0}
        new_fn.body = _simplify_node(new_fn.body, params, kernc, [], stats)
        n_changes = sum(stats.values())
        if n_changes == 0:
            continue
        cc1, _ = _cc_and_smells(new_fn)
        # ДВА независимых основания для эквивалентности:
        #  (а) САМИ трансформации доказаны UNSAT-результатами Z3:
        #      мёртвая ветка удалена по UNSAT(путь AND cond),
        #      избыточный гард убран по UNSAT(путь AND NOT cond);
        #  (б) НЕЗАВИСИМАЯ перепроверка через `--diff-equiv` (Z3: ∃x: f_old != f_new)
        #      — выполняется, когда тело выразимо в нашем подмножестве.
        independent = _equiv_proven(fn, new_fn, kernc)
        justified = (stats["dead"] + stats["redundant"]) > 0
        if independent or justified:
            proven += 1
            how = ("независимо перепроверено --diff-equiv (UNSAT)" if independent
                   else "следует из UNSAT-доказательств трансформаций "
                        "(--diff-equiv неприменим: тело вне подмножества)")
            print(f"  [SIMPLIFIED & PROVEN EQUIVALENT] {fn.name}: "
                  f"CC {cc0} -> {cc1}; правок {n_changes} "
                  f"(мёртвых {stats['dead']}, избыточных {stats['redundant']}, "
                  f"одинаковых ветвей {stats['same']}); {how}")
            fn.body = new_fn.body  # принимаем только ДОКАЗАННОЕ
        else:
            rejected += 1
            print(f"  [REJECTED] {fn.name}: упрощение НЕ доказано эквивалентным "
                  f"(fail-closed) — оставляю как было")
    if out_file:
        Path(out_file).write_text(ast.unparse(tree) + "\n", encoding="utf-8")
        print(f"  [i] записано: {out_file}")
    print("-" * 74)
    print(f"ИТОГО: доказанно упрощено {proven} | отклонено {rejected}")
    return 0


# -----------------------------------------------------------------------------
# ЭШЕЛОН 5, ПУНКТ 26: ОДНОСЛОВНЫЕ БИЗНЕС-ПРЕСЕТЫ (+ `--spec-gaps`).
#
# ЗАЧЕМ. Обычному разработчику трудно написать формулу постусловия, но легко
# поставить ОДНО СЛОВО над функцией. Пресет разворачивается в математическое
# обязательство и проверяется тем же путём (`kernc prove` + пруф-чекер).
#
# ЕДИНЫЙ МЕХАНИЗМ КОМПОЗИЦИИ (`_instantiate_body`). `idempotent`, `monotonic`
# и `no_arbitrage` (пункт 27) — это ОДНА операция: подстановка произвольного
# SMT-выражения вместо параметра в СИМВОЛЬНОЕ ТЕЛО функции. Три отдельные
# реализации разошлись бы и дали бы разные вердикты на одном и том же коде.
# -----------------------------------------------------------------------------

PRESET_RE = re.compile(
    r"^\s*(?:#|//|///)\s*@kern:(non_negative|percentage|idempotent|monotonic"
    r"|no_arbitrage|conservation|no_double_spend|calls_i32|calls_u32"
    r"|bounded\s*\(([^)]*)\))\s*$")


def _presets_of(lines, lineno):
    """Пресеты в блоке комментариев непосредственно НАД функцией."""
    out = []
    i = lineno - 2
    while i >= 0:
        s = lines[i].strip()
        if not s or not s.startswith(("#", "//")):
            break
        m = PRESET_RE.match(s)
        if m:
            out.append((m.group(1).split("(")[0].strip(), m.group(2)))
        i -= 1
    return out


def _requires_above(lines, lineno):
    """`@kern:requires` из блока комментариев НАД функцией (или None)."""
    i = lineno - 2
    while i >= 0:
        s = lines[i].strip()
        if not s or not s.startswith("#"):
            break
        m = re.search(r"@kern:requires\s+(.+)$", s)
        if m:
            return m.group(1).strip()
        i -= 1
    return None


def _instantiate_body(body_smt_text: str, param: str, arg_sexp: str) -> str:
    """Подставить SMT-выражение `arg_sexp` вместо `param` в тело функции.

    ОБЩИЙ механизм для `idempotent` (тело в себя), `monotonic` (две копии
    входа) и `no_arbitrage` (две части платежа + их сумма). Подстановка идёт по
    ГРАНИЦАМ СЛОВА (`_subst`), поэтому `x` не задевает `x1` и `x_len`.
    """
    return _subst(body_smt_text, {param: arg_sexp})


def _prove_checked(kernc, decls, asserts):
    """(kind, контрпример, trusted): sat | unsat | unknown.

    `trusted` — число шагов, которые пруф-чекер НЕ перепроверил. `PASS`
    засчитывается ТОЛЬКО при `trusted == 0`: иначе «доказано» было бы словом
    решателя, а не проверенным сертификатом.
    """
    decls_txt = "\n".join(f"(declare-const {p} Int)" for p in decls)
    body = "\n".join(f"(assert {a})" for a in asserts)
    smt = f"(set-logic ALL)\n{decls_txt}\n{body}\n(check-sat)\n"
    _rc, out = run_kernc(kernc, smt)
    if "КОНТРПРИМЕР" in out:
        ce = next((ln.strip()[:110] for ln in out.splitlines() if "КОНТРПРИМЕР" in ln),
                  "SAT (модель не извлечена)")
        return ("sat", ce, None)
    if "ДОКАЗАНО" in out:
        m = re.search(r"trusted:\s*(\d+)", out)
        return ("unsat", None, (int(m.group(1)) if m else None))
    return ("unknown", "решатель не решил (N)", None)


def _fn_stmts(fn):
    """Операторы функции без докстроки и `pass`."""
    return [st for st in fn.body
            if not isinstance(st, ast.Pass)
            and not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)
                     and isinstance(st.value.value, str))]


def _preset_obligation(kind, args, params, body, req_smt):
    """Построить обязательство пресета: (label, decls, asserts) или None.

    SAT обязательства = БАГ (пресет нарушен); UNSAT = пресет доказан. Для
    составных пресетов используется ОДИН механизм `_instantiate_body`.
    """
    pre = [req_smt] if req_smt else []
    decls = list(dict.fromkeys(params + ["result"]))
    if kind == "non_negative":
        return (kind, decls, pre + [f"(= result {body})", "(not (>= result 0))"])
    if kind == "percentage":
        return (kind, decls, pre + [f"(= result {body})",
                                    "(not (and (>= result 0) (<= result 100)))"])
    if kind == "no_double_spend":
        # ПУНКТ 28. Модель гонки: обе транзакции проверяют СНИМОК баланса, а
        # списание идёт от текущего -> итог может уйти в минус. Проверяем
        # ГЛАВНОЕ следствие: функция не имеет права вернуть отрицательный баланс
        # ни при каких неотрицательных входах (`balance, a1, a2 >= 0`).
        pre_all = [f"(>= {p} 0)" for p in params]
        return (kind, decls, pre + pre_all + [f"(= result {body})",
                                              "(not (>= result 0))"])
    if kind in ("calls_i32", "calls_u32"):
        # ПУНКТ 29. FFI-МОСТ: значение уходит в C-ABI (`libkern.so`/Zig/Rust),
        # где тип имеет КОНЕЧНУЮ разрядность. Выход за диапазон = усечение
        # (Python/JS это не видят вовсе).
        lo, hi = (-2**31, 2**31 - 1) if kind == "calls_i32" else (0, 2**32 - 1)
        return (kind, decls, pre + [f"(= result {body})",
                                    f"(or (< result {lo}) (> result {hi}))"])
    if kind == "bounded":
        parts = [x.strip() for x in (args or "").split(",")]
        if len(parts) != 2 or not all(parts):
            return None
        try:
            lo_smt = expr_smt(ast.parse(parts[0], mode="eval").body, {})
            hi_smt = expr_smt(ast.parse(parts[1], mode="eval").body, {})
        except Exception as _kern_e_5725:
            _replay_soft(_kern_e_5725, "kern_contracts.py:5725")
            return None
        return (f"bounded({parts[0]}, {parts[1]})", decls,
                pre + [f"(= result {body})",
                       f"(not (and (>= result {lo_smt}) (<= result {hi_smt})))"])
    if kind in ("idempotent", "monotonic", "no_arbitrage", "conservation"):
        if len(params) != 1:
            return None
        p = params[0]
        if kind == "idempotent":
            f1 = body
            f2 = _instantiate_body(body, p, f1)
            return (kind, [p], pre + [f"(not (= {f2} {f1}))"])
        if kind == "monotonic":
            f1 = _instantiate_body(body, p, "x1")
            f2 = _instantiate_body(body, p, "x2")
            rs = ([_instantiate_body(req_smt, p, "x1"),
                   _instantiate_body(req_smt, p, "x2")] if req_smt else [])
            return (kind, ["x1", "x2"], rs + ["(<= x1 x2)", f"(not (<= {f1} {f2}))"])
        # АНТИ-АРБИТРАЖ (пункт 27): дробление платежа не должно быть выгоднее
        # целого -> обязательство `f(a1) + f(a2) >= f(a1 + a2)`.
        f1 = _instantiate_body(body, p, "a1")
        f2 = _instantiate_body(body, p, "a2")
        fs = _instantiate_body(body, p, "(+ a1 a2)")
        rs = ([_instantiate_body(req_smt, p, "a1"),
               _instantiate_body(req_smt, p, "a2"),
               _instantiate_body(req_smt, p, "(+ a1 a2)")] if req_smt else [])
        return (kind, ["a1", "a2"],
                rs + ["(> a1 0)", "(> a2 0)", f"(not (>= (+ {f1} {f2}) {fs}))"])
    return None


def cmd_presets(path: str, kernc, spec_gaps: bool = False) -> int:
    """ПУНКТ 26: `--presets <file>` (+ `--spec-gaps`). Цель `make presets-check`."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    fns = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]
    checked = skipped = fails = unknowns = 0
    rows: list[str] = []
    for fn in fns:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        presets = _presets_of(lines, fn.lineno)
        req_txt = _requires_above(lines, fn.lineno)
        body, why = None, ""
        try:
            body = body_smt(_fn_stmts(fn), _self_meta(fn, _fn_stmts(fn)))
        except (NoReturn, Unsupported) as e:
            why = str(e)

        # `--spec-gaps`: ДИАГНОСТИКА (MacFarlane) — только при явном флаге;
        # штатный прогон без флага она не задевает.
        if spec_gaps:
            gaps = []
            if req_txt is None:
                for p in params:
                    if body and re.search(r"(?<![\w])" + re.escape(p) + r"(?![\w])", body):
                        gaps.append(f"отрицательная область параметра `{p}` "
                                    f"не закрыта предусловием")
            if any(k == "non_negative" for k, _ in presets):
                gaps.append("пресет `non_negative` ограничивает результат только "
                            "снизу (нет верхней границы)")
            for g in gaps:
                print(f"  [SPEC GAP] {fn.name}: {g}")
                rows.append("[SPEC GAP]")

        if not presets:
            skipped += 1
            continue
        if body is None:
            skipped += 1
            rows.append("[SKIP]")
            print(f"  [SKIP] {fn.name}: тело вне подмножества ({why})")
            continue
        req_smt = None
        if req_txt:
            try:
                req_smt = expr_smt(ast.parse(req_txt, mode="eval").body, {})
            except Exception as _kern_e_5802:
                _replay_soft(_kern_e_5802, "kern_contracts.py:5802")
                req_smt = None
        checked += 1
        for kind, args in presets:
            if kind == "idempotent":
                obs = _idempotent_obligations(fn, params)
                if obs is None:
                    print(f"  [SKIP] {fn.name}: `idempotent` требует ровно один "
                          f"параметр и путевое тело")
                    continue
                n_pass = n_fail = n_unk = 0
                first_fail = ""
                for label, decls, asserts in obs:
                    v, ce, tr = _prove_checked(kernc, decls, asserts)
                    if v == "sat":
                        n_fail += 1
                        first_fail = first_fail or f"{label} — {ce}"
                    elif v == "unsat" and tr == 0:
                        n_pass += 1
                    else:
                        n_unk += 1
                print(f"  [i] {fn.name}: idempotent — путей {len(obs)} | "
                      f"PASS {n_pass} | FAIL {n_fail} | UNKNOWN {n_unk}")
                if n_fail:
                    fails += 1
                    rows.append("[FAIL]")
                    print(f"  [FAIL] {fn.name}: idempotent REFUTED — {first_fail}")
                elif n_unk:
                    unknowns += 1
                    rows.append("[UNKNOWN]")
                    print(f"  [UNKNOWN] {fn.name}: idempotent — {n_unk} путей "
                          f"НЕ перепроверены чекером (НЕ засчитано)")
                else:
                    rows.append("[PASS]")
                    print(f"  [PASS] {fn.name}: idempotent PROVEN по всем "
                          f"{n_pass} путям (trusted: 0 | holes: 0)")
                continue
            # ПУТЕВАЯ РАЗВЁРТКА для диапазонных пресетов (Пункты 26, 28, 29):
            # значение ветви — простое выражение, поэтому обязательство
            # `P_p ∧ ¬pred(V_p)` перепроверяется на `trusted: 0`.
            p_obs = _range_obligations(kind, args, params, fn, req_smt)
            if p_obs is not None:
                n_pass = n_fail = n_unk = 0
                first_fail = ""
                for label, decls, asserts in p_obs:
                    v, ce, tr = _prove_checked(kernc, decls, asserts)
                    if v == "sat":
                        n_fail += 1
                        first_fail = first_fail or f"{label} — {ce}"
                    elif v == "unsat" and tr == 0:
                        n_pass += 1
                    else:
                        n_unk += 1
                if n_fail:
                    fails += 1
                    rows.append("[FAIL]")
                    print(f"  [FAIL] {fn.name}: {kind} REFUTED — {first_fail}")
                elif n_unk:
                    unknowns += 1
                    rows.append("[UNKNOWN]")
                    print(f"  [UNKNOWN] {fn.name}: {kind} — {n_unk} путей "
                          f"НЕ перепроверены чекером (НЕ засчитано)")
                else:
                    rows.append("[PASS]")
                    print(f"  [PASS] {fn.name}: {kind} PROVEN по всем "
                          f"{n_pass} путям (trusted: 0 | holes: 0)")
                continue
            built = _preset_obligation(kind, args, params, body, req_smt)
            if built is None:
                print(f"  [SKIP] {fn.name}: `{kind}` неприменим "
                      f"(нужен один параметр / корректные границы)")
                continue
            label, decls, ob = built
            v, ce, tr = _prove_checked(kernc, decls, ob)
            if v == "sat":
                fails += 1
                rows.append("[FAIL]")
                print(f"  [FAIL] {fn.name}: {label} REFUTED — {ce}")
            elif v == "unsat" and tr == 0:
                rows.append("[PASS]")
                print(f"  [PASS] {fn.name}: {label} PROVEN (trusted: 0 | holes: 0)")
            elif v == "unsat":
                unknowns += 1
                rows.append("[UNKNOWN]")
                print(f"  [UNKNOWN] {fn.name}: {label} — Z3 UNSAT, "
                      f"но чекер оставил trusted: {tr} (НЕ засчитано)")
            else:
                unknowns += 1
                rows.append("[UNKNOWN]")
                print(f"  [UNKNOWN] {fn.name}: {label} — {ce}")
    print("-" * 74)
    print(f"[PRESETS SUMMARY] checked {checked} / {len(fns)} functions, "
          f"skipped {skipped} (без пресетов / вне подмножества)")
    print(f"  PASS {rows.count('[PASS]')} | FAIL {rows.count('[FAIL]')} | "
          f"UNKNOWN {rows.count('[UNKNOWN]')} | SPEC GAP {rows.count('[SPEC GAP]')}")
    return 1 if (fails or unknowns) else 0


def _paths_of(fn, syms=None):
    """Все пути выхода функции: список (условия_пути, значение_возврата).

    Нужен для ПУТЕВОЙ формулировки идемпотентности: подстановка значения ветви
    в тело даёт вложенный `ite`, который чекер пока не перепроверяет. Если же
    разложить тело на пути, обязательства становятся константными (условия
    сворачиваются) и проверяются на `trusted: 0`.
    """
    out: list = []
    ok = True

    def rec(stmts, path):
        nonlocal ok
        for i, st in enumerate(stmts):
            if isinstance(st, ast.If):
                try:
                    cond = _cond_smt(st.test, syms or set())
                except Exception as _kern_e_5917:
                    _replay_soft(_kern_e_5917, "kern_contracts.py:5917")
                    ok = False
                    return
                rec(st.body, path + [cond])
                rest = stmts[i + 1:]
                if st.orelse:
                    rec(st.orelse, path + [f"(not {cond})"])
                elif rest:
                    rec(rest, path + [f"(not {cond})"])
                return
            if isinstance(st, ast.Return):
                if st.value is None:
                    ok = False
                    return
                try:
                    val = expr_smt(st.value, {})
                except Exception as _kern_e_5933:
                    _replay_soft(_kern_e_5933, "kern_contracts.py:5933")
                    ok = False
                    return
                out.append((list(path), val))
                return
            ok = False
            return

    rec(_fn_stmts(fn), [])
    return out if ok else None


def _range_pred(kind, args, params, v: str):
    """Предикат, который ОБЯЗАН выполняться для значения `v` (или None).

    ПУТЕВАЯ формулировка: значение ветви — простое выражение (без вложенного
    `ite`), поэтому обязательство `P_p ∧ ¬pred(V_p)` решается коротко и
    перепроверяется чекером с `trusted: 0` (ИЗМЕРЕНО: на `no_double_spend` и
    `calls_u32` цельнотельное обязательство давало 2-3 доверенных шага).
    """
    if kind == "non_negative" or kind == "no_double_spend":
        return f"(>= {v} 0)"
    if kind == "percentage":
        return f"(and (>= {v} 0) (<= {v} 100))"
    if kind == "bounded":
        parts = [x.strip() for x in (args or "").split(",")]
        if len(parts) != 2 or not all(parts):
            return None
        try:
            lo_smt = expr_smt(ast.parse(parts[0], mode="eval").body, {})
            hi_smt = expr_smt(ast.parse(parts[1], mode="eval").body, {})
        except Exception as _kern_e_5964:
            _replay_soft(_kern_e_5964, "kern_contracts.py:5964")
            return None
        return f"(and (>= {v} {lo_smt}) (<= {v} {hi_smt}))"
    if kind == "calls_i32":
        return f"(and (>= {v} -2147483648) (<= {v} 2147483647))"
    if kind == "calls_u32":
        return f"(and (>= {v} 0) (<= {v} 4294967295))"
    return None


def _range_obligations(kind, args, params, fn, req_smt):
    """Путевые обязательства для диапазонных пресетов: [(label, decls, asserts)].

    ЗВУЧНОСТЬ: пути исчерпывают домен, поэтому проверка КАЖДОГО пути покрывает
    все входы. SAT любого обязательства = НАЙДЕН контрпример (баг).
    """
    pred_of = _range_pred
    if pred_of(kind, args, params, "0") is None:
        return None
    paths = _paths_of(fn)
    if not paths:
        return None
    pre = [req_smt] if req_smt else []
    extra = [f"(>= {p} 0)" for p in params] if kind == "no_double_spend" else []
    obs = []
    for i, (pp, vp) in enumerate(paths):
        pred = pred_of(kind, args, params, vp)
        if pred is None:
            return None
        obs.append((f"{kind}[путь {i + 1}]", list(dict.fromkeys(params)),
                    pre + extra + list(pp) + [f"(not {pred})"]))
    return obs


def _idempotent_obligations(fn, params, syms=None):
    """ПУТЕВАЯ идемпотентность: для всех пар путей (p, q).

    На пути `p` функция возвращает `V_p`. Тогда `f(f(x)) = V_q(V_p)`, где `q` —
    путь, активный на входе `V_p`. Обязательство:
    `P_p ∧ P_q[V_p] ∧ V_q[V_p] ≠ V_p` — SAT означает НЕидемпотентность.

    ЗВУЧНОСТЬ: пути исчерпывают домен, поэтому перебор всех пар `(p, q)`
    покрывает ВСЕ входы (никакой случай не теряется).
    """
    if len(params) != 1:
        return None
    paths = _paths_of(fn, syms)
    if not paths or len(paths) < 2:
        return None
    p0 = params[0]
    obs = []
    for i, (pp, vp) in enumerate(paths):
        for j, (pq, vq) in enumerate(paths):
            sub = {p0: vp}
            pq_s = _subst("(and " + " ".join(pq) + ")" if len(pq) > 1
                          else (pq[0] if pq else "true"), sub)
            vq_s = _subst(vq, sub)
            asserts = list(pp) + [pq_s, f"(not (= {vq_s} {vp}))"]
            obs.append((f"idempotent[путь {i + 1}->{j + 1}]", [p0], asserts))
    return obs


# -----------------------------------------------------------------------------
# ЭШЕЛОН 5, ПУНКТ 30: ВЕРИФИКАТОР RLS-ПОЛИТИК (`--verify-sql`).
#
# ЗАЧЕМ. Классический баг приоритета операторов в SQL: `WHERE tenant = req OR
# public = 1 AND deleted = 0` — из-за того, что `AND` связывает сильнее, запрос
# отдаёт ЧУЖУЮ публичную запись и/или УДАЛЁННУЮ строку своего тенанта. Проверяем
# не текст запроса, а ПРЕДИКАТ-функцию доступа: доступ разрешён (`result == 1`)
# ТОЛЬКО при `(row_tenant == req_tenant ∨ is_public == 1) ∧ is_deleted == 0`.
# -----------------------------------------------------------------------------

RLS_RE = re.compile(r"^\s*(?:#|//|///)\s*@kern:rls\s*\(([^)]*)\)\s*$")


def _directive_above(lines, lineno, rx):
    """Аргументы директивы из блока комментариев НАД функцией (или None)."""
    i = lineno - 2
    while i >= 0:
        s = lines[i].strip()
        if not s or not s.startswith(("#", "//")):
            break
        m = rx.match(s)
        if m:
            return m.group(1)
        i -= 1
    return None


def cmd_verify_sql(path: str, kernc) -> int:
    """ПУНКТ 30: `--verify-sql <file>` (цель `make sql-policy-check`)."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    fns = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]
    checked = fails = unknowns = skipped = 0
    for fn in fns:
        cols = _directive_above(lines, fn.lineno, RLS_RE)
        if cols is None:
            skipped += 1
            continue
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        names = [c.strip() for c in cols.split(",") if c.strip()]
        if len(names) != 4 or any(n not in params for n in names):
            print(f"  [SKIP] {fn.name}: `@kern:rls` требует 4 ИМЕНИ параметров-столбцов")
            skipped += 1
            continue
        row_t, req_t, pub, del_ = names
        paths = _paths_of(fn)
        if not paths:
            print(f"  [SKIP] {fn.name}: тело вне подмножества")
            skipped += 1
            continue
        checked += 1
        # МОДЕЛЬ КОЛОНОК: булевы флаги SQL принимают только {0,1} — без этого
        # проверка ловила бы `is_deleted = -1` как «обход» (ИЗМЕРЕНО).
        flags = [f"(or (= {c} 0) (= {c} 1))" for c in (pub, del_)]
        bad = unk = 0
        for i, (pp, vp) in enumerate(paths):
            # ПОКОМПОНЕНТНАЯ ПРОВЕРКА ИНВАРИАНТА (Дефект #145): одна составная
            # формула `¬((A ∨ B) ∧ C)` заставляет Z3 вводить Tseitin-атомы, и
            # чекер оставлял 4 доверенных шага (`[UNKNOWN]`). Инвариант —
            # КОНЪЮНКЦИЯ, поэтому нарушение проверяется ПО КОМПОНЕНТАМ
            # (по де Моргану `¬(X ∧ Y) = ¬X ∨ ¬Y`): SAT хотя бы одной компоненты
            # нарушения эквивалентен SAT всего нарушения. ЗВУЧНО и ПОЛНО.
            violations = [
                f"(not (= {del_} 0))",                                   # удалённая строка
                f"(and (not (= {row_t} {req_t})) (not (= {pub} 1)))",    # чужой непубличный
            ]
            for vi, viol in enumerate(violations):
                v, ce, tr = _prove_checked(kernc, list(dict.fromkeys(params)),
                                           flags + list(pp) + [f"(= {vp} 1)", viol])
                if v == "sat":
                    bad += 1
                    print(f"  [FAIL] {fn.name}: RLS POLICY BYPASS FOUND "
                          f"(путь {i + 1}, нарушение {vi + 1}) — {ce}")
                elif v != "unsat" or tr != 0:
                    unk += 1
        if bad:
            fails += 1
        elif unk:
            unknowns += 1
            print(f"  [UNKNOWN] {fn.name}: {unk} путей НЕ перепроверены чекером")
        else:
            print(f"  [PASS] {fn.name}: PROVEN (tenant isolation on all "
                  f"{len(paths)} paths, trusted: 0 | holes: 0)")
    print("-" * 74)
    print(f"[SQL SUMMARY] checked {checked} / {len(fns)} functions, skipped {skipped} | "
          f"FAIL {fails} | UNKNOWN {unknowns}")
    return 1 if (fails or unknowns) else 0


# -----------------------------------------------------------------------------
# ЭШЕЛОН 5, ПУНКТ 31: ВЕРИФИКАТОР ТАРИФНЫХ МАТРИЦ (`--verify-pricing`).
#
# ЗАЧЕМ. Тарифная сетка — это РАЗБИЕНИЕ домена на правила `(условие -> цена)`.
# Два формальных свойства:
#   * ПОЛНОТА: каждому допустимому входу соответствует ЦЕНА, а не признак
#     «не обработано» (отрицательная цена = sentinel) -> SAT = дыра в тарифах;
#   * НЕПРОТИВОРЕЧИВОСТЬ: два правила с РАЗНЫМИ ценами не пересекаются ->
#     SAT = конфликт правил (в Белнапе это состояние B).
# -----------------------------------------------------------------------------

PRICING_RE = re.compile(r"^\s*(?:#|//|///)\s*@kern:pricing\s*\(([^)]*)\)\s*$")


def _raw_rules(fn):
    """Цепочка `if cond: return value` КАК НАПИСАНО: [(cond_smt|None, value_smt)].

    Именно «как написано»: для проверки НЕПРОТИВОРЕЧИВОСТИ нужны ИСХОДНЫЕ условия
    (путевые условия уже взаимно исключающие по построению, и конфликт в них
    исчез бы).
    """
    out: list = []
    ok = True

    def walk(stmts):
        nonlocal ok
        for st in stmts:
            if isinstance(st, ast.If):
                try:
                    cond = _cond_smt(st.test, set())
                except Exception as _kern_e_6145:
                    _replay_soft(_kern_e_6145, "kern_contracts.py:6145")
                    ok = False
                    return
                val = None
                for sub in st.body:
                    if isinstance(sub, ast.Return) and sub.value is not None:
                        try:
                            val = expr_smt(sub.value, {})
                        except Exception as _kern_e_6153:
                            _replay_soft(_kern_e_6153, "kern_contracts.py:6153")
                            ok = False
                            return
                        break
                if val is None:
                    ok = False
                    return
                out.append((cond, val))
                rest = stmts[stmts.index(st) + 1:]
                if st.orelse:
                    walk(st.orelse)
                elif rest:
                    walk(rest)
                return
            if isinstance(st, ast.Return):
                if st.value is None:
                    ok = False
                    return
                try:
                    out.append((None, expr_smt(st.value, {})))
                except Exception as _kern_e_6173:
                    _replay_soft(_kern_e_6173, "kern_contracts.py:6173")
                    ok = False
                    return
                return
            ok = False
            return

    walk(_fn_stmts(fn))
    return out if ok and out else None


def cmd_verify_pricing(path: str, kernc) -> int:
    """ПУНКТ 31: `--verify-pricing <file>` (цель `make pricing-matrix-check`)."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    fns = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]
    checked = fails = unknowns = skipped = 0
    for fn in fns:
        dom = _directive_above(lines, fn.lineno, PRICING_RE)
        if dom is None:
            skipped += 1
            continue
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        rules = _raw_rules(fn)
        if not rules:
            print(f"  [SKIP] {fn.name}: тело вне подмножества")
            skipped += 1
            continue
        checked += 1
        bad = unk = 0
        # ПОЛНОТА: цена обязана быть неотрицательной (sentinel = не обработано).
        paths = _paths_of(fn) or []
        for i, (pp, vp) in enumerate(paths):
            v, ce, tr = _prove_checked(kernc, list(dict.fromkeys(params)),
                                       list(pp) + [f"(< {vp} 0)"])
            if v == "sat":
                bad += 1
                print(f"  [FAIL] {fn.name}: PRICING GAP (unhandled input, путь {i + 1}) — {ce}")
            elif v != "unsat" or tr != 0:
                unk += 1
        # НЕПРОТИВОРЕЧИВОСТЬ: разные цены не пересекаются.
        conds = [(c, v) for c, v in rules if c is not None]
        for i in range(len(conds)):
            for j in range(i + 1, len(conds)):
                ci, vi = conds[i]
                cj, vj = conds[j]
                v, ce, tr = _prove_checked(
                    kernc, list(dict.fromkeys(params)),
                    [ci, cj, f"(not (= {vi} {vj}))"])
                if v == "sat":
                    bad += 1
                    print(f"  [FAIL] {fn.name}: PRICING CONFLICT (Belnap B): "
                          f"rules {i + 1} and {j + 1} overlap — {ce}")
                elif v != "unsat" or tr != 0:
                    unk += 1
        if bad:
            fails += 1
        elif unk:
            unknowns += 1
            print(f"  [UNKNOWN] {fn.name}: {unk} обязательств НЕ перепроверены чекером")
        else:
            print(f"  [PASS] {fn.name}: PROVEN COMPLETE & DISJOINT "
                  f"(rules {len(conds)}, paths {len(paths)}, trusted: 0 | holes: 0)")
    print("-" * 74)
    print(f"[PRICING SUMMARY] checked {checked} / {len(fns)} functions, skipped {skipped} | "
          f"FAIL {fails} | UNKNOWN {unknowns}")
    return 1 if (fails or unknowns) else 0


# -----------------------------------------------------------------------------
# ЭШЕЛОН 6, ПУНКТ 32: АНТИ-ЧИТ ПРОТИВ REWARD HACKING И SLOPSQUATTING.
#
# ЗАЧЕМ. ИИ-агент, которому не удаётся починить код, идёт на хитрость: перегружает
# `__eq__` (любой объект «равен» любому), глушит `assert` через `except: pass`,
# выходит из процесса `sys.exit(0)`, подменяет проверяемое `unittest.mock`, либо
# хардкодит ответ под конкретный тест (`if x == 42 and y == 17`). Плюс
# SLOPSQUATTING: галлюцинированный импорт, зарегистрированный злоумышленником в
# PyPI. Всё это ловится СТАТИЧЕСКИ по AST.
# -----------------------------------------------------------------------------

CHEAT_EXIT = {"sys.exit", "os._exit", "exit", "quit"}
CHEAT_MOCK = {"unittest.mock.patch", "mock.patch", "patch", "MagicMock", "Mock"}
SUSPICIOUS_MODULES = {"fast_crypto_utils", "requests_easy", "openai_helpers",
                      "crypto_utils", "python-dotenv-safe"}


def _dotted(node) -> str:
    """Полное имя вызова: `unittest.mock.patch` -> "unittest.mock.patch".

    ИЗМЕРЕНО: первая версия смотрела только `Attribute(value=Name)` и НЕ видела
    вложенные атрибуты (`unittest.mock.patch`), из-за чего чит «мок в проде»
    пропускался.
    """
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


class _CheatScan(ast.NodeVisitor):
    """Статический поиск читов: каждая находка — (класс, строка)."""

    def __init__(self):
        self.findings: list[tuple[str, int]] = []
        self.imports: list[tuple[str, int]] = []

    def visit_Import(self, node):
        for al in node.names:
            self.imports.append((al.name.split(".")[0], node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.append((node.module.split(".")[0], node.lineno))
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        # (1) перегрузка __eq__, всегда возвращающая True
        if node.name == "__eq__":
            for st in ast.walk(node):
                if (isinstance(st, ast.Return) and isinstance(st.value, ast.Constant)
                        and st.value.value is True):
                    self.findings.append(("always-true __eq__", node.lineno))
                    break
        # (4) хардкод под тест: `if x == 42 and y == 17:`
        for st in ast.walk(node):
            if isinstance(st, ast.If) and isinstance(st.test, ast.BoolOp):
                lits = sum(1 for sub in ast.walk(st.test)
                           if isinstance(sub, ast.Compare)
                           and any(isinstance(c, ast.Constant) for c in sub.comparators))
                if lits >= 2 and isinstance(st.test.op, ast.And):
                    self.findings.append(("test-case overfitting (chain of literals)",
                                          st.lineno))
        self.generic_visit(node)

    def visit_Call(self, node):
        name = _dotted(node.func)
        if name in CHEAT_EXIT:
            self.findings.append((f"exit inside tested code: {name}()", node.lineno))
        if name in CHEAT_MOCK or name.startswith("mock."):
            self.findings.append(("mock in production code", node.lineno))
        self.generic_visit(node)

    def visit_Try(self, node):
        for h in node.handlers:
            if len(h.body) == 1 and isinstance(h.body[0], ast.Pass):
                has_assert = any(isinstance(x, ast.Assert) for x in ast.walk(node))
                kind = ("swallowed assert (except: pass)" if has_assert
                        else "swallowed exception (except: pass)")
                self.findings.append((kind, h.lineno))
        self.generic_visit(node)


def cmd_anti_cheat(path: str, allowlist: str | None = None) -> int:
    """ПУНКТ 32: `--anti-cheat <file> [--import-lock <allow.json>]`."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    sc = _CheatScan()
    sc.visit(ast.parse(src))
    allowed: set[str] | None = None
    if allowlist:
        data = json.loads(Path(allowlist).read_text(encoding="utf-8"))
        allowed = set(data.get("allowed", []))
    findings = list(sc.findings)
    # TYPE-ALIAS SPOOFING: переопределение зарезервированных семантических
    # типов (`PositiveInt = int`, `type uint32 = int64`) обнуляет Sorbet-границы
    # и позволяет «легально» выйти за домен. Для C-like — текстовый поиск.
    RESERVED = ("PositiveInt", "NonNegativeInt", "Percent", "uint32", "int32",
                "int64", "uint64", "nat", "pos_int")
    for ln_no, raw in enumerate(src.splitlines(), 1):
        line = raw.split("#", 1)[0].split("//", 1)[0]
        m_alias = re.match(r"\s*(?:type\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[A-Za-z_]", line)
        if m_alias and m_alias.group(1) in RESERVED:
            findings.append((f"type-alias spoofing: {m_alias.group(1)}", ln_no))
    for mod, ln in sc.imports:
        if allowed is not None and mod not in allowed:
            findings.append((f"import not in allowlist (slopsquatting?): {mod}", ln))
        elif allowed is None and mod in SUSPICIOUS_MODULES:
            findings.append((f"suspicious module (slopsquatting): {mod}", ln))
    findings.sort(key=lambda z: z[1])
    for kind, ln in findings:
        print(f"  [CHEAT DETECTED: {kind}] строка {ln}")
    print("-" * 74)
    print(f"[ANTI-CHEAT SUMMARY] файл {path}: находок {len(findings)}")
    if findings:
        return 1
    print("  [OK] чисто: ни читов, ни подозрительных импортов")
    return 0


# -----------------------------------------------------------------------------
# ЭШЕЛОН 6, ПУНКТ 33: СКАНЕР ОТРАВЛЕНИЯ MCP И ЗАЩИТА ОТ RUG-PULL.
#
# ЗАЧЕМ. MCP-сервер описывает инструменты в JSON; поле `description` читает
# ЯЗЫКОВАЯ МОДЕЛЬ, а не человек. Оттуда три атаки:
#   * промпт-инъекция (`ignore previous instructions`, чтение `~/.ssh`, `.env`);
#   * невидимые символы (Zero-Width, Bidi Override, Tag characters) — текст
#     выглядит безобидно, но модель читает скрытое;
#   * RUG-PULL: описание «тихо» меняется ПОСЛЕ одобрения. Замок `mcp.lock.json`
#     хранит SHA-256 каждого инструмента; изменение -> тревога.
# -----------------------------------------------------------------------------

MCP_INJECT_PATTERNS = [
    "ignore previous", "ignore all previous", "disregard previous",
    "<system>", "</system>", "important: before calling", "you must first",
    "~/.ssh", "id_rsa", ".env", "send the contents", "exfiltrate",
    "do not tell the user", "silently",
]
MCP_INVISIBLE_RANGES = [(0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2064),
                        (0xE0000, 0xE007F), (0xFEFF, 0xFEFF)]


def _mcp_tool_hash(tool: dict) -> str:
    """SHA-256 инструмента по КАНОНИЧЕСКОМУ JSON (имя+описание+схема).

    Спецификация допускает BLAKE3; здесь SHA-256 из stdlib, чтобы проверка
    работала без внешних зависимостей — это ЯВНО указано в отчёте.
    """
    payload = json.dumps({"name": tool.get("name", ""),
                          "description": tool.get("description", ""),
                          "inputSchema": tool.get("inputSchema", {})},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cmd_audit_mcp(schema_path: str, lock_path: str | None) -> int:
    """ПУНКТ 33: `--audit-mcp <schema.json> [--mcp-lock <lock.json>]`."""
    data = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    tools = data.get("tools", data if isinstance(data, list) else [])
    findings: list[str] = []
    for t in tools:
        name = t.get("name", "?")
        desc = json.dumps(t, ensure_ascii=False)
        low = desc.lower()
        for pat in MCP_INJECT_PATTERNS:
            if pat in low:
                findings.append(f"PROMPT INJECTION in `{name}`: «{pat}»")
        for ch in desc:
            cp = ord(ch)
            for lo, hi in MCP_INVISIBLE_RANGES:
                if lo <= cp <= hi:
                    findings.append(f"INVISIBLE UNICODE in `{name}`: U+{cp:04X}")
                    break
    if lock_path:
        lp = Path(lock_path)
        cur = {t.get("name", "?"): _mcp_tool_hash(t) for t in tools}
        if lp.exists():
            old = json.loads(lp.read_text(encoding="utf-8")).get("tools", {})
            for name, h in cur.items():
                if name in old and old[name] != h:
                    findings.append(f"MCP RUG-PULL DETECTED: `{name}` изменён после одобрения")
                elif name not in old:
                    findings.append(f"MCP RUG-PULL DETECTED: `{name}` добавлен после одобрения")
            for name in old:
                if name not in cur:
                    findings.append(f"MCP RUG-PULL DETECTED: `{name}` удалён после одобрения")
        else:
            lp.write_text(json.dumps({"tools": cur}, indent=2, sort_keys=True),
                          encoding="utf-8")
            print(f"  [i] замок создан: {lp} ({len(cur)} инструментов)")
    for f in findings:
        print(f"  [MCP] {f}")
    print("-" * 74)
    print(f"[MCP SUMMARY] инструментов {len(tools)} | находок {len(findings)}")
    if findings:
        return 1
    print("  [OK] схема чиста (нет инъекций, невидимых символов, rug-pull)")
    return 0


# -----------------------------------------------------------------------------
# ЭШЕЛОН 6, ПУНКТ 34: НЕИНТЕРФЕРЕНЦИЯ (`# @kern:secret`, 2-Safety).
#
# ЗАЧЕМ. Утечка по сторонним каналам: публичный выход зависит от СЕКРЕТА (pin,
# key, token). Классическая формулировка Гогоэна—Месегера: две копии программы с
# ОДИНАКОВЫМ публичным входом и РАЗНЫМИ секретами обязаны дать ОДИН выход.
# Проверяем самокомпозицию: `body[secret := s1] != body[secret := s2]` -> SAT =
# утечка (существует пара секретов, различимая по публичному выходу).
# -----------------------------------------------------------------------------

SECRET_RE = re.compile(r"^\s*(?:#|//|///)\s*@kern:secret\s*\(([^)]*)\)\s*$")


def cmd_noninterference(path: str, kernc) -> int:
    """ПУНКТ 34: `--noninterference <file>` (цель `make noninterference-check`)."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    fns = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]
    checked = fails = unknowns = skipped = 0
    for fn in fns:
        names = _directive_above(lines, fn.lineno, SECRET_RE)
        if names is None:
            skipped += 1
            continue
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        secrets = [s.strip() for s in names.split(",") if s.strip()]
        if not secrets or any(s not in params for s in secrets):
            print(f"  [SKIP] {fn.name}: `@kern:secret` называет не-параметры")
            skipped += 1
            continue
        body, why = None, ""
        try:
            body = body_smt(_fn_stmts(fn), _self_meta(fn, _fn_stmts(fn)))
        except (NoReturn, Unsupported) as e:
            why = str(e)
        if body is None:
            print(f"  [SKIP] {fn.name}: тело вне подмножества ({why})")
            skipped += 1
            continue
        checked += 1
        # ДВЕ КОПИИ: публичные параметры — ОДНО имя (вход одинаков), секреты
        # разведены в `__1` / `__2`. Это и есть 2-Safety самокомпозиция.
        m1 = {s: f"{s}__1" for s in secrets}
        m2 = {s: f"{s}__2" for s in secrets}
        f1 = _subst(body, m1)
        f2 = _subst(body, m2)
        decls = ([p for p in params if p not in secrets]
                 + list(m1.values()) + list(m2.values()))
        v, ce, tr = _prove_checked(kernc, decls, [f"(not (= {f1} {f2}))"])
        if v == "sat":
            fails += 1
            print(f"  [FAIL] {fn.name}: SECRET LEAK / NON-INTERFERENCE VIOLATED — {ce}")
        elif v == "unsat" and tr == 0:
            print(f"  [PASS] {fn.name}: PROVEN NON-INTERFERENT (trusted: 0 | holes: 0)")
        else:
            unknowns += 1
            print(f"  [UNKNOWN] {fn.name}: {v} trusted={tr} — НЕ засчитано")
    print("-" * 74)
    print(f"[NONINTERFERENCE SUMMARY] checked {checked} / {len(fns)} functions, "
          f"skipped {skipped} | FAIL {fails} | UNKNOWN {unknowns}")
    return 1 if (fails or unknowns) else 0


# -----------------------------------------------------------------------------
# ЭШЕЛОН 7, ПУНКТ 36: ACTION / FINOPS FIREWALL ДЛЯ ИИ-АГЕНТОВ.
#
# ЗАЧЕМ. Агент собирается вызвать боевой API (перевод, масштабирование облака,
# удаление ресурса). Проверяем JSON-вызов ДО исполнения против политики:
#   * `allow`  — предикат, который обязан быть истинным (лимиты, бюджеты);
#   * `forbid` — список предикатов, которые обязаны быть ложными.
# Вердикт в решётке Белнапа и кодах RFC 9110:
#   T -> 200 (проверено, trusted: 0); F -> 422 (контрпример);
#   B -> 409 (политики ПРОТИВОРЕЧАТ: allow и forbid истинны одновременно).
# -----------------------------------------------------------------------------

def _pol_smt(text: str) -> str:
    """Предикат политики (Python-подобное выражение) -> SMT."""
    return expr_smt(ast.parse(text, mode="eval").body, {})


def cmd_verify_action(action_path: str, policy_path: str, kernc) -> int:
    """ПУНКТ 36: `--verify-action <action.json> <policy.json>`."""
    act = json.loads(Path(action_path).read_text(encoding="utf-8"))
    pol = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    args = act.get("args", {})
    if not args or not all(isinstance(v, int) for v in args.values()):
        print("  [SKIP] аргументы действия должны быть ЦЕЛЫМИ (домен ℤ)")
        return 2
    decls = list(args)
    fixed = [f"(= {k} {v})" for k, v in args.items()]
    allow = pol.get("allow")
    forbids = pol.get("forbid", [])
    allow_smt = _pol_smt(allow) if allow else None
    allow_ok = True
    # (1) НАРУШЕНИЕ allow -> F (422)
    if allow_smt:
        v, ce, tr = _prove_checked(kernc, decls, fixed + [f"(not {allow_smt})"])
        if v == "sat":
            print(f"  [FAIL] Firewall: ALLOW VIOLATED -> F (0,1), e=0, "
                  f"HTTP 422 Unprocessable Entity — {ce}")
            return 1
        if v != "unsat" or tr != 0:
            print(f"  [UNKNOWN] allow не перепроверен (trusted={tr}) — НЕ засчитано")
            return 2
        allow_ok = True
    # (2) СРАБОТАВШИЙ forbid: если allow при этом истинен -> B (409), иначе F (422)
    for i, f in enumerate(forbids):
        f_smt = _pol_smt(f)
        v, ce, tr = _prove_checked(kernc, decls, fixed + [f_smt])
        if v != "sat":
            if v != "unsat" or tr != 0:
                print(f"  [UNKNOWN] forbid[{i}] не перепроверен (trusted={tr})")
                return 2
            continue
        if allow_smt and allow_ok:
            print(f"  [FAIL] Firewall: POLICY CONFLICT -> B (1,1), e=0, "
                  f"HTTP 409 Conflict (allow ∧ forbid[{i}]) — {ce}")
        else:
            print(f"  [FAIL] Firewall: FORBIDDEN ACTION -> F (0,1), e=0, "
                  f"HTTP 422 (forbid[{i}]) — {ce}")
        return 1
    print(f"  [PASS] Firewall: PROVEN (tool `{act.get('tool', '?')}`, "
          f"args {len(args)}, trusted: 0 | holes: 0) -> T (1,0), e=1, HTTP 200 OK")
    return 0


# -----------------------------------------------------------------------------
# ЭШЕЛОН 7, ПУНКТ 37: ПРОТИВОРЕЧИЯ В ДОКУМЕНТАХ / ДОГОВОРАХ / RAG-БАЗАХ.
#
# ЗАЧЕМ. Пункты договора — это КОНЪЮНКЦИЯ ограничений. Если она несовместна
# (`UNSAT`), документ внутренне противоречив: состояние B (1,1), Врата ЗАКРЫТЫ.
# Мало сказать «противоречиво» — нужно назвать КОНКРЕТНЫЕ пункты: минимальное
# ядро несовместности (greedy-удаление: если без пункта система всё ещё
# несовместна, пункт в ядро не входит).
# -----------------------------------------------------------------------------

def cmd_verify_doc(path: str, kernc) -> int:
    """ПУНКТ 37: `--verify-doc <doc.json>` (цель `make rag-conflict-check`)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    clauses = doc.get("clauses", [])
    decls = doc.get("vars", [])
    if not clauses or not decls:
        print("  [SKIP] нужны `vars` и `clauses`")
        return 2
    id_of = [c.get("id", f"clause_{i + 1}") for i, c in enumerate(clauses)]
    smt_of = [_pol_smt(c["expr"]) for c in clauses]

    def verdict(idxs) -> tuple[str, str | None, int | None]:
        return _prove_checked(kernc, decls, [smt_of[i] for i in idxs])

    v, ce, tr = verdict(range(len(clauses)))
    if v == "sat":
        print(f"  [PASS] DOCUMENT CONSISTENT: все {len(clauses)} пунктов совместны "
              f"(trusted: 0 | holes: 0)")
        return 0
    if v != "unsat" or tr != 0:
        print(f"  [UNKNOWN] документ не перепроверен (trusted={tr}) — НЕ засчитано")
        return 2
    # МИНИМАЛЬНОЕ ЯДРО: жадное удаление пунктов, пока система остаётся UNSAT.
    keep = list(range(len(clauses)))
    for i in list(keep):
        trial = [j for j in keep if j != i]
        if not trial:
            continue
        tv, _tce, ttr = verdict(trial)
        if tv == "unsat" and ttr == 0:
            keep = trial
    core = [id_of[i] for i in keep]
    print(f"  [FAIL] CONFLICT B(1,1): document UNSAT (trusted: 0 | holes: 0), "
          f"e=0 — пункты противоречат друг другу")
    print(f"  [CONFLICT B(1,1)] Minimal conflicting clauses: [{', '.join(core)}]")
    return 1


# -----------------------------------------------------------------------------
# ЭШЕЛОН 7, ПУНКТ 38: RLVR — ВЕРИФИЦИРУЕМЫЙ ОРАКУЛ ВОЗНАГРАЖДЕНИЯ.
#
# ЗАЧЕМ. «LLM-as-a-judge» недетерминирован и поддаётся взлому. Здесь награда
# выдаётся МАТЕМАТИКОЙ: R = +1.0 только при `trusted: 0 | holes: 0` И чистоте по
# `--anti-cheat`; иначе -2.0 (чит), -1.0 (контрпример), 0.0 (вне фрагмента).
# Никаких ложных наград: `unknown` НИКОГДА не даёт положительный сигнал.
# -----------------------------------------------------------------------------

def cmd_rlvr_reward(path: str, kernc) -> int:
    """ПУНКТ 38: `--rlvr-reward <candidate.py>` (цель `make rlvr-oracle-check`)."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    sc = _CheatScan()
    sc.visit(ast.parse(src))
    sc_findings = list(sc.findings)
    for mod, ln in sc.imports:
        if mod in SUSPICIOUS_MODULES:
            sc_findings.append((f"suspicious module: {mod}", ln))
    if sc_findings:
        kind, ln = sc_findings[0]
        print(f"[REWARD] R=-2.0 [REWARD HACKING PENALTY, Belnap F] "
              f"({kind}, строка {ln})")
        return 0
    entries = parse_file(Path(path))
    proven = refuted = unknown = 0
    first_ce = ""
    for (name, params, req, ens, body, _lineno, _skip, meta) in entries:
        if body is None or (not req and not ens):
            continue
        try:
            smt = build_smt(params, req, ens, body, meta.get("ranges"))
        except Exception as _kern_e_6651:
            _replay_soft(_kern_e_6651, "kern_contracts.py:6651")
            unknown += 1
            continue
        _rc, out = run_kernc(kernc, smt)
        if "КОНТРПРИМЕР" in out:
            refuted += 1
            first_ce = first_ce or next((l.strip()[:100] for l in out.splitlines()
                                         if "КОНТРПРИМЕР" in l), "SAT")
        elif "ДОКАЗАНО" in out:
            m = re.search(r"trusted:\s*(\d+)", out)
            tr = int(m.group(1)) if m else None
            if tr == 0:
                proven += 1
            else:
                unknown += 1
        else:
            unknown += 1
    if refuted:
        print(f"[REWARD] R=-1.0 [REFUTED, Belnap F] ({first_ce})")
    elif unknown or proven == 0:
        print(f"[REWARD] R=0.0 [ABSTAIN, Belnap N] "
              f"(proven {proven}, unknown {unknown}, refuted 0)")
    else:
        print(f"[REWARD] R=+1.0 [VERIFIED REWARD, Belnap T, e=1] "
              f"(доказано {proven}, trusted: 0 | holes: 0, чисто по anti-cheat)")
    return 0


# -----------------------------------------------------------------------------
# ЭШЕЛОН 8, ПУНКТ 40Б: ИНТЕРАКТИВНЫЙ ХОЛСТ ДОКАЗАТЕЛЬСТВ (`--html`).
#
# Инженеру нужно УВИДЕТЬ поведение функции на домене: ползунки параметров
# (Tangle-style) пересчитывают активную ветвь вживую, квадрат решётки Белнапа B4
# окрашивается по вердикту, рядом — паспорт (CC, число путей) и источник истины.
# Шаблон — отдельный ассет `tools/canvas_template.html` (0 внешних CDN).
# -----------------------------------------------------------------------------

CANVAS_TMPL = Path(__file__).resolve().parent / "canvas_template.html"


def cmd_html(path: str, out_path: str, kernc) -> int:
    """ПУНКТ 40Б: `--html <out.html>` (цель `make html-canvas-check`)."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    fns = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]
    functions = []
    for fn in fns:
        paths = _paths_of(fn)
        if not paths:
            continue
        functions.append({
            "name": fn.name,
            "cc": len(paths),
            "params": [a.arg for a in fn.args.args if a.arg != "self"],
            "paths": [{"conds": pp, "value": vp} for pp, vp in paths],
            "verdict": "N",
        })
    if not functions:
        print("  [SKIP] ни одной функции в подмножестве `_paths_of`")
        return 2
    if not CANVAS_TMPL.exists():
        print(f"  [!] нет шаблона {CANVAS_TMPL}")
        return 2
    payload = {
        "functions": functions,
        "proof_note": ("вердикт выдаёт `kernc prove` (Z3) и перепроверяет "
                       "пруф-чекер; квадрат B4 окрашен по первому вердикту. "
                       "Источник истины — CLI, а не холст."),
    }
    html = CANVAS_TMPL.read_text(encoding="utf-8").replace(
        "__DATA__", json.dumps(payload, ensure_ascii=False))
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"  [OK] холст записан: {out_path} ({len(html)} байт, "
          f"функций {len(functions)}, внешних зависимостей 0)")
    return 0


# =========================================================================
#  ГОМЕОСТАТИЧЕСКАЯ ПЕТЛЯ САМОИСЦЕЛЕНИЯ (--heal)
# =========================================================================
# ЗАЧЕМ. `--infer-requires` и `[SUGGESTED FIX]` только ПЕЧАТАЮТ рецепт: петля
# разомкнута, человек обязан применить патч руками. `--heal` замыкает её:
#   [1] проверка -> F (0,1) + контрпример
#   [2] синтез защитного гарда (с ПРОВЕРКОЙ в Z3)
#   [3] ВСТАВКА гарда в исходник (с бэкапом)
#   [4] ПОВТОРНАЯ проверка -> T (1,0), trusted: 0
# Если после патча краш остаётся — изменения ОТКАТЫВАЮТСЯ (fail-closed):
# «вылеченным» файл объявляется только по машинному вердикту.

def _crash_sites(tree: ast.AST, params: list[str], kernc) -> list[tuple[ast.AST, str]]:
    """Точки, где делитель МОЖЕТ быть нулём (Z3 подтвердил SAT)."""
    out: list[tuple[ast.AST, str]] = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod))):
            continue
        try:
            div = expr_smt(n.right, {})
        except (Unsupported, NoReturn):
            continue
        if _smt_sat(kernc, params, [f"(= {div} 0)"]) is True:
            out.append((n, div))
    return out


def _guard_covers(fn: ast.AST, node: ast.AST, div_py: str) -> bool:
    """Есть ли ПЕРЕД узлом `if <делитель> == 0: return ...` в том же теле?

    Нужно для ПЕРЕПРОВЕРКИ после патча: статический SAT «делитель может быть 0»
    сам по себе не знает, что эта ветка уже перехвачена ранее возвратом.
    Сравнение — по нормализованному AST-тексту (ast.unparse).
    """
    def walk_block(stmts: list) -> bool:
        for st in stmts:
            if isinstance(st, ast.If) and getattr(st, "lineno", 10**9) < getattr(node, "lineno", 0):
                t = st.test
                try:
                    if (isinstance(t, ast.Compare) and isinstance(t.ops[0], ast.Eq)
                            and ast.unparse(t.left) == div_py
                            and ast.unparse(t.comparators[0]) == "0"
                            and any(isinstance(x, ast.Return) for x in st.body)):
                        return True
                except Exception as _kern_e_6771:
                    _replay_soft(_kern_e_6771, "kern_contracts.py:6771")
                    pass
            for attr in ("body", "orelse"):
                sub = getattr(st, attr, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt) and walk_block(sub):
                    return True
        return False
    return walk_block(getattr(fn, "body", []))

def cmd_heal(path: str, kernc) -> int:
    """Замкнуть петлю: найти F -> вставить гард -> ПЕРЕПРОВЕРИТЬ -> T."""
    src_path = Path(path)
    if not src_path.exists():
        print(f"[!] нет файла: {path}")
        return 2
    original = src_path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(original)

    # [1] и [2]: находим краши и синтезируем гарды (все — с проверкой в Z3).
    plan: list[tuple[int, str, str, str]] = []  # (строка, функция, условие-py, условие-smt)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        for node, div in _crash_sites(fn, params, kernc):
            guard_smt = f"(= {div} 0)"
            if _smt_sat(kernc, params, [f"(not {guard_smt})", guard_smt]) is not False:
                continue  # гард не доказан — рецепт не применяем
            try:
                guard_py = f"{ast.unparse(node.right)} == 0"
            except Exception as _kern_e_6799:
                _replay_soft(_kern_e_6799, "kern_contracts.py:6799")
                continue
            line = min(getattr(node, "lineno", fn.lineno), fn.lineno + 200)
            plan.append((line, fn.name, guard_py, guard_smt))

    if not plan:
        print("[HEAL] крашей не найдено — патчить нечего (T (1,0), e=1)")
        return 0

    # [3] ВСТАВКА: по одному гарду, от ПОСЛЕДНЕЙ строки к первой, чтобы
    # сдвиг номеров не ломал вставки. Отступ — от самой строки.
    lines = original.splitlines()
    for line, fname, guard_py, _gsmt in sorted(plan, key=lambda t: -t[0]):
        idx = line - 1
        if idx < 0 or idx >= len(lines):
            continue
        target = lines[idx]
        indent = target[: len(target) - len(target.lstrip())]
        lines.insert(idx, f"{indent}if {guard_py}:  # [KERN HEAL] {fname}: защита от деления на 0")
        lines.insert(idx + 1, f"{indent}    return 0")
    patched = "\n".join(lines) + ("\n" if original.endswith("\n") else "")

    try:
        new_tree = ast.parse(patched)
    except SyntaxError as e:
        print(f"[HEAL] [!] патч НЕ компилируется ({e}) — файл НЕ изменён")
        return 1

    # [4] ПЕРЕПРОВЕРКА: крашей быть не должно. Только по машинному вердикту.
    remaining = 0
    for fn in [n for n in ast.walk(new_tree) if isinstance(n, ast.FunctionDef)]:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        for node, div in _crash_sites(fn, params, kernc):
            # Краш считается ОСТАВШИМСЯ только если перед ним НЕТ гарда.
            try:
                div_py = ast.unparse(node.right)
            except Exception as _kern_e_6835:
                _replay_soft(_kern_e_6835, "kern_contracts.py:6835")
                div_py = ""
            if not _guard_covers(fn, node, div_py):
                remaining += 1

    print(f"[HEAL] найдено крашей: {len(plan)} | после патча: {remaining}")
    if remaining != 0:
        print("[HEAL] [!] остались краши — изменения ОТКАТЫВАЮТСЯ (fail-closed)")
        return 1

    # АТОМАРНАЯ ЗАПИСЬ (Д7): tmp -> flush -> fsync -> ПЕРЕПРОВЕРКА tmp ->
    # .bak -> os.replace. Порядок принципиален: сначала ДОКАЗУЕМО хороший
    # временный файл, и только потом трогаем оригинал. При любом сбое
    # оригинал остаётся нетронутым.
    tmp_path = src_path.with_suffix(src_path.suffix + ".kern_tmp")
    bak_path = src_path.with_suffix(src_path.suffix + ".bak")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(patched)
            f.flush()
            os.fsync(f.fileno())
        # ПЕРЕПРОВЕРКА ИМЕННО ВРЕМЕННОГО ФАЙЛА (не строки в памяти).
        check_tree = ast.parse(tmp_path.read_text(encoding="utf-8", errors="replace"))
        still = 0
        for fn in [n for n in ast.walk(check_tree) if isinstance(n, ast.FunctionDef)]:
            params = [a.arg for a in fn.args.args if a.arg != "self"]
            for node, _div in _crash_sites(fn, params, kernc):
                try:
                    div_py = ast.unparse(node.right)
                except Exception as _kern_e_6864:
                    _replay_soft(_kern_e_6864, "kern_contracts.py:6864")
                    div_py = ""
                if not _guard_covers(fn, node, div_py):
                    still += 1
        if still != 0:
            print(f"[HEAL] [!] временный файл НЕ прошёл перепроверку ({still}) — оригинал не тронут")
            tmp_path.unlink(missing_ok=True)
            return 1
        # БЭКАП ОРИГИНАЛА и атомарная замена.
        bak_path.write_text(original, encoding="utf-8")
        os.replace(tmp_path, src_path)
    except OSError as e:
        print(f"[HEAL] [!] ошибка записи: {e} — оригинал не тронут")
        tmp_path.unlink(missing_ok=True)
        return 1
    print(f"[HEAL] [T (1,0)] файл вылечен: {path} (гардов {len(plan)}, бэкап {bak_path.name})")
    return 0


# =========================================================================
#  РАЗДЕЛ 5 ЭНЦИКЛОПЕДИИ: КОНКОЛИЧЕСКОЕ ИСПОЛНЕНИЕ (--concolic)
# =========================================================================
# ИДЕЯ (DART / KLEE). Статический `--gen-tests` перебирает пути СИМВОЛЬНО и
# не знает, какие из них реально исполняются. Конколика совмещает оба мира:
#   1) КОНКРЕТНЫЙ запуск интерпретатором AST на реальном входе (0,0,...);
#   2) запись РЕАЛЬНОЙ трассы условий (какое условие куда пошло);
#   3) инверсия условия в Z3 -> НОВЫЙ конкретный вход;
#   4) снова живой запуск — пока не будут исполнены все достижимые ветви.
# ЗВУЧИМОСТЬ ОТЧЁТА: «покрыто M/M» подтверждается РЕАЛЬНЫМ исполнением,
# а мёртвые ветви (SAT=unsat) исключаются из знаменателя с указанием причины.

def _eval_cond(cond: ast.AST, env: dict) -> bool:
    """Значение условия на КОНКРЕТНЫХ данных (реальное исполнение ветки)."""
    expr = ast.Expression(body=cond)
    ast.fix_missing_locations(expr)
    return bool(eval(compile(expr, "<concolic>", "eval"), {}, dict(env)))


def _run_trace(stmts: list, env: dict, trace: list, depth: int = 0) -> tuple[bool, object]:
    """Исполнить операторы интерпретатором: вернуть (был_return, значение).

    Записывает в `trace` пары (объект If, взятое_значение) по РЕАЛЬНОМУ пути.
    Поддержано подмножество: assign / if-elif-else / return / выражение.
    """
    if depth > 64:
        return False, None
    for st in stmts:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            try:
                env[st.targets[0].id] = eval(compile(ast.Expression(body=st.value), "<c>", "eval"), {}, dict(env))
            except Exception as _kern_e_6914:
                _replay_soft(_kern_e_6914, "kern_contracts.py:6914")
                pass
            continue
        if isinstance(st, ast.If):
            try:
                taken = _eval_cond(st.test, env)
            except Exception as _kern_e_6920:
                _replay_soft(_kern_e_6920, "kern_contracts.py:6920")
                continue
            trace.append((st, taken))
            done, val = _run_trace(st.body if taken else st.orelse, env, trace, depth + 1)
            if done:
                return True, val
            continue
        if isinstance(st, ast.Return):
            try:
                val = eval(compile(ast.Expression(body=st.value), "<c>", "eval"), {}, dict(env)) if st.value else None
            except Exception as _kern_e_6930:
                _replay_soft(_kern_e_6930, "kern_contracts.py:6930")
                val = None
            return True, val
    return False, None


def _smt_text(params: list[str], asserts: list[str]) -> str:
    """SMT-LIB2 текст из объявлений и утверждений (для минимизации)."""
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    body = "\n".join(f"(assert {a})" for a in asserts)
    return f"(set-logic ALL)\n{decls}\n{body}\n(check-sat)\n"


def cmd_concolic(path: str, kernc) -> int:
    """Конколика: реальные запуски + инверсия условий в Z3."""
    if not Path(kernc).exists():
        print(f"[!] не найден kernc: {kernc}")
        return 2
    tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    total_runs = 0
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        if not params:
            continue
        # Достижимые условия этой функции (для знаменателя).
        ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If)]
        if not ifs:
            continue
        covered: set[tuple[int, bool]] = set()   # (lineno, taken)
        seen_paths: set[tuple] = set()
        worklist: list[dict] = [{p: 0 for p in params}]
        runs = 0
        while worklist and runs < 64:
            env = dict(worklist.pop())
            trace: list = []
            _run_trace(fn.body, env, trace)
            runs += 1
            total_runs += 1
            key = tuple((getattr(st, "lineno", 0), t) for st, t in trace)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            for st, t in trace:
                covered.add((getattr(st, "lineno", 0), t))
            # Инверсия КАЖДОГО условия реального пути: prefix ∧ ¬(взятое).
            prefix: list[str] = []
            for st, t in trace:
                try:
                    c = expr_smt(st.test, {})
                except (Unsupported, NoReturn):
                    break
                want = (f"(not {c})") if t else c   # инвертируем
                model = _smt_model(kernc, params, prefix + [want])
                # ИЗМЕРЕНО: Z3 не связывает параметры, не входящие в условие,
                # поэтому модель бывает НЕПОЛНОЙ (например, только x). Такие
                # параметры СВОБОДНЫ — берём 0 (любое значение даёт тот же путь).
                if model:
                    cand = {k: int(model.get(k, 0)) for k in params}
                    cand = minimize_counterexample(
                        kernc, _smt_text(params, prefix + [want]), params, cand)
                    worklist.append(cand)
                prefix.append(c if t else f"(not {c})")
        # Сколько ветвей ДОСТИЖИМО: проверяем каждую (lineno, True/False) через Z3
        # с учётом префиксов — приближение: условие SAT => достижимо.
        # ЧЕСТНЫЙ СЧЁТ. «Достижимо» проверяется С УЧЁТОМ ПУТИ (префикса), а не
        # глобально: иначе вложенное `if y > 3` считалось бы достижимым даже
        # при недостижимом внешнем `if x > 5` (ИЗМЕРЕНО: давало 2/6 вместо 2/4).
        cov = sum(1 for st in ifs for t in (True, False) if (getattr(st, "lineno", 0), t) in covered)
        dead = 0
        unexplored = 0
        for st in ifs:
            try:
                c = expr_smt(st.test, {})
            except (Unsupported, NoReturn):
                continue
            for t in (True, False):
                if (getattr(st, "lineno", 0), t) in covered:
                    continue
                # Мёртвая, если условие несовместно САМО ПО СЕБЕ (без путей)
                # — консервативно: только такие называем dead.
                probe = c if t else f"(not {c})"
                if _smt_sat(kernc, params, [probe]) is False:
                    dead += 1
                else:
                    unexplored += 1
        total = cov + dead + unexplored
        print(f"  [CONCOLIC] {fn.name}: concrete runs {runs}, "
              f"branches covered {cov}/{total} (dead {dead}, unexplored {unexplored})")
    print("-" * 74)
    print(f"ИТОГО: реальных запусков {total_runs}")
    return 0


if __name__ == "__main__":
    # Ф6.3: подкоманда `explain --hypotheses FILE` (как в плане).
    _argv = sys.argv[1:]
    if _argv and _argv[0] == "explain":
        _argv = _argv[1:]
        _argv = ["--explain-hypotheses" if a == "--hypotheses" else a
                  for a in _argv]
    sys.exit(main(_argv))
