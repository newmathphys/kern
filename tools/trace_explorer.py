#!/usr/bin/env python3
"""Ступень 2: AST-guided trace explorer (живой дифференциальный прогон).

ЗАЧЕМ. Ступень 1 (`body_smt` -> Z3 -> proof_check.zig) переводит функцию в
QF_LIA. Если в теле есть строки, словари, битовые операции, float или вызовы,
Ступень 1 пишет `SKIP` — и функция вообще не проверяется (измерено: 32/40
QuixBugs, 587/595 функций библиотек).

Ступень 2 НЕ переводит код в формулу. Она:
  1) читает AST ОБЕИХ версий функции и выводит ПО ИСПОЛЬЗОВАНИЮ, какого типа
     значения ждёт каждый параметр (биты/`%`/`//` -> int; `for x in p`,
     `p[i]`, `len(p)` -> последовательность; `.split()/.join()/.lower()` ->
     строка; сравнение с float-константой -> float);
  2) строит домен из констант самого кода (`c-1, c, c+1`) и граничных
     значений;
  3) исполняет ОБЕ версии вживую с таймаутом и лимитом рекурсии, под
     `sys.settrace` (покрытие строк) — по правилу №4 «модель не судья».

ЗВУЧНОСТЬ. Расхождение заявляется ТОЛЬКО когда на одном и том же входе
`buggy` и `correct` РЕАЛЬНО дали разный результат (значение или «упало/не
упало»). Это то же правило, что Live Replay Ступени 1 (дефекты #206, #209):
ложное обвинение физически невозможно, чем бы ни была заполнена модель Z3.

Использование:
    python3 tools/trace_explorer.py /tmp/QuixBugs-master [--json out.json]
"""
import ast
import collections
import copy
import importlib.util
import inspect
import itertools
import json
import re
import signal
import sys
import time
from pathlib import Path

MAX_COMBOS = 250          # потолок перебора на функцию
CALL_TIMEOUT = 1          # сек на один живой вызов (SIGALRM)
REC_LIMIT = 250
TASK_BUDGET = 6.0         # сек на одну задачу (защита от вечного перебора)

BIT_OPS = (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift,
           ast.Mod, ast.FloorDiv, ast.Invert)
STR_METHODS = {"split", "join", "lower", "upper", "strip", "lstrip", "rstrip",
               "replace", "startswith", "endswith", "find", "index", "format",
               "encode", "decode", "isdigit", "isalpha", "count", "zfill",
               "rfind", "rindex", "splitlines", "ljust", "rjust", "center",
               "partition", "rpartition", "swapcase", "capitalize", "title"}


class _Timeout(Exception):
    pass


def _alarm(_sig, _frm):
    raise _Timeout()


class _Tracer:
    """Считает исполненные строки ТОЛЬКО целевой функции."""

    def __init__(self, filename: str, first: int, last: int):
        self.file = filename
        self.first = first
        self.last = last
        self.lines: set = set()

    def __call__(self, frame, event, arg):
        if event == "line" and frame.f_code.co_filename == self.file:
            n = frame.f_lineno
            if self.first <= n <= self.last:
                self.lines.add(n)
        return self

# ---------------------------------------------------------------- домены


def _const_ints(tree: ast.AST) -> list:
    """Целочисленные константы тела (и `c±1` к ним) — приоритетные входы."""
    out: list = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) \
                and not isinstance(node.value, bool):
            for d in (-1, 0, 1):
                v = int(node.value) + d
                if -1000 <= v <= 1000 and v not in out:
                    out.append(v)
    return out


def _kinds(tree: ast.AST, name: str) -> set:
    """Как используется параметр `name` — по фактическим операциям в AST."""
    kinds: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            for side in (node.left, node.right):
                if isinstance(side, ast.Name) and side.id == name:
                    kinds.add("int")
                    if isinstance(node.op, BIT_OPS):
                        kinds.add("bit")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
            if isinstance(node.operand, ast.Name) and node.operand.id == name:
                kinds.update(("int", "bit"))
        elif isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == name:
                kinds.add("seq")
        elif isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            if any(isinstance(s, ast.Name) and s.id == name for s in sides) and \
                    any(isinstance(s, ast.Constant) and isinstance(s.value, float)
                        for s in sides):
                kinds.add("float")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in STR_METHODS and \
                    isinstance(f.value, ast.Name) and f.value.id == name:
                kinds.add("str")
            if isinstance(f, ast.Name) and f.id == "len" and node.args and \
                    isinstance(node.args[0], ast.Name) and node.args[0].id == name:
                kinds.add("seq")
            if isinstance(f, ast.Name) and f.id in ("abs", "round", "float") \
                    and node.args and isinstance(node.args[0], ast.Name) \
                    and node.args[0].id == name:
                kinds.add("float")
        elif isinstance(node, (ast.For, ast.comprehension)):
            it = node.iter
            if isinstance(it, ast.Name) and it.id == name:
                kinds.add("seq")
            elif isinstance(it, ast.Call) and isinstance(it.func, ast.Name) \
                    and it.func.id in ("range", "len") and it.args \
                    and isinstance(it.args[0], ast.Name) and it.args[0].id == name:
                kinds.add("int")
        elif isinstance(node, ast.While) and isinstance(node.test, ast.Name) \
                and node.test.id == name:
            kinds.add("int")
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Name) \
                and node.test.id == name:
            kinds.add("truthy")
    return kinds


_INT_DOMAIN = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 16, 17,
               20, 25, 31, 32, 48, 63, 64, 100, 128, 255, 256,
               # 0 и отрицательные — ПОСЛЕ положительных: docstring большинства
               # задач требует «positive/nonnegative int», и первое найденное
               # расхождение должно быть на валидном входе (Defect #200).
               0, -1, -2]
_SEQ_DOMAIN = (
    # 1) Списки ЧИСЕЛ — то, что документируют docstring'и большинства задач.
    #    Идут ПЕРВЫМИ: первое найденное расхождение должно быть на валидном
    #    входе, а не на экзотическом (иначе свидетельство слабее, Defect #200).
    [], [0], [1], [1, 2], [2, 1], [1, 2, 0], [0, 1, 2], [2, 0, 1],
    [1, 3, 2], [2, 3, 1], [0, 2, 1], [1, 2, 3], [3, 2, 1], [3, 1, 2],
    [-1, 2, -1], [2, -1, 2], [1, -2, 3, -1], [-1, -2], [0, 1, 2, 3, 4],
    [1, 2, 2, 3], [5, 4, 3, 2, 1], [1, 1, 1], [2, 1, 2, 1],
    # 2) Строки и токены — для строковых и калькуляторных задач.
    ["a"], ["("], ["(", ")"], ["()"], [")(("],
    ["+"], ["+", 1, 2], [3, 5, "+"], [4, 2, "-"], [6, 2, "/"],
    # 3) Вложенные структуры — ПОСЛЕДНИМИ: они вне документированного входа
    #    у большинства задач (для lis/flatten это допустимо, для остальных нет).
    [[1, 2], [3]], [[1], [2, 3], []], [[3, 4], [1, 2]], [(0, 1), (0, 2)],
)
_STR_DOMAIN = ["", "a", "ab", "abc", "abcd", "()", "((()", ")(", "()[]{}",
               "a b c", "abcdef", "  ", "0", "1", "-1"]
_FLOAT_DOMAIN = [0.0, 0.5, 1.0, 2.0, 2.5, 4.0, 9.0, 16.0, 0.1, -1.0, -2.5]


def module_doc(tree: ast.AST) -> str:
    """Docstring модуля — где бы он ни стоял.

    `ast.get_docstring()` читает только ПЕРВЫЙ statement, а в QuixBugs
    документация лежит в КОНЦЕ файла (после функции). Из-за этого
    объявленные типы не читались и свидетельства брались на невалидных
    входах (`['(']` вместо `'('`).
    """
    doc = ""
    for node in getattr(tree, "body", []):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            doc = node.value.value
    return doc


def declared_kind(doc: str, name: str) -> str | None:
    """Тип параметра, ОБЪЯВЛЕННЫЙ в docstring (секция `Input:`).

    Зачем: домен по AST описывает лишь то, как значение ИСПОЛЬЗУЕТСЯ.
    Список вида `["("]` и строка `"("` для `for c in parens` неотличимы,
    но docstring говорит «A string of parentheses». Свидетельство должно
    быть на ВАЛИДНОМ входе (Defect #200), поэтому объявленный тип важнее.
    """
    if not doc:
        return None
    m = re.search(r"^\s*Input:\s*$", doc, re.M)
    if not m:
        return None
    block = doc[m.end():]
    stop = re.search(r"^\s*(Output|Precondition|Example|Postcondition):",
                     block, re.M)
    if stop:
        block = block[:stop.start()]
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        if k.strip().lstrip("*") != name:
            continue
        t = v.lower()
        if "string" in t or "str" in t:
            return "str"
        if "float" in t or "real" in t:
            return "float"
        if "list" in t or "array" in t or "sequence" in t or "tuple" in t:
            return "seq"
        if "int" in t or "number" in t:
            return "int"
    return None


def domain_for(tree: ast.AST, name: str, declared: str | None = None) -> list:
    """Домен значений параметра по его ФАКТИЧЕСКОМУ использованию в AST."""
    kinds = _kinds(tree, name)
    if declared:
        kinds = set(kinds) | {declared}
    dom: list = []
    ints = _const_ints(tree)
    # Положительные — первыми, затем 0, затем отрицательные: docstring'и
    # чаще требуют positive/nonnegative (Defect #200).
    ints.sort(key=lambda v: (0 if v > 0 else (1 if v == 0 else 2), abs(v)))
    if declared == "str":
        dom.extend(_STR_DOMAIN)
    elif declared == "seq":
        dom.extend(_SEQ_DOMAIN)
    elif declared == "float":
        dom.extend(_FLOAT_DOMAIN)
    if "float" in kinds:
        dom.extend(_FLOAT_DOMAIN)
        dom.extend(float(v) for v in ints[:12])
    if "str" in kinds:
        dom.extend(_STR_DOMAIN)
    if "seq" in kinds or "truthy" in kinds:
        dom.extend(_SEQ_DOMAIN)
    if "bit" in kinds:
        dom.extend([0, 1, 2, 3, 4, 5, 7, 8, 15, 16, 17, 31, 32, 33, 63, 64,
                    65, 127, 128, 255, 256, 1023])
    if "int" in kinds or "bit" in kinds or "truthy" in kinds or not dom:
        dom.extend(ints[:20])
        dom.extend(_INT_DOMAIN)
    seen, out = set(), []
    for v in dom:
        key = (type(v).__name__, repr(v))
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out

# ---------------------------------------------------------------- вызовы


def load_fn(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(f"te_{path.stem}_{id(path)}", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:                            # noqa: BLE001
        return None
    fn = getattr(mod, name, None)
    return fn if callable(fn) else None


def call(fn, kwargs: dict, tracer=None):
    """Живой вызов: (ok, value_or_error, covered_lines)."""
    old = signal.signal(signal.SIGALRM, _alarm)
    old_limit = sys.getrecursionlimit()
    signal.alarm(int(CALL_TIMEOUT) or 1)
    sys.setrecursionlimit(REC_LIMIT)
    prev = sys.gettrace()
    if tracer is not None:
        sys.settrace(tracer)
    try:
        return True, fn(**kwargs), (tracer.lines if tracer else None)
    except _Timeout:
        return False, "TIMEOUT", (tracer.lines if tracer else None)
    except RecursionError:
        return False, "RecursionError", (tracer.lines if tracer else None)
    except Exception as e:                       # noqa: BLE001
        return False, f"{type(e).__name__}: {e}", (tracer.lines if tracer else None)
    finally:
        signal.alarm(0)
        sys.settrace(prev)
        signal.signal(signal.SIGALRM, old)
        sys.setrecursionlimit(old_limit)


def precondition_of(tree: ast.AST) -> str | None:
    """Исполняемый текст «Precondition:» из docstring модуля (если он есть).

    Зачем: свидетельство обязано быть на входе ИЗ ДОКУМЕНТИРОВАННОГО ДОМЕНА.
    `get_factors` документирует `n >= 1`, поэтому расхождение на `n = 0`
    доказывало бы не баг в коде, а выход за предусловие (Defect #200 —
    «обвинение вне домена обесценивает результат»).
    """
    doc = ""
    for node in tree.body:                       # docstring в QuixBugs — в КОНЦЕ файла
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            doc = node.value.value
            break
    doc = doc or (ast.get_docstring(tree) or "")
    i = doc.find("Precondition:")
    if i < 0:
        return None
    lines = []
    for line in doc[i + len("Precondition:"):].splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("Output:", "Example", "Examples:", '"""')):
            break
        lines.append(s)
    expr = " ".join(lines).strip().rstrip(".").strip()
    return expr or None


_PRE_NAMES = {"all": all, "any": any, "isinstance": isinstance, "len": len,
              "int": int, "str": str, "float": float, "abs": abs,
              "list": list, "tuple": tuple, "dict": dict, "set": set}


def precondition_ok(expr: str | None, args: dict) -> bool:
    """Проверка аргументов на документированное предусловие.

    НЕРАЗОБРАННОЕ предусловие НЕ отсеивает входы: выдумывать ограничение,
    которого нет в тексте, — то же искажение, что и игнорировать реальное.
    """
    if not expr:
        return True
    try:
        # Имена (all/isinstance/int/...) кладём в GLOBALS: генераторное выражение
        # внутри `all(... for x in arr)` имеет собственную область и ищет имена
        # именно в globals — иначе NameError, фильтр молча пропускает всё.
        env = {"__builtins__": {}, **_PRE_NAMES, **dict(args)}
        r = eval(expr, env)
        # `to_base` пишет два условия через запятую -> eval даёт КОРТЕЖ:
        # без этого `bool((True, False))` == True, и фильтр пропускал бы всё.
        if isinstance(r, tuple):
            return all(bool(x) for x in r)
        return bool(r)
    except Exception:                            # noqa: BLE001
        return True


def _params(fn) -> list:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return []
    return [n for n, p in sig.parameters.items()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            and p.default is p.empty and n != "self"]


def _span(tree: ast.AST, name: str) -> tuple:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node.lineno, node.end_lineno or node.lineno
    return 1, 10 ** 9


def _uniq(vals: list) -> list:
    seen, out = set(), []
    for v in vals:
        key = (type(v).__name__, repr(v))
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _norm(v, depth: int = 0):
    """Рекурсивно нормализовать результат для сравнения.

    ДЕФЕКТ (найден этим замером): `flatten`/`kheapsort` возвращают ГЕНЕРАТОР,
    причём `flatten` — генератор ВЛОЖЕННЫХ генераторов. Два разных объекта
    никогда не равны, поэтому наивное сравнение объявляло «расхождение» на
    любом входе (адрес в памяти). Материализуем рекурсивно.
    """
    if depth > 4:
        return ("<deep>", type(v).__name__)
    if isinstance(v, (str, bytes, int, float, bool, type(None))):
        return v
    if isinstance(v, dict):
        return ("<dict>", sorted((repr(k), _norm(x, depth + 1))
                                 for k, x in v.items()))
    if isinstance(v, (list, tuple, set)):
        return ("<seq>", [_norm(x, depth + 1) for x in v])
    if hasattr(v, "__iter__"):
        try:
            return ("<iter>", [_norm(x, depth + 1) for x in v])
        except Exception as e:                   # noqa: BLE001
            # Материализовать НЕЛЬЗЯ (например, buggy-flatten отдаёт
            # генератор, который падает при первом же next). Это само по себе
            # расхождение — печатаем причину, а не безымянный <obj>.
            return ("<broken-iter>", f"{type(v).__name__}: {type(e).__name__}: {e}"[:60])
    return ("<obj>", type(v).__name__)


# Односторонний `TypeError`/`AttributeError` = мы подали аргумент НЕ ТОГО
# ТИПА (например, int вместо list), а не баг в коде. Такие входы отбрасываются.
_TYPE_MISMATCH = ("TypeError", "AttributeError")


def _render(v) -> str:
    """Человекочитаемая печать нормализованного значения."""
    if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str) and v[0].startswith("<"):
        tag, payload = v
        if isinstance(payload, list):
            return "[" + ", ".join(_render(x) for x in payload) + "]"
        return f"{tag}{payload!r}"
    return repr(v)


def _show(v) -> str:
    """Печать нормализованного результата (генераторы — материализованные)."""
    return _render(v)


def explore(buggy: Path, correct: Path, fn_name: str) -> dict:
    """Ступень 2 для одной функции: синтез входов по AST + живой дифф-прогон."""
    fb = load_fn(buggy, fn_name)
    if fb is None:
        return {"fn": fn_name, "diverged": False, "tries": 0,
                "note": "не загрузить (импорт/декораторы)", "lines": "0/0"}
    fc = load_fn(correct, fn_name)
    if fc is None:
        return {"fn": fn_name, "diverged": False, "tries": 0,
                "note": "нет correct-версии", "lines": "0/0"}
    params = _params(fb)
    if not params or len(params) > 3:
        return {"fn": fn_name, "diverged": False, "tries": 0,
                "note": f"параметров {len(params)} (не поддержано)", "lines": "0/0"}
    try:
        tb = ast.parse(buggy.read_text(encoding="utf-8", errors="replace"))
        tc = ast.parse(correct.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as e:
        return {"fn": fn_name, "diverged": False, "tries": 0,
                "note": f"SyntaxError: {e}", "lines": "0/0"}
    doms = []
    for p in params:
        dk = declared_kind(module_doc(tb), p) or declared_kind(module_doc(tc), p)
        doms.append(_uniq(domain_for(tb, p, dk) + domain_for(tc, p, dk)[:10]))
    first, last = _span(tb, fn_name)
    body_lines = max(1, last - first + 1)
    tracer = _Tracer(str(buggy.resolve()), first, last)
    tries = 0
    crash_hit = None            # «упало vs не упало» — слабее, чем «значения»
    t0 = time.monotonic()
    # Порядок перебора: сначала комбинации БЕЗ отрицательных целых — это то,
    # что документируют docstring'и («nonnegative int», «positive int»).
    # Первое найденное расхождение должно быть на валидном входе (Defect #200).
    # Полный домен сохраняется: отрицательные идут следом, в пределах бюджета.
    combos = list(itertools.product(*doms))
    combos.sort(key=lambda c: sum(1 for v in c
                                  if isinstance(v, int) and not isinstance(v, bool)
                                  and v < 0))
    # Предусловие из docstring: свидетельство вне домена не считается
    # доказательством (Defect #200). Неразобранный текст не отсеивает.
    pre = precondition_of(tb) or precondition_of(tc)
    dropped = 0
    if pre:
        kept = [c for c in combos
                if precondition_ok(pre, dict(zip(params, c)))]
        dropped = len(combos) - len(kept)
        combos = kept
    for combo in combos:
        if tries >= MAX_COMBOS or (time.monotonic() - t0) > TASK_BUDGET:
            break
        tries += 1
        args = {p: copy.deepcopy(v) for p, v in zip(params, combo)}
        ok_b, vb, _ = call(fb, args, tracer)
        ok_c, vc, _ = call(fc, {p: copy.deepcopy(v) for p, v in zip(params, combo)})
        if ok_b and ok_c:
            nb, nc = _norm(vb), _norm(vc)
            if nb != nc:
                # СИЛЬНОЕ свидетельство: обе версии отработали, значения разные
                return {"fn": fn_name, "diverged": True, "tries": tries,
                        "note": f"{args} buggy={_show(nb)} correct={_show(nc)}",
                        "lines": f"{len(tracer.lines)}/{body_lines}"}
        elif ok_b != ok_c:
            err = (vb if not ok_b else vc)
            if isinstance(err, str) and err.startswith(_TYPE_MISMATCH):
                continue        # неверный тип аргумента — не баг в коде
            cand = {"fn": fn_name, "diverged": True, "tries": tries,
                    "note": (f"{args} buggy={'ok' if ok_b else vb} "
                             f"correct={'ok' if ok_c else vc}"),
                    "lines": f"{len(tracer.lines)}/{body_lines}"}
            if crash_hit is None:
                crash_hit = cand
    if crash_hit:
        return crash_hit
    return {"fn": fn_name, "diverged": False, "tries": tries,
            "note": f"нет расхождения на {tries} входах",
            "lines": f"{len(tracer.lines)}/{body_lines}"}


def functions_in(path: Path) -> list:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]


def run(qb: Path, json_out: Path | None) -> int:
    tasks = sorted(p.stem for p in (qb / "python_programs").glob("*.py")
                   if not p.stem.endswith("_test") and p.stem != "node")
    rows, hits = [], []
    for name in tasks:
        b_file = qb / "python_programs" / f"{name}.py"
        c_file = qb / "correct_python_programs" / f"{name}.py"
        if not c_file.exists():
            rows.append((name, "NO-CORRECT", "0", ""))
            continue
        c_names = set(functions_in(c_file))
        best = None
        for fn in functions_in(b_file):
            if fn not in c_names:
                continue
            r = explore(b_file, c_file, fn)
            if r["diverged"]:
                best = r
                break
            if best is None or r["tries"] > best["tries"]:
                best = r
        if best is None:
            rows.append((name, "SKIP", "0", "нет общих функций"))
            continue
        if best["diverged"]:
            rows.append((name, "DIVERGED", str(best["tries"]), best["note"]))
            hits.append((name, best["note"], best["lines"]))
        else:
            rows.append((name, "EXPLORED", str(best["tries"]), best["note"]))
        print(f"  [s2] {name:<22} {rows[-1][1]:<9} {best['tries']:>3}  "
              f"lines={best['lines']:<7} {best['note'][:90]}", flush=True)
    w = max((len(r[0]) for r in rows), default=4) + 2
    for r in rows:
        print(f"{r[0]:<{w}} {r[1]:<10} {r[2]:>4}  {r[3]}")
    cnt = collections.Counter(r[1] for r in rows)
    print("\n=== STAGE-2 SUMMARY ===")
    for k, v in cnt.most_common():
        print(f"  {k:<10} {v}")
    print(f"[OK] DIVERGED (живой вызов, 0 ложных по построению): "
          f"{len(hits)}/{len(rows)}")
    if json_out:
        json_out.write_text(json.dumps({"rows": rows, "hits": hits, "counts": cnt},
                                       ensure_ascii=False, indent=1),
                            encoding="utf-8")
    return 0


def main(argv: list) -> int:
    qb = Path("/tmp/QuixBugs-master")
    json_out = None
    i = 1
    while i < len(argv):
        if argv[i] == "--json" and i + 1 < len(argv):
            json_out = Path(argv[i + 1])
            i += 2
            continue
        qb = Path(argv[i])
        i += 1
    if not (qb / "python_programs").is_dir():
        print(f"[!] нет {qb}/python_programs — склонируйте QuixBugs")
        return 2
    return run(qb, json_out)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
