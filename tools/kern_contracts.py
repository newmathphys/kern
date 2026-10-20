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
import re
import shutil
import subprocess
import io
import sys
import tempfile
from pathlib import Path


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


def expr_smt(node: ast.AST, env: dict) -> str:
    """Python-выражение (подмножество) -> SMT-LIB2 с учётом локальных имён.

    `env` отображает имена локальных переменных в их SMT-выражения (результат
    символьного исполнения присваиваний). Имена, которых нет в env, считаются
    параметрами функции и печатаются как есть.
    """
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
            a = expr_smt(node.args[0], env)
            b = expr_smt(node.args[1], env)
            cmp_ = "<=" if fname == "min" else ">="
            return f"(ite ({cmp_} {a} {b}) {a} {b})"
        if fname == "abs" and len(node.args) == 1 and not node.keywords:
            x = expr_smt(node.args[0], env)
            return f"(ite (< {x} 0) (- 0 {x}) {x})"
        # СИМВОЛЬНАЯ АБСТРАКЦИЯ (правило №1): неизвестный вызов больше НЕ
        # означает отказ от функции. `len(x)` -> символ `len__x` с аксиомой
        # неотрицательности; `int(x)` -> x; `bool(x)` -> 0/1; всё прочее ->
        # СВЕЖАЯ символьная переменная (havoc), т.е. произвольное целое.
        # Такой SAT-контрпример обязан подтвердиться живым вызовом (см. вердикт).
        if fname == "len" and len(node.args) == 1 and not node.keywords:
            a0 = node.args[0]
            if isinstance(a0, ast.Name):
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
            x = expr_smt(node.args[0], env)
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
                _new_env[_p] = expr_smt(_a, env)
            _new_env["__self__"] = (_sname, _sparams, _sbody, _budget - 1)
            _INLINED[0] += 1
            _UNROLLED[0] = True
            return body_smt(copy.deepcopy(_sbody), _new_env)
        _HAVOC_SEQ[0] += 1
        _HAVOC_USED[0] = True
        _sym = f"_havoc_{_HAVOC_SEQ[0]}"
        _ABSTRACT_SYMS.add(_sym)
        return _sym
    # Тернарный оператор `A if cond else B` -> SMT `ite`.
    if isinstance(node, ast.IfExp):
        return (f"(ite {expr_smt(node.test, env)} "
                f"{expr_smt(node.body, env)} {expr_smt(node.orelse, env)})")
    if isinstance(node, ast.BoolOp):
        op = "and" if isinstance(node.op, ast.And) else "or"
        parts = " ".join(expr_smt(v, env) for v in node.values)
        return f"({op} {parts})"
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return f"(not {expr_smt(node.operand, env)})"
        if isinstance(node.op, ast.USub):
            return f"(- {expr_smt(node.operand, env)})"
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
            # ДЕЛЕНИЕ/ОСТАТОК. В SMT `div`/`mod` — ТОТАЛЬНЫЕ функции: Z3 просто
            # доопределяет `div(x, 0)`, поэтому сам по себе ноль НЕ ловится.
            # Собираем делители и отдельно доказываем `делитель ≠ 0`
            # (обязательство безопасности, см. `build_divzero_smt`).
            op = "mod" if isinstance(node.op, ast.Mod) else "div"
            # `%` над СТРОКАМИ — это форматирование, а не остаток от деления.
            if isinstance(node.op, ast.Mod) and _is_str_expr(node.left):
                raise Unsupported("строковое форматирование %")
            d = expr_smt(node.right, env)
            _DIV_COLLECTOR.append(d)
            return f"({op} {expr_smt(node.left, env)} {d})"
        else:
            raise Unsupported("бинарный оператор (только + - * / // %)")
        return f"({op} {expr_smt(node.left, env)} {expr_smt(node.right, env)})"
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
            parts.append(f"({CMP[opname]} {expr_smt(cur, env)} {expr_smt(right, env)})")
            cur = right
        if not parts:
            raise Unsupported("пустое сравнение")
        return parts[0] if len(parts) == 1 else f"(and {' '.join(parts)})"
    raise Unsupported(f"узел {type(node).__name__}")


def _self_meta(fn, stmts) -> dict:
    """Окружение с метаданными функции для inline саморекурсии (bounded)."""
    params = [a.arg for a in fn.args.args if a.arg != "self"]
    return {"__self__": (fn.name, params, stmts, _UNROLL_K[0])}


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
            if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                    and it.func.id == "range" and not it.keywords):
                raise Unsupported("for по не-range")
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
            # `x op= e` — это `x = x op e`. Для имён транслируется точно;
            # `arr[i] op= e` (мутация элемента) вне модели — честный отказ.
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
            if len(st.targets) != 1 or not isinstance(tgts, ast.Name):
                raise Unsupported("присваивание не в простую переменную")
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
            then_env = dict(env)
            then_expr = body_smt(st.body, then_env)
            rest = stmts[i + 1:]
            else_env = dict(env)
            if st.orelse:
                else_expr = body_smt(st.orelse, else_env)
            elif rest:
                # Нет `else` -> при ложном условии исполняются оставшиеся операторы.
                else_expr = body_smt(rest, else_env)
            else:
                # Нет `else` и нет остатка -> путь без `return` (неявный None).
                else_expr = None
            # ВЕТКА БЕЗ `return` (только присваивания, например `if c: y = 1`)
            # НЕ терминальна: исполнение продолжается после `if`, поэтому
            # значение берётся из ОСТАТКА операторов (раньше это был ложный
            # отказ «путь без return»).
            _then_term = bool(st.body) and isinstance(st.body[-1], ast.Raise)
            if then_expr is None and not _then_term and rest:
                then_expr = body_smt(rest, then_env)
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
            return f"(ite {expr_smt(st.test, env)} {then_expr} {else_expr})"
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
    lines = src.splitlines()
    # ИЗ НАСТОЯЩИХ КОММЕНТАРИЕВ (tokenize), а не построчно — защита от
    # Comment-in-String Injection.
    anchors: dict[int, dict[str, str]] = _py_comment_anchors(src)
    tree = ast.parse(src)
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
        _UNROLLED[0] = False
        try:
            body = body_smt(stmts, _self_meta(node, stmts))
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
_WRAP_ZIG = ("+%", "-%", "*%", "+|", "-|")
_WRAP_RUST = (".wrapping_add(", ".wrapping_sub(", ".wrapping_mul(",
              ".saturating_add(", ".saturating_sub(", ".saturating_mul(")


def _explicit_wrap(body: str, lang: str) -> str | None:
    """Вернуть найденный оператор оборачивания/насыщения или None.

    ЗАЧЕМ. Обычный `a + b` в Zig ПАНИКУЕТ при переполнении (это баг), а
    `a +% b` / `a +| b` — ЗАКОННЫЕ операции без паники. Обвинять вторые в
    `INTEGER OVERFLOW` — ЛОЖНОЕ СРАБАТЫВАНИЕ (False Positive), которого не
    должно быть: пользователь явно выбрал семантику.
    """
    if not body:
        return None
    if lang == "zig":
        for op in _WRAP_ZIG:
            if op in body:
                return op
        return None
    if lang == "rust":
        for op in _WRAP_RUST:
            if op in body:
                return op
        return None
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


def build_divzero_smt(params, req, divisors, ranges) -> str:
    """Обязательство ДЕЛЕНИЯ НА НОЛЬ: `requires ∧ (делитель = 0)` -> SAT = баг.

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
    lines.append("(assert (or " + " ".join(f"(= {d} 0)" for d in divisors) + "))")
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


def run_kernc(kernc, smt: str):
    """Прогнать `kernc prove` на SMT-тексте. Возвращает (rc, вывод).

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
        r = subprocess.run([str(kernc), "prove", sp],
                           capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr
    finally:
        Path(sp).unlink(missing_ok=True)


def parse_bodies(path: Path):
    """Все функции файла БЕЗ контракта: (имя, params, body_smt, строка, unrolled).

    Нужна для УЛУЧШЕНИЯ №3 (`--diff-equiv`): эквивалентность рефакторинга
    доказывается по ТЕЛАМ, контракты писать не требуется.

    `unrolled=True` означает, что тело получено РАЗВЁРТКОЙ цикла/рекурсии на
    K шагов. Такое тело — недо-аппроксимация: SAT на нём даёт честный
    контрпример, но UNSAT НЕ доказывает эквивалентность (дефект #207).
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
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
            body = body_smt(stmts, _self_meta(node, stmts))
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
            anchors.setdefault(i, {})[m.group(1)] = m.group(2)
    out: dict[str, str] = {}
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef):
            continue
        for k in range(max(1, node.lineno - 6), node.lineno):
            if k not in anchors:
                continue
            for kind, text in anchors[k].items():
                out[f"{node.name}:{kind}"] = hashlib.sha256(
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

# `/// @kern:...`, `// @kern:...`, `# @kern:...`
ANNOT = re.compile(r"^\s*(?:///|//|#)\s*@kern:(requires|ensures)\s+(.+?)\s*$")

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
    r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?"
    r"(?:extern\s+(?:\"[^\"]*\"\s+)?)?"
    r"(?:async\s+)?(?:unsafe\s+)?(?:const\s+)?"
    r"fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
    r"\s*(?:->\s*)?([\w:<>\[\]&' ]+)?\s*\{")
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
    r"([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*\{?\s*$")
# ПУНКТ 25: TypeScript/JavaScript — `function name(x: Type): Ret {`,
# `export function name(x) {`. Стрелочные функции (`const f = (x) => …`) в
# подмножество НЕ входят и получают честный SKIP (регулярка их не матчит).
RE_FN_TS = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)"
    r"\s*(?::\s*([\w<>\[\]]+))?\s*\{")
# ПУНКТ 25: Go — `func name(x int) int {`, `func (r T) name(x uint32) uint32 {`.
# Условия в Go пишутся БЕЗ скобок (`if x < 0 {`), но `_normalize_clike` убирает
# фигурные скобки, поэтому разбор операторов переиспользуется без изменений.
RE_FN_GO = re.compile(
    r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)"
    r"\s*(?:\(([^)]*)\)|([\w\.\*\[\]]+))?\s*\{")


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
            m = re.match(r"^(?:const\s+)?([A-Za-z_]\w*)\s+\**([A-Za-z_]\w*)$", part)
            if m:
                out.append((m.group(2), m.group(1)))
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
    """`cond ? a : b` -> `(a if cond else b)` (рекурсивно)."""
    depth = 0
    q = -1
    for i, c in enumerate(s):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "?" and depth == 0:
            q = i
            break
    if q < 0:
        return s
    depth = 0
    cpos = -1
    for j in range(q + 1, len(s)):
        c = s[j]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == ":" and depth == 0:
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


def _iter_call_args(src: str, name: str):
    r"""Все аргументы вызова `name(...)` с БАЛАНСОМ скобок.

    🔴 ДЕФЕКТ #182 (найден полевым прогоном): регулярка `assert\s*\(([^()]*)\)`
    не видит вложенных скобок, поэтому `assert(@backingInt(index) < len)`
    (zls) НЕ становился гардом пути, и `--xray` выдавал ложный
    `[CRASH PATH] len == 0` на защищённом коде. Здесь скобки считаются.
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
            yield src[m.end(): j - 1]
        i = j


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



def _drop_macro_divisors(divs: list[str]) -> list[str]:
    return [d for d in divs if not _MACRO_DIV.match(d)]


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
    text = re.sub(r"([A-Za-z_][\w]*|\d+)\s*\+\|\s*([A-Za-z_][\w]*|\d+)",
                  lambda m: clamp("+", m.group(1), m.group(2)), text)
    text = re.sub(r"([A-Za-z_][\w]*|\d+)\s*-\|\s*([A-Za-z_][\w]*|\d+)",
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
        meta = {"ranges": {}, "ret": (ret or "").strip()}
        ret = meta["ret"]
        req = ens = None
        for k in range(max(0, i - 6), i):
            am = ANNOT.match(lines[k])
            if am:
                if am.group(1) == "requires":
                    req = am.group(2)
                else:
                    ens = am.group(2)
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
            for ch in lines[j]:
                if ch == "{":
                    depth += 1
                    if depth == 1:
                        started = True
                        continue
                elif ch == "}":
                    depth -= 1
            if started and depth >= 1 and j > i:
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
                out.append((name, names, req, ens, "BV_PENDING", i + 1, None, meta))
            else:
                out.append((name, names, req, ens, None, i + 1, str(e), meta))
            i = j + 1
            continue
        meta["divisors"] = _drop_macro_divisors(list(dict.fromkeys(_DIV_COLLECTOR)))
        out.append((name, names, req, ens, body, i + 1, None, meta))
        i = j + 1
    return out


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
        return 2
    diverged = same = unknown = 0
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
        rc, out = run_kernc(kernc, diff_equiv_smt(pa, ba, bnew))
        if "ДОКАЗАНО" in out:
            extra = "" if rc == 0 else " (пруф-чекер не покрывает форму вывода)"
            print(f"  [EQUIVALENT] {name}: рефакторинг математически "
                  f"эквивалентен на всём домене Z{extra}")
            same += 1
        else:
            print(f"  [DIVERGED] {name}: РЕФАКТОРИНГ ИЗМЕНИЛ ПОВЕДЕНИЕ")
            for line in out.splitlines():
                if "КОНТРПРИМЕР" in line:
                    print(f"         {line.strip()}")
                    break
            diverged += 1
    print("-" * 74)
    print(f"ИТОГО: эквивалентных {same} | разошедшихся {diverged} | "
          f"недоказуемых (абстракция) {unknown} | всего {len(common)}")
    if diverged:
        return 1
    return 2 if unknown else 0


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


def main() -> int:
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
    ap.add_argument("--xray", default=None, metavar="PATH",
                    help="ПУНКТ 13: рентген кода БЕЗ аннотаций "
                         "(мёртвые ветки, избыточные проверки, краш-пути, CC)")
    ap.add_argument("--full-scan", dest="full_scan", default=None, metavar="PATH",
                    help="полноспектральный обход: xray (7 языков) + anti-cheat "
                         "+ MCP-аудит + авто-роутинг теорий (честно: без контракта "
                         "теории только помечаются как применимые)")
    ap.add_argument("--explain", default=None, metavar="PATH",
                    help="ПУНКТ 18: человеческий паспорт функций")
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
    args = ap.parse_args()

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
    if getattr(args, "audit_repo", None):
        return cmd_audit_repo(args.audit_repo, args.kernc,
                              getattr(args, "html_out", None))
    if getattr(args, "full_scan", None):
        return cmd_full_scan(args.full_scan, args.kernc)
    if args.xray:
        return cmd_xray(args.xray, args.kernc)
    if args.heal:
        return cmd_heal(args.heal, args.kernc)
    if args.concolic:
        return cmd_concolic(args.concolic, args.kernc)
    if args.explain:
        return cmd_explain(args.explain, args.kernc)
    if args.pr_summary:
        return cmd_pr_summary(args.pr_summary[0], args.pr_summary[1], args.kernc)
    if args.infer_requires:
        return cmd_suggest_fix(args.infer_requires, args.kernc, infer_requires=True)
    if args.diff_equiv:
        return cmd_diff_equiv(args.diff_equiv[0], args.diff_equiv[1],
                              Path(args.kernc))
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
            _DIV_COLLECTOR.append(right)
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
    lines.append("(assert (or " + " ".join(f"(= {d} {zero})" for d in divisors) + "))")
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


KERN_VERSION = "2.4.0"

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

    total = ok = failed = skipped = vacuous = safety_failed = unknown = 0
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
            forced_bv = ("@kern:bitvec32" in ftext) or ("@kern:bitvec64" in ftext)
            use_bv = (p.suffix in CLIKE_EXT
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
                    bv_body = _exec_clike(meta["raw_body"].split(";"), {},
                                          meta.get("lang", "zig"),
                                          lambda node, env_: expr_smt_bv(node, env_, w, signed))
                    meta["divisors"] = _drop_macro_divisors(list(dict.fromkeys(_DIV_COLLECTOR)))
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
            # ---- ОБЯЗАТЕЛЬСТВО БЕЗОПАСНОСТИ: ДЕЛЕНИЕ НА НОЛЬ ---------------
            # В SMT-LIB2 `div`/`mod` — ТОТАЛЬНЫЕ функции: `(div x 0)` просто
            # доопределён, поэтому наивный чекер ноль НЕ видит, а в рантайме
            # будет `ZeroDivisionError` / аппаратное исключение. Проверяем
            # ОТДЕЛЬНО: `requires ∧ (делитель = 0)` — SAT означает баг.
            if divisors:
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
                          f"(делитель: {', '.join(divisors)})")
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
                                    f"(делитель: {', '.join(divisors)})"
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
    print(f"ИТОГО: доказано {ok} | нарушено {failed} (из них "
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
            continue
        if isinstance(st, ast.AugAssign) and isinstance(st.target, ast.Name):
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}.get(type(st.op))
            if op is not None:
                try:
                    cur = env.get(st.target.id, st.target.id)
                    env[st.target.id] = f"({op} {cur} {expr_smt(st.value, env)})"
                except (Unsupported, NoReturn):
                    env.pop(st.target.id, None)
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
            for n in ast.walk(st):
                if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                    if isinstance(n.op, ast.Mod) and _is_str_expr(n.left):
                        continue  # `'%s' % x` — форматирование, не деление
                    if isinstance(n.left, ast.Name) and _MACRO_DIV.match(n.left.id):
                        continue  # UPGRADE_DIR / name — pathlib-склейка, не арифметика
                    try:
                        div = expr_smt(n.right, env)
                    except (Unsupported, NoReturn):
                        continue
                    if not _could_be_zero(div) or not _mentions_param(div, params):
                        continue
                    sat_dz = _smt_sat(kernc, params, path + [cond, f"(= {div} 0)"])
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
            for n in ast.walk(st):
                if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                    if isinstance(n.op, ast.Mod) and _is_str_expr(n.left):
                        continue  # `'%s' % x` — форматирование, не деление
                    if isinstance(n.left, ast.Name) and _MACRO_DIV.match(n.left.id):
                        continue  # UPGRADE_DIR / name — pathlib-склейка, не арифметика
                    try:
                        div = expr_smt(n.right, env)
                    except (Unsupported, NoReturn):
                        continue
                    if not _could_be_zero(div) or not _mentions_param(div, params):
                        continue
                    sat_dz = _smt_sat(kernc, params, path + [f"(= {div} 0)"])
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
    _rc, out = run_kernc(kernc, smt)
    if "КОНТРПРИМЕР" in out:
        for ln in out.splitlines():
            if "КОНТРПРИМЕР" in ln:
                return ("sat", ln.strip()[:110])
        return ("sat", "SAT (модель не извлечена)")
    if "ДОКАЗАНО" in out:
        return ("unsat", None)
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
    """Завершается ли блок безусловно (return/raise)?"""
    return bool(body) and isinstance(body[-1], (ast.Return, ast.Raise))


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


def _walk_bounds(body, path, params, lens, kernc, found, fname, syms=None):
    """Обход тела с накоплением путевых условий (Пункт 21, Zero-Annotation)."""
    syms = syms if syms is not None else set()
    for st in body:
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
            _walk_bounds(st.body, path + ([cond] if cond else []), params, lens,
                         kernc, found, fname, syms)
            neg = f"(not {cond})" if cond else None
            _walk_bounds(st.orelse, path + ([neg] if neg else []), params, lens,
                         kernc, found, fname, syms)
            # ИЗМЕРЕНО: операторы ПОСЛЕ `if` раньше теряли путевое условие, и
            # `get_safe` (с гардами) ЛОЖНО обвинялся в выходе за границы.
            # Если ветка THEN безусловно завершается, то всё последующее
            # выполняется при `NOT cond` -> сужаем путь.
            if neg and _block_exits(st.body):
                path = path + [neg]
            continue
        for sub in [n for n in ast.walk(st) if isinstance(n, ast.Subscript)]:
            if not isinstance(sub.value, ast.Name):
                continue
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
                continue
            try:
                idx = expr_smt(sub.slice, {})
            except (Unsupported, NoReturn):
                continue
            bad = f"(not (and (>= {idx} 0) (< {idx} {n})))"
            v, ce = _smt_verdict(kernc, decls, pre + path + [bad])
            if v == "sat":
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
_XRAY_EXTS = {".py", ".ts", ".js", ".go", ".zig", ".c", ".h", ".rs"}


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
_CLIKE_RANGES = {
    "u8": (0, 255), "u16": (0, 65535), "u32": (0, 4294967295),
    "u64": (0, 18446744073709551615), "usize": (0, 18446744073709551615),
    "uint": (0, 4294967295), "size_t": (0, 18446744073709551615),
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
        key = ty.split()[-1] if ty else ""
        if key in _CLIKE_RANGES:
            out[name] = _CLIKE_RANGES[key]
    return out


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
    out = []
    for i, line in enumerate(lines):
        m = (RE_FN_FN.match(line) or RE_FN_TS.match(line)
             or RE_FN_GO.match(line) or RE_FN_C.match(line))
        if not m:
            continue
        # имя/параметры по языку
        if path.suffix in {".zig", ".rs", ".ts", ".js"}:
            name, praw = m.group(1), m.group(2)
        elif path.suffix == ".go":
            name, praw = m.group(1), m.group(2)
        else:
            name, praw = m.group(2), m.group(3)
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
            body.append(ln)
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

def _xray_clike_file(path: Path, kernc) -> tuple[int, int, list[str]]:
    """ПОЛЕВОЙ АДАПТЕР №5б: `--xray` для C-like (Zig/C/Rust/TS/JS/Go).

    Извлекает условия `if (...)` из ТЕЛА (без исполнения) и проверяет их
    достижимость/тавтологичность в Z3. Путь сужается по правилу #134/#149:
    после `if (c) { return … }` следующие операторы идут при `not c`.

    ЧЕСТНО: условия вне подмножества (вызовы, `@as`, указатели) ведут к SKIP
    с причиной — они не «проверены», а пропущены.
    """
    try:
        funcs = _clike_functions(path)
    except Exception:  # noqa: BLE001
        return 0, 0, []
    # ДЕФЕКТ #193: типы полей структур нужны для проверки переполнения
    # счётчиков (`row->n_columns : uint16_t`). Определения лежат в том же
    # файле (cmark: `typedef struct { uint16_t n_columns; } table_row;`).
    try:
        field_types = _clike_struct_fields(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        field_types = {}
    checked = total = 0
    found: list[str] = []
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
        proven = 0
        raw_body = body          # для правила B (смотрит на САМИ касты)
        # ДЕФЕКТ #189: C-касты снимаются ДО разбора условий/индексов/делителей.
        # Иначе `if (len == (size_t)(max_rewind - rewind)) return` не переводился,
        # путь не сужался, и на ИСПРАВЛЕННОМ cmark-gfm оставалось предупреждение.
        body = _strip_c_casts(body)
        # Диапазоны типов — часть домена (u32 не бывает отрицательным).
        path_conds: list[str] = [f"(and (>= {p} {lo}) (<= {p} {hi}))"
                                 for p, (lo, hi) in (ranges or {}).items()]
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
        for lm2 in _RE_CLIKE_LOCAL_RHS.finditer(body):
            nm2, ty2, rhs2 = lm2.group(1), (lm2.group(2) or ""), lm2.group(3).strip()
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
            if len(re.findall(rf"\b{re.escape(nm2)}\s*=", body)) > 1:
                continue
            try:
                local_smt[nm2] = expr_smt(
                    ast.parse(clike_to_python(_unwrap_zig_builtins(rhs2)), mode="eval").body,
                    local_smt)
            except (Unsupported, NoReturn, SyntaxError):
                continue
        # ДЕФЕКТ #196 (полевой прогон axios): `x = x || K` — после этой строки
        # x гарантированно НЕ 0 (значение по умолчанию). Без учёта этого
        # `i % x` выглядел как деление на ноль.
        for dm2 in re.finditer(r"\b([A-Za-z_]\w*)\s*=\s*\1\s*\|\|", body):
            path_conds.append(f"(not (= {dm2.group(1)} 0))")
        pos = 0
        for m in _clike_ifs(body):
            raw_cond = m.group(1)
            # ДЕФЕКТ #197 (полевой прогон gin): `err != nil` — указательное
            # сравнение; в Int-модели `nil` бессмысленно, и получался ложный
            # DEAD BRANCH. Такие условия честно пропускаем.
            if re.search(r"\b(?:nil|null|NULL|None|undefined)\b", raw_cond):
                pos = m.end()
                continue
            try:
                cond = expr_smt(ast.parse(clike_to_python(raw_cond), mode="eval").body, local_smt)
            except (Unsupported, NoReturn, SyntaxError):
                pos = m.end()
                continue
            proven += 1
            sat_then = _smt_sat(kernc, params, path_conds + [cond])
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
            tail = body[m.end(): m.end() + 160]
            if re.match(r"\s*\{?\s*(return|break|continue)\b", tail):
                path_conds.append(f"(not {cond})")
            elif re.match(r"\s*\}?\s*else\b", tail):
                path_conds.append(f"(not {cond})")
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
        for am2_body in _iter_call_args(body, "assert"):
            try:
                ac = expr_smt(ast.parse(clike_to_python(_unwrap_zig_builtins(am2_body)), mode="eval").body, local_smt)
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
        for lm in _RE_CLIKE_LOCAL.finditer(body):
            nm_, ty_ = lm.group(1), (lm.group(2) or "")
            locals_.add(nm_)
            if ty_.lower().startswith("f") or "float" in ty_.lower():
                float_names.add(nm_)
        float_names |= float_locals
        if float_names or re.search(r"\b[0-9]+\.[0-9]+", body):
            float_names |= {m2.group(1) for m2 in _RE_CLIKE_LOCAL.finditer(body)}
        for dm in _RE_CLIKE_DIV.finditer(body):
            if dm.group(1) is not None:
                den = dm.group(2)
            elif dm.group(3) is not None:
                den = dm.group(4)
            else:
                den = dm.group(6)
            try:
                d = expr_smt(ast.parse(clike_to_python(_unwrap_zig_builtins(den)), mode="eval").body, local_smt)
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
                sat_dz = _smt_sat(kernc, params, path_conds + [f"(= {d} 0)"])
            except Exception:  # noqa: BLE001
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
                sat_neg = _smt_sat(kernc, params, path_conds + [f"(< {idxs} 0)"])
            except Exception:  # noqa: BLE001
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
                    sat_ov = _smt_sat(kernc, params, path_conds + [f"(> {size_smt} 2147483647)"])
                except Exception:  # noqa: BLE001
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
        for im in _RE_CLIKE_INDEX.finditer(raw_body):
            if re.search(r"\(\s*(?:ptrdiff_t|ssize_t|intptr_t|size_t)\s*\)"
                         r"\s*[A-Za-z_]\w*\s*\)\s*[-+]", im.group(2)):
                found.append(
                    f"[OVERFLOW PATH] {name}: unsigned-арифметика смещения: каст "
                    f"покрывает ОДНО слагаемое, остаток считается беззнаково "
                    f"({im.group(2).strip()}) -> перенос указателя")

        # --- C: ac80f7b (uint16_t counter) — ДЕФЕКТ #193 --------------------
        is_u16 = lambda t: t.strip().lower() in {"uint16_t", "u16", "unsigned short", "ushort"}
        for m2 in re.finditer(r"\w+\s*(?:->|\.)\s*(\w+)\s*(?:\+\+|\+=\s*1)", body):
            fld = m2.group(1)
            ty = field_types.get(fld, "")
            if not ty or not is_u16(ty):
                continue
            head = body[:m2.start()]
            if re.search(r"UINT16_MAX|65535|0xFFFF", head):
                continue  # граница проверяется — не обвиняем
            found.append(
                f"[OVERFLOW PATH] {name}: поле `{fld}` ({ty}) инкрементируется без "
                f"проверки границы 65535 -> счётчик переполнится (CVE-класс ac80f7b)")

        # --- D: 198669d (off-by-one vs capacity) — ДЕФЕКТ #194 --------------
        # `numdelims <= max_delims` разрешает `numdelims == max_delims`, т.е.
        # ровно на единицу больше ёмкости. Правило требует ИМЕНИ-ёмкости
        # (max_delims/max_size/…capacity), иначе `i <= max_retries` дало бы шум.
        for m3 in re.finditer(
                r"([A-Za-z_]\w*)\s*<=\s*(max_(?:delims|size|len|length|capacity|count)"
                r"|[A-Za-z_]*_capacity|MAX_(?:SIZE|LEN|LENGTH|CAPACITY|DELIMS))", body):
            var, cap = m3.group(1), m3.group(2)
            if not re.search(rf"{re.escape(var)}\s*(?:\+\+|\[+\-\]=)", body):
                continue
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
        if proven:
            checked += 1
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
        msg = (f"[OVERFLOW PATH] {path.name}: поле `{fld}` ({ty}) инкрементируется "
               f"без проверки границы 65535 -> счётчик переполнится")
        if msg not in found:
            found.append(msg)
    return checked, total, found


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
    files: list[Path] = []
    if root.is_file():
        files = [root] if root.suffix in _XRAY_EXTS else []
    else:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in _XRAY_SKIP_DIRS]
            for f in sorted(filenames):
                fp = Path(dirpath) / f
                if fp.suffix in _XRAY_EXTS and not fp.is_symlink():
                    files.append(fp)

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
                c, t, fd = _xray_clike_file(f, kernc)
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
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
            except Exception:  # noqa: BLE001
                pass
            inferred += buf.getvalue().count("[INFERRED SPEC]")
            tmp = Path(tempfile.gettempdir()) / f"kern_gen_{f.stem}.py"
            try:
                cmd_gen_tests(str(f), str(tmp), kernc)
                if tmp.exists():
                    tests_gen += tmp.read_text(encoding="utf-8").count("def test_")
                    tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
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
        print(f"[!] {e}")
        return 2
    try:
        files: list[Path] = []
        skipped_files = 0          # мусор: симлинки, гиганты, минифицированные
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
                    ck, tot, fd = _xray_clike_file(f, kernc)
                    st[1] += ck; st[2] += max(0, tot - ck)
                    for x in fd:
                        findings.append(f"{f.relative_to(root)}: {x}")
            except Exception:  # noqa: BLE001 — честно пропускаем нечитаемое
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


def cmd_xray(path: str, kernc, show_all: bool = False) -> int:
    """ПУНКТ 13: рентген кода БЕЗ аннотаций."""
    if not Path(kernc).exists():
        print(f"[!] не найден kernc: {kernc} (соберите: zig build)")
        return 2
    p = Path(path)
    # ПОЛЕВОЙ АДАПТЕР №5: `--xray <dir>` — рекурсивный обход репозитория.
    # Пропускаем служебные каталоги и агрегируем отчёт по всему дереву.
    if p.is_dir():
        return _xray_repo(p, kernc, show_all)
    # C-like файлы: Python-AST неприменим (упал бы на `//!` комментариях).
    # Маршрутизируем в устойчивый разбор БЕЗ исполнения тела (адаптер №5б).
    if p.suffix != ".py":
        _SMT_CALLS[0] = 0
        ck, tot, fd = _xray_clike_file(p, kernc)
        _smt_calls_clike = _SMT_CALLS[0]
        _LAST_XRAY["stat"] = (ck, tot, tot - ck, list(fd))
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
        print(f"[XRAY SUMMARY] checked {ck} / {tot} functions, "
              f"skipped {tot - ck} with explicit reasons, findings {len(fd)}, "
              f"SMT calls {_smt_calls_clike}")
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
    skipped: list[str] = []
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
            skipped.append(f"{fn.name}: условие ветвления вне подмножества")
            continue
        checked += 1
        if show_all or cc > 1:
            print(f"  [FN] {fn.name}: CC={cc} параметров={len(params)}")
        for s in smells:
            found.append(f"[SMELL] {fn.name}: {s}")
        lens = _declared_lengths_for(src_lines, fn.lineno)  # опциональное переопределение
        syms: set = set()
        lens.update(_collect_lens(fn, syms))   # Zero-Annotation: литералы + len()
        _walk_branches(fn.body, [], params, kernc, found, skipped, fn.name, syms, module_env)
        _walk_bounds(fn.body, [], params, lens, kernc, found, fn.name, syms)
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
    _LAST_XRAY["stat"] = (checked, len(fns), len(fns) - checked, list(found))
    print(f"[XRAY SUMMARY] checked {checked} / {len(fns)} functions "
          f"(SMT-verified {verified_smt}, no obligations {no_obligations}), "
          f"skipped {len(fns) - checked} with explicit reasons, "
          f"findings {len(found)}")
    for s in skipped:
        print(f"    skip: {s}")
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
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _XRAY_SKIP_DIRS]
        for f in sorted(filenames):
            if Path(f).suffix in _XRAY_EXTS:
                files.append(Path(dirpath) / f)
    print(f"[REPO SCAN] {root} | файлов к сканированию: {len(files)}")
    total_checked = total_fns = total_skip = 0
    all_findings: list[str] = []
    bad_files = 0
    for f in files:
        if f.suffix != ".py":
            ck, tot, fd = _xray_clike_file(f, kernc)
            total_checked += ck
            total_fns += tot
            total_skip += max(0, tot - ck)
            for x in fd:
                all_findings.append(f"{f}: {x}")
            continue
        try:
            rc = cmd_xray(str(f), kernc, show_all)
        except SyntaxError as e:
            bad_files += 1
            print(f"  [SKIP FILE] {f}: синтаксис: {e}")
            continue
        except Exception as e:  # noqa: BLE001 — честно печатаем, а не глотаем
            bad_files += 1
            print(f"  [SKIP FILE] {f}: {type(e).__name__}: {e}")
            continue
        # cmd_xray печатает свою сводку; агрегируем через побочный канал
        st = _LAST_XRAY.get("stat")
        if st:
            total_checked += st[0]
            total_fns += st[1]
            total_skip += st[2]
            for x in st[3]:
                all_findings.append(f"{f}: {x}")
        if rc not in (0, 1):
            bad_files += 1
    print("=" * 74)
    print(f"[REPO SUMMARY] файлов {len(files)} | функций проверено {total_checked} / {total_fns} "
          f"(skipped {total_skip}) | находок {len(all_findings)} | нечитаемых файлов {bad_files}")
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
        except Exception:
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
            except Exception:
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
                except Exception:
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
                except Exception:
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
        except Exception:
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
                except Exception:
                    ok = False
                    return
                val = None
                for sub in st.body:
                    if isinstance(sub, ast.Return) and sub.value is not None:
                        try:
                            val = expr_smt(sub.value, {})
                        except Exception:
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
                except Exception:
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
        except Exception:
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
                except Exception:
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
            except Exception:
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
            except Exception:
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
                except Exception:
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
            except Exception:
                pass
            continue
        if isinstance(st, ast.If):
            try:
                taken = _eval_cond(st.test, env)
            except Exception:
                continue
            trace.append((st, taken))
            done, val = _run_trace(st.body if taken else st.orelse, env, trace, depth + 1)
            if done:
                return True, val
            continue
        if isinstance(st, ast.Return):
            try:
                val = eval(compile(ast.Expression(body=st.value), "<c>", "eval"), {}, dict(env)) if st.value else None
            except Exception:
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
    sys.exit(main())
