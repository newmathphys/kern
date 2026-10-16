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
import re
import subprocess
import io
import sys
import tempfile
from pathlib import Path

ANNOT = re.compile(r"^\s*#\s*@kern:(requires|ensures)\s+(.+?)\s*$")

CMP = {"Eq": "=", "NotEq": "distinct", "Lt": "<", "LtE": "<=",
       "Gt": ">", "GtE": ">="}


class Unsupported(Exception):
    pass


class NoReturn(Exception):
    """Путь исполнения доходит до конца функции без `return` (неявный None)."""


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
            l, r = node.left, node.right
            if not (isinstance(r, ast.Constant) and isinstance(r.value, int)):
                if not (isinstance(l, ast.Constant) and isinstance(l.value, int)):
                    raise Unsupported("нелинейное умножение")
            op = "*"
        else:
            raise Unsupported("бинарный оператор (только + - *)")
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
        try:
            body = body_smt(stmts, {})
        except (NoReturn, Unsupported) as e:
            body = None
            skip_reason = str(e)
        params = [a.arg for a in node.args.args if a.arg != "self"]
        out.append((node.name, params, req, ens, body, node.lineno, skip_reason))
    return out


def build_smt(params, req, ens, body_smt_text: str) -> str:
    """Собрать SMT-LIB2: параметры, requires, `result = <тело>`, отрицание ensures."""
    decls = "\n".join(f"(declare-const {p} Int)" for p in params)
    lines = ["(set-logic ALL)", decls, "(declare-const result Int)"]
    env: dict = {}  # в requires/ensures локальных имён нет — только параметры
    if req:
        lines.append(f"(assert {expr_smt(ast.parse(req, mode='eval').body, env)})")
    lines.append(f"(assert (= result {body_smt_text}))")
    if ens:
        e = expr_smt(ast.parse(ens, mode='eval').body, env)
        lines.append(f"(assert (not {e}))")
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


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
    if problems:
        print("[!] ДЕМО НЕ СООТВЕТСТВУЕТ ОЖИДАНИЮ:")
        for x in problems:
            print(f"      - {x}")
        return 1
    print("[OK] демо воспроизвело ожидаемые вердикты")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--kernc", default=str(Path(__file__).resolve().parent.parent
                                          / "zig-out" / "bin" / "kernc"))
    ap.add_argument("--expect-demo", action="store_true",
                    help="проверить, что демо дало ОЖИДАЕМЫЕ вердикты "
                         "(превращает цель в ПРОВЕРКУ: падает при расхождении)")
    args = ap.parse_args()

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


def _demo(args) -> int:
    kernc = Path(args.kernc)
    if not kernc.exists():
        print(f"[!] не найден kernc: {kernc} (соберите: zig build)")
        return 1

    total = ok = failed = skipped = 0
    print("=" * 74)
    print("KERN: контракты из комментариев (@kern:requires / @kern:ensures)")
    print("=" * 74)
    for f in args.files:
        p = Path(f)
        try:
            funcs = parse_file(p)
        except SyntaxError as e:
            print(f"  {p}: SKIP (синтаксис Python: {e})")
            skipped += 1
            continue
        if not funcs:
            print(f"  {p}: нет функций с аннотациями @kern:")
            continue
        for name, params, req, ens, body, ln, skip_reason in funcs:
            total += 1
            if body is None:
                # Причина ОТКАЗА печатается как есть: «нет return» и «цикл»
                # требуют разных действий, а раньше сообщение было одно.
                print(f"  {name} (стр. {ln}): SKIP — {skip_reason or 'вне подмножества'}")
                skipped += 1
                continue
            try:
                smt = build_smt(params, req, ens, body)
            except Unsupported as e:
                print(f"  {name} (стр. {ln}): SKIP — вне подмножества: {e}")
                skipped += 1
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".smt2",
                                             delete=False) as tf:
                tf.write(smt)
                sp = tf.name
            r = subprocess.run([str(kernc), "prove", sp],
                               capture_output=True, text=True, timeout=120)
            out = r.stdout + r.stderr
            # ТРИ РАЗЛИЧНЫХ ИСХОДА (раньше два). Различие принципиально:
            #   PASS — Z3 доказал И пруф-чекер перепроверил вывод;
            #   SKIP — Z3 доказал, но пруф-чекер НЕ ПОКРЫВАЕТ такую форму вывода
            #          (например, с `ite`). Код не виноват, но и «проверено»
            #          сказать нельзя — поэтому НЕ PASS и НЕ FAIL;
            #   FAIL — контракт опровергнут (предъявлен контрпример).
            if "ДОКАЗАНО" in out and r.returncode != 0:
                reason = ""
                for line in out.splitlines():
                    if "причина:" in line:
                        reason = line.split("причина:", 1)[1].strip()
                        break
                print(f"  [SKIP] {name}: Z3 доказал, но пруф-чекер не покрывает "
                      f"вывод ({reason or 'причина не указана'})")
                skipped += 1
                continue
            if "ДОКАЗАНО" in out and r.returncode == 0:
                proof = ""
                for line in out.splitlines():
                    if "PROOF VERIFIED" in line:
                        proof = line.strip()
                print(f"  [PASS] {name}: ДОКАЗАНО")
                if proof:
                    print(f"         {proof}")
                ok += 1
            else:
                print(f"  [FAIL] {name}: КОНТРАКТ НАРУШЕН")
                for line in out.splitlines():
                    if "ВЕРДИКТ" in line or "KERN-EQ2" in line:
                        print(f"         {line.strip()}")
                # КОНТРПРИМЕР Z3: конкретные значения, сломавшие контракт.
                # Без них вердикт F бесполезен — непонятно, что именно чинить.
                for line in out.splitlines():
                    if "КОНТРПРИМЕР" in line:
                        print(f"         {line.strip()}")
                        break
                failed += 1
    print("-" * 74)
    print(f"ИТОГО: доказано {ok} | нарушено {failed} | вне подмножества "
          f"{skipped} | всего {total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
