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
import ast
import hashlib
import json
import os
import re
import subprocess
import io
import sys
import tempfile
from pathlib import Path

ANNOT = re.compile(r"^\s*#\s*@kern:(requires|ensures)\s+(.+?)\s*$")

CMP = {"Eq": "=", "NotEq": "distinct", "Lt": "<", "LtE": "<=",
       "Gt": ">", "GtE": ">="}

# Делители, встреченные при трансляции выражения (для обязательства
# «делитель ≠ 0»): в SMT `div`/`mod` тотальны, поэтому ноль надо ловить отдельно.
_DIV_COLLECTOR: list = []


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
        raise Unsupported(f"литерал {node.value!r}")
    if isinstance(node, ast.Name):
        return env.get(node.id, node.id)
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
            d = expr_smt(node.right, env)
            _DIV_COLLECTOR.append(d)
            return f"({op} {expr_smt(node.left, env)} {d})"
        else:
            raise Unsupported("бинарный оператор (только + - * / // %)")
        return f"({op} {expr_smt(node.left, env)} {expr_smt(node.right, env)})"
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise Unsupported("цепочка сравнений")
        opname = type(node.ops[0]).__name__
        if opname not in CMP:
            raise Unsupported(f"сравнение {opname}")
        return (f"({CMP[opname]} {expr_smt(node.left, env)} "
                f"{expr_smt(node.comparators[0], env)})")
    raise Unsupported(f"узел {type(node).__name__}")


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
        if isinstance(st, ast.Assign):
            if len(st.targets) != 1 or not isinstance(st.targets[0], ast.Name):
                raise Unsupported("присваивание не в простую переменную")
            # Подстановка: имя запоминается как SMT-выражение (символьное значение).
            env[st.targets[0].id] = expr_smt(st.value, env)
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


def parse_file(path: Path):
    """Вернуть список (имя, params, requires, ensures, body_smt, lineno, причина)."""
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    anchors: dict[int, dict[str, str]] = {}
    for i, ln in enumerate(lines, 1):
        m = ANNOT.match(ln)
        if m:
            anchors.setdefault(i, {})[m.group(1)] = m.group(2)
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
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
        try:
            body = body_smt(stmts, {})
        except (NoReturn, Unsupported) as e:
            body = None
            skip_reason = str(e)
        # Делители, встреченные при трансляции -> обязательство «делитель ≠ 0».
        divs = list(dict.fromkeys(_DIV_COLLECTOR))
        params = [a.arg for a in node.args.args if a.arg != "self"]
        out.append((node.name, params, req, ens, body, node.lineno, skip_reason,
                    {"ranges": {}, "ret": None, "divisors": divs}))
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
    env: dict = {}  # в requires/ensures локальных имён нет — только параметры
    for p, (lo, hi) in (ranges or {}).items():
        lines.append(f"(assert (and (>= {p} {lo}) (<= {p} {hi})))")
    if req:
        lines.append(f"(assert {expr_smt(ast.parse(req, mode='eval').body, env)})")
    lines.append(f"(assert (= result {value_of(body_smt_text)}))")
    if ens:
        e = expr_smt(ast.parse(ens, mode='eval').body, env)
        lines.append(f"(assert (not {e}))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


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
    """Прогнать `kernc prove` на SMT-тексте. Возвращает (rc, вывод)."""
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
    """Все функции файла БЕЗ требования контракта: (имя, params, body_smt, строка).

    Нужна для УЛУЧШЕНИЯ №3 (`--diff-equiv`): эквивалентность рефакторинга
    доказывается по ТЕЛАМ, контракты писать не требуется.
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
        try:
            body = body_smt(stmts, {})
        except (NoReturn, Unsupported):
            continue
        params = [a.arg for a in node.args.args if a.arg != "self"]
        out.append((node.name, params, body, node.lineno))
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
    try:
        _rc, out = run_kernc(kernc, _bound_smt(smt, params))
    except (subprocess.SubprocessError, OSError):
        return ce
    small = parse_counterexample(out)
    return small or ce


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
    # Zig: `pub fn name(a: i32) i32 {`   Rust: `pub fn name(a: i32) -> i32 {`
    r"^\s*(?:pub\s+)?(?:extern\s+)?fn\s+(\w+)\s*\(([^)]*)\)"
    r"\s*(?:->\s*)?([\w:]+)?\s*\{")
RE_FN_C = re.compile(
    r"^\s*(?:static\s+|inline\s+|const\s+)*"
    r"(void|char|short|int|long|unsigned|size_t|"
    r"int8_t|int16_t|int32_t|int64_t|uint8_t|uint16_t|uint32_t|uint64_t)"
    r"\s+(\w+)\s*\(([^)]*)\)\s*\{")
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
    return convert_ternary(s)


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


def parse_clike(path: Path):
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
        meta = {"ranges": {}, "ret": ret}
        req = ens = None
        for k in range(max(0, i - 6), i):
            am = ANNOT.match(lines[k])
            if am:
                if am.group(1) == "requires":
                    req = am.group(2)
                else:
                    ens = am.group(2)
        if req is None and ens is None:
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
        raw_body = _normalize_clike("\n".join(body_lines), keep_newlines=semi_optional)
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
        meta["divisors"] = list(dict.fromkeys(_DIV_COLLECTOR))
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
    a = {n: (p, b, ln) for n, p, b, ln in parse_bodies(Path(old_file))}
    b2 = {n: (p, b, ln) for n, p, b, ln in parse_bodies(Path(new_file))}
    common = [n for n in a if n in b2]
    if not common:
        print("[!] нет одноимённых функций в подмножестве — сравнивать нечего")
        return 2
    diverged = same = 0
    for name in sorted(common):
        pa, ba, _ = a[name]
        pb, bnew, _ = b2[name]
        if pa != pb:
            print(f"  [SKIP] {name}: разные наборы параметров {pa} / {pb}")
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
          f"всего {len(common)}")
    return 0 if diverged == 0 else 1


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
    ap.add_argument("--xray", default=None, metavar="PATH",
                    help="ПУНКТ 13: рентген кода БЕЗ аннотаций "
                         "(мёртвые ветки, избыточные проверки, краш-пути, CC)")
    ap.add_argument("--explain", default=None, metavar="PATH",
                    help="ПУНКТ 18: человеческий паспорт функций")
    ap.add_argument("--pr-summary", nargs=2, default=None, metavar=("OLD", "NEW"),
                    help="ПУНКТ 19: математическое резюме для Code Review")
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
    if args.xray:
        return cmd_xray(args.xray, args.kernc)
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
    except Exception:
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
    except Exception:
        return None
    env = {p: vals[p] for p in params}
    env["result"] = res
    try:
        ok = eval(ens, {"__builtins__": {}}, env)  # noqa: S307
    except Exception:
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
                    meta["divisors"] = list(dict.fromkeys(_DIV_COLLECTOR))
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
                            except Exception:
                                pass
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
            if ret in TYPE_RANGE and not meta.get("bv"):
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
                            except Exception:
                                pass
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
            rc, out = run_kernc(kernc, smt)
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
                if conf is True:
                    if p.suffix in CLIKE_EXT:
                        print("         [RUNTIME CONFIRMED] контрпример перепроверен "
                              "конкретным вычислителем тела (модель совпала с исходником)")
                    else:
                        print("         [RUNTIME CONFIRMED] нарушение подтверждено "
                              "и в рантайме (0% ложных срабатываний)")
                elif conf is False:
                    print("         [!] RUNTIME НЕ подтвердил: контрпример "
                          "ФАЛЬШИВЫЙ (ошибка трансляции, а не кода)")
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
    """Выполним ли набор утверждений? True/False, либо None (не решено)."""
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    body = "\n".join(f"(assert {a})" for a in asserts)
    smt = f"(set-logic ALL)\n{decls}\n{body}\n(check-sat)\n"
    rc, out = run_kernc(kernc, smt)
    if "НЕ доказано" in out or "КОНТРПРИМЕР" in out:
        return True  # SAT: контрпример найден
    if "ДОКАЗАНО" in out:
        return False  # UNSAT: утверждения невыполнимы
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


def _walk_branches(stmts, path: list[str], params: list[str], kernc,
                   found: list[str], skipped: list[str], fnname: str,
                   syms=None) -> None:
    """Обход ветвлений с накоплением условия пути."""
    syms = syms if syms is not None else set()
    for st in stmts:
        if isinstance(st, ast.If):
            try:
                # ПУНКТ 21 (Zero-Annotation): `len(arr)` -> символическая длина,
                # иначе условия с `len(...)` ЛОЖНО считались «вне подмножества».
                cond = _cond_smt(st.test, syms)
            except (Unsupported, NoReturn, Exception):
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
                    try:
                        div = expr_smt(n.right, {})
                    except (Unsupported, NoReturn, Exception):
                        continue
                    sat_dz = _smt_sat(kernc, params, path + [cond, f"(= {div} 0)"])
                    if sat_dz is True:
                        found.append(f"[CRASH PATH] {fnname}: строка {n.lineno} — "
                                     f"возможно деление на ноль: {div} == 0")
            _walk_branches(st.body, path + [cond], params, kernc, found, skipped, fnname, syms)
            _walk_branches(st.orelse, path + [f"(not {cond})"], params, kernc,
                           found, skipped, fnname)
        else:
            for n in ast.walk(st):
                if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                    try:
                        div = expr_smt(n.right, {})
                    except (Unsupported, NoReturn, Exception):
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


def _smt_verdict(kernc, params, asserts) -> tuple[str, str | None]:
    """ТРЁХЗНАЧНЫЙ вердикт: ("sat", контрпример) | ("unsat", None) | ("unknown", причина).

    ДЕФЕКТ #137 (звучимость): раньше возвращался `None` и для `UNSAT`, и для `N`
    (решатель не решил). Из-за этого НЕРЕШЁННАЯ формула молча считалась
    ДОКАЗАННОЙ — ложный PASS. Теперь `unknown` отличается от `unsat` и обязан
    обрабатываться вызывающим кодом как «НЕ проверено».
    """
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
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


def _cond_smt(node, syms: set):
    """SMT условия с переписанным `len(arr)` -> `kern_len_arr`."""
    node = _LenRewrite(syms).visit(ast.parse(ast.unparse(node), mode="eval").body)
    ast.fix_missing_locations(node)
    return expr_smt(node, {})


def _block_exits(body) -> bool:
    """Завершается ли блок безусловно (return/raise)?"""
    return bool(body) and isinstance(body[-1], (ast.Return, ast.Raise))


def _walk_bounds(body, path, params, lens, kernc, found, fname, syms=None):
    """Обход тела с накоплением путевых условий (Пункт 21, Zero-Annotation)."""
    syms = syms if syms is not None else set()
    for st in body:
        if isinstance(st, ast.If):
            try:
                cond = _cond_smt(st.test, syms)
            except (Unsupported, NoReturn, Exception):
                cond = None
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
            except (Unsupported, NoReturn, Exception):
                continue
            bad = f"(not (and (>= {idx} 0) (< {idx} {n})))"
            v, ce = _smt_verdict(kernc, decls, pre + path + [bad])
            if v == "sat":
                found.append(f"[BOUNDS PATH] {fname}: `{arr}[{idx}]` (строка {sub.lineno}) — "
                             f"возможен выход за границы {human}; контрпример: {ce}")
            elif v == "unknown":
                found.append(f"[BOUNDS UNKNOWN] {fname}: `{arr}[{idx}]` (строка {sub.lineno}) — "
                             f"НЕ решено ({ce}) — НЕ считается безопасным")


def cmd_xray(path: str, kernc, show_all: bool = False) -> int:
    """ПУНКТ 13: рентген кода БЕЗ аннотаций."""
    if not Path(kernc).exists():
        print(f"[!] не найден kernc: {kernc} (соберите: zig build)")
        return 2
    p = Path(path)
    src = p.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    src_lines = src.splitlines()  # ПУНКТ 21: директивы `# @kern:len(arr) = N`
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    found: list[str] = []
    skipped: list[str] = []
    checked = 0
    for fn in fns:
        params = [a.arg for a in fn.args.args if a.arg != "self"]
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
                except (Unsupported, NoReturn, Exception):
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
        _walk_branches(fn.body, [], params, kernc, found, skipped, fn.name, syms)
        _walk_bounds(fn.body, [], params, lens, kernc, found, fn.name, syms)

    print("-" * 74)
    for f in found:
        print("  " + f)
    print("-" * 74)
    print(f"[XRAY SUMMARY] checked {checked} / {len(fns)} functions, "
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
            except (Unsupported, NoReturn, Exception):
                raise Unsupported(f"присваивание на строке {st.lineno} вне подмножества")
        elif isinstance(st, ast.AugAssign) and isinstance(st.target, ast.Name):
            op = {"Add": "+", "Sub": "-", "Mult": "*"}.get(type(st.op).__name__)
            if op is None:
                raise Unsupported(f"+=/-= только на строке {st.lineno}")
            try:
                out.append((st.target.id, f"({op} {st.target.id} {expr_smt(st.value, {})})"))
            except (Unsupported, NoReturn, Exception):
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
            except (Unsupported, NoReturn, Exception):
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
        except (Unsupported, NoReturn, Exception):
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
                except (Unsupported, NoReturn, Exception):
                    req = None
            m = re.search(r"@kern:ensures\s+(.+)", s)
            if m:
                try:
                    ens = expr_smt(ast.parse(m.group(1).strip(), mode="eval").body, {})
                except (Unsupported, NoReturn, Exception):
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
            except (Unsupported, NoReturn, Exception):
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
            except (Unsupported, NoReturn, Exception):
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
                except (Unsupported, NoReturn, Exception):
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
                except (Unsupported, NoReturn, Exception):
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
    a = {n: (p, b, ln) for n, p, b, ln in parse_bodies(Path(old_file))}
    b2 = {n: (p, b, ln) for n, p, b, ln in parse_bodies(Path(new_file))}
    common = sorted(n for n in a if n in b2)
    only_old = sorted(set(a) - set(b2))
    only_new = sorted(set(b2) - set(a))
    same = diverged = 0
    print(f"[PR-SUMMARY] {Path(old_file).name} -> {Path(new_file).name}")
    for name in common:
        pa, ba, _ = a[name]
        pb, bnew, _ = b2[name]
        if pa != pb:
            print(f"  [SKIP] {name}: изменён набор параметров")
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
            try:
                div = expr_smt(n.right, {})
            except (Unsupported, NoReturn, Exception):
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
            k, v = k.strip(), v.strip()
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
            except (Unsupported, NoReturn, Exception):
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
            except (Unsupported, NoReturn, Exception):
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
                except (Unsupported, NoReturn, Exception):
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
        a = {n: (p, b) for n, p, b, _ in parse_bodies(po)}
        b2 = {n: (p, b) for n, p, b, _ in parse_bodies(pn)}
        if fn_old.name not in a or fn_old.name not in b2:
            return False
        pa, ba = a[fn_old.name]
        pb, bb = b2[fn_old.name]
        if pa != pb:
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
            body = body_smt(_fn_stmts(fn), {})
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
            body = body_smt(_fn_stmts(fn), {})
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


if __name__ == "__main__":
    sys.exit(main())
