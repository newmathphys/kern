#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ОКНО №15: Live Replay, ведомый моделью Z3 (краевой конструктор входов).

ЗАЧЕМ. Окно №14 показало разрыв: `--xray` находит край (kern_len_xs = 0,
period = 0), а реплей подавал норму ([1.0, 2.0, 3.0]) и не мог воспроизвести
путь падения — 43 находки ушли в OTHER не потому, что Z3 наврал, а потому
что харнесс выбросил сам контрпример.

КОНТРАКТ МОДУЛЯ:
    build(model, params, kinds) -> dict аргументов СТРОГО легальных типов;
    run(finding) -> (verdict, detail), где verdict ∈
        CONFIRMED       легальные типы + ровно обещанный класс исключения;
        GUARDED_RAISE   функция штатно отвергла вход (ValueError и т.п.);
        SURVIVED        вызов отработал без падения;
        NOT_REPLAYABLE  легальный вход построить нельзя (внешний тип).

ЗАКОН ЛЕГАЛЬНОСТИ (урок finta.PSAR): `None` вместо коллекции/DataFrame —
нарушение контракта типа, а не край. Пустая коллекция, ряд длины 0/1 и
плоский ряд (high == low) — законные краевые данные предметной области.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import io
import json
import re
import sys
from pathlib import Path

WANT = {"div0": "ZeroDivisionError", "bounds": "IndexError",
        "none_attr": "AttributeError", "none_type": "TypeError"}

LINE_CRASH = re.compile(
    r"^(.*?):\s*\[(CRASH|BOUNDS) PATH\]\s+(\w+):\s+строка\s+(\d+)\s+—\s+(.*)$")
LINE_CRASH_BARE = re.compile(
    r"^\s*\[(CRASH|BOUNDS) PATH\]\s+(\w+):\s+строка\s+(\d+)\s+—\s+(.*)$")
LINE_BOUNDS_BARE = re.compile(
    r"^\s*\[BOUNDS PATH\]\s+(\w+):\s+`(.*?)`\s+\(строка\s+(\d+)\)\s+—\s+(.*)$")
LINE_BOUNDS = re.compile(
    r"^(.*?):\s*\[BOUNDS PATH\]\s+(\w+):\s+`(.*?)`\s+\(строка\s+(\d+)\)\s+—\s+(.*)$")
MODEL = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(-?\d+)")


def parse_findings(text: str, default_path: str = "") -> list:
    """Строки `--xray` -> [{'path','kind','fn','line','text','model'}] (без дублей)."""
    out, seen = [], set()
    for raw in text.splitlines():
        raw = raw.strip()
        m = LINE_CRASH.match(raw)
        if m:
            path, cls, fn, line, text = m.groups()
        else:
            m = LINE_BOUNDS.match(raw)
            if m:
                path, fn, _expr, line, text = m.groups()
                cls = "BOUNDS"
            else:
                mb = LINE_BOUNDS_BARE.match(raw)
                if mb:
                    fn, _expr, line, text = mb.groups()
                    path, cls = default_path, "BOUNDS"
                else:
                    mb = LINE_CRASH_BARE.match(raw)
                    if not mb:
                        continue
                    cls, fn, line, text = mb.groups()
                    path = default_path
        if cls == "BOUNDS":
            kind = "bounds"
        elif "деление на ноль" in text:
            kind = "div0"
        elif "разыменование None" in text:
            kind = "none_attr" if "AttributeError" in text else "none_type"
        else:
            kind = "other"
        model = {}
        if "КОНТРПРИМЕР" in text:
            body = text.split("КОНТРПРИМЕР", 1)[1]
            model = {k: int(v) for k, v in MODEL.findall(body)}
        key = (path.strip(), fn, int(line), kind)
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": path.strip(), "kind": kind, "fn": fn,
                    "line": int(line), "text": text, "model": model})
    return out

DICT_METHODS = ("get", "items", "keys", "values", "setdefault", "popitem")
ITER_CALLS = ("len", "max", "min", "sum", "sorted", "list", "set", "tuple", "iter", "next")


def _container_role(node, name):
    """Чем параметр является в теле: 'dict' | 'seq' | '' (роль не видна)."""
    role = ""
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                and sub.value.id == name and sub.attr in DICT_METHODS):
            return "dict"
        if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                and sub.value.id == name
                and sub.attr in ("shape", "ndim", "dtype", "astype", "size", "reshape")):
            # ОКНО №38: доступ к массивному атрибуту — это ndarray, а не список
            # (урок resampler.py: `.shape` проверяется в хелпере, tb=9).
            return "ndarray"
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id in ITER_CALLS
                and any(isinstance(a, ast.Name) and a.id == name for a in sub.args)):
            role = "seq"
        if (isinstance(sub, (ast.For, ast.comprehension))
                and isinstance(sub.iter, ast.Name) and sub.iter.id == name):
            role = "seq"
        if (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name)
                and sub.value.id == name):
            role = "seq"
    return role


FILL = {"str": "abc", "int": 3, "float": 1.5, "bool": True,
        "list": [1.0, 2.0, 3.0], "dict": {"a": 1}, "tuple": (1, 2)}
OHLC = ("open", "high", "low", "close", "volume")


def load_target(path):
    """Импорт мишени как части её пакета (относительные импорты иначе падают)."""
    p = Path(path).resolve()
    parts, cur = [p.stem], p.parent
    while (cur / "__init__.py").exists():
        parts.insert(0, cur.name)
        cur = cur.parent
    if str(cur) not in sys.path:
        sys.path.insert(0, str(cur))
    dotted = ".".join(parts)
    # КЭШ МОДУЛЕЙ (найдено в Окне №18): два разных `guard_target.py` из разных
    # temp-каталогов получали имя одно и то же -> второй вызов видел ПЕРВЫЙ
    # файл, резолвер не находил тело и отдавал NOT_REPLAYABLE. Сбрасываем.
    for _k in [k for k in sys.modules if k == dotted or k.startswith(dotted + ".")]:
        sys.modules.pop(_k, None)
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        return importlib.import_module(dotted)
    except Exception:
        return None
    finally:
        sys.stdout = old


def _series_maker():
    try:
        import pandas as pd
        return pd
    except Exception:
        return None


def frame(k: int, flat: bool = False):
    """OHLC длины k. flat=True — нулевая волатильность (high == low)."""
    pd = _series_maker()
    if pd is None:
        return None
    if flat:
        base = [10.0] * k
        return pd.DataFrame({c: list(base) for c in OHLC})
    return pd.DataFrame({
        "open": [1.0 + i for i in range(k)],
        "high": [2.0 + i for i in range(k)],
        "low": [0.5 + i for i in range(k)],
        "close": [1.5 + i for i in range(k)],
        "volume": [10.0 + i for i in range(k)]})


def _by_ann(name, ann, k, flat):
    """Легальное значение ровно длины k по аннотации (None = не знаем тип)."""
    a = ann or ""
    # ОКНО №36: научные и финансовые пакеты принимают массивы и Decimal —
    # без этого десятки кандидатов уходили в NOT_REPLAYABLE.
    if "ndarray" in a or "NDArray" in a or "np." in a or name in ("arr", "xs", "values") and "numpy" in a:
        try:
            import numpy as np
            return np.full(k, 10.0) if flat else np.zeros(k, dtype=float)
        except Exception:
            return None
    if "Decimal" in a:
        try:
            from decimal import Decimal
            return Decimal("0") if k == 0 else (Decimal("10") if flat else Decimal("1"))
        except Exception:
            return None
    if "Fraction" in a:
        try:
            from fractions import Fraction
            return Fraction(0) if k == 0 else Fraction(1)
        except Exception:
            return None
    if "DataFrame" in a or name in ("ohlc", "df", "data") and "Series" in a:
        return frame(k, flat)
    if "Series" in a:
        pd = _series_maker()
        return None if pd is None else pd.Series([10.0 if flat else 1.0 + i for i in range(k)])
    if a.startswith("str") or "str" in a:
        return "a" * k
    if "tuple" in a or "Tuple" in a:
        return tuple([1] * k)
    if "dict" in a or "Dict" in a:
        return {i: 1 for i in range(k)}
    if "list" in a or "List" in a or "Sequence" in a or "ndarray" in a:
        return [10.0] * k if flat else [1.0 + i for i in range(k)]
    return None


def build(finding, sig, flat=False, force_empty=False):
    """Аргументы из модели Z3. Возврат: (kwargs, blocked) — blocked = нелегальные."""
    if isinstance(sig, dict):          # Окно №23: нужен и AST-узел тела
        sig_node = sig
        names, anns, defs = sig["names"], sig["anns"], sig["defs"]
    else:
        sig_node, (names, anns, defs) = None, sig
    model = dict(finding.get("model") or {})
    hint = ""
    m = re.search(r":\s*(\w+)\s*==\s*0", finding["text"])
    if m:
        hint = m.group(1)
    out, blocked = {}, []
    for n in names:
        k = model.get("kern_len_" + n)
        if k is not None:
            k = 0 if force_empty else max(int(k), 0)
            v = _by_ann(n, anns.get(n), k, flat)
            if v is None:
                # символическая длина в модели => это последовательность:
                # список длины k легален и без аннотации.
                v = [10.0] * k if flat else [1.0 + i for i in range(k)]
            out[n] = v
            continue
        ann = anns.get(n, "")
        # ЗАКОН ЛЕГАЛЬНОСТИ: `ohlc = 0` из модели НЕ заменяет DataFrame —
        # скаляр вместо коллекции нарушает контракт типа (урок finta.PSAR).
        if "DataFrame" in ann or "Series" in ann:
            k0 = model.get("kern_len_" + n, 5)
            v = _by_ann(n, ann, max(int(k0), 0), flat)
            if v is None:
                blocked.append(n + "(frame)")
            else:
                out[n] = v
            continue
        if not ann:
            role = _container_role(sig_node.get("node"), n) if sig_node else ""
            if role == "dict":
                out[n] = {}
                continue
            if role == "seq":
                out[n] = []
                continue
            if role == "ndarray":
                v = _by_ann(n, "ndarray", 3, flat)
                if v is None:
                    blocked.append(n + "(ndarray)")
                    continue
                out[n] = v
                continue
        # КЛАСС в аннотации (например `_ParsingState`) нельзя заменить нулём:
        # скаляр вместо объекта даёт ложный CONFIRMED (случай click._match_short_opt).
        _root = (ann.split("[")[0] or "").strip().lstrip("_")
        if (_root and _root[0].isupper()
                and _root not in ("DataFrame", "Series")
                and not any(k in ann for k in ("List", "Dict", "Tuple", "Optional"))):
            blocked.append(n + "(" + _root + ")")
            continue
        if n in model:
            v = int(model[n])
            out[n] = float(v) if "float" in ann else v
            continue
        if n == hint:
            out[n] = 0.0 if "float" in ann else 0
            continue
        root = (ann.split("[")[0] or "").strip()
        # Окно №31: аннотация вида `_ParsingState` (свой класс) — НЕ повод
        # подставлять 0. Скаляр вместо объекта класса даёт ложный CONFIRMED
        # (ровно случай click._match_short_opt). Честный отказ важнее трофея.
        if root in FILL:
            out[n] = FILL[root]
        elif n in defs and defs[n] == "None":
            # `x=None` в сигнатуре — это и есть законный край для nullable:
            # подача None НЕ нарушает контракт типа (в отличие от коллекции).
            out[n] = None
        else:
            out[n] = 0
    return out, blocked


def signature(path, fn, line):
    """Строгая привязка находки к ФИЗИЧЕСКОМУ телу: (qualname, lineno, end_lineno, args).
    ЗАЧЕМ. Окно №15 дало ложный CONFIRMED на finta.PSAR: `getattr` по классам
    находил ОДНОИМЁННЫЙ объект, не тот, что на строке находки. Теперь побеждает
    только определение, в чей диапазон строк реально попадает `line`.
    """
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    best = None

    def walk(node, stack):
        nonlocal best
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = stack + [child.name]
                if (isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == fn and child.lineno <= line
                        and (getattr(child, "end_lineno", child.lineno) or child.lineno) >= line):
                    cand = (".".join(inner), child)
                    if best is None or child.lineno > best[1].lineno:
                        best = cand
                walk(child, inner)
            else:
                walk(child, stack)

    walk(tree, [])
    if best is None:
        return None
    qual, node = best
    a = node.args
    names = [x.arg for x in a.args if x.arg not in ("self", "cls")]
    anns = {x.arg: ast.unparse(x.annotation)
            for x in a.args if x.annotation is not None}
    nd = len(a.defaults)
    defs = {}
    if nd:
        for x, d in zip(a.args[len(a.args) - nd:], a.defaults):
            defs[x.arg] = ast.unparse(d)
    deco = {ast.unparse(d).split("(")[0].strip().split(".")[-1]
            for d in node.decorator_list}
    first = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return {"qualname": qual, "lineno": node.lineno, "first_lineno": first,
            "node": node,
            "end_lineno": getattr(node, "end_lineno", node.lineno) or node.lineno,
            "names": names, "anns": anns, "defs": defs,
            "static": "staticmethod" in deco, "classm": "classmethod" in deco}


def resolve(mod, sig):
    """Объект по qualname + ЗАМОК подлинности: co_firstlineno == def_lineno."""
    obj, owner = mod, None
    for part in sig["qualname"].split("."):
        owner, obj = obj, getattr(obj, part, None)
        if obj is None:
            return None, "no_attr:%s" % part
    target = inspect.unwrap(obj)
    code = getattr(target, "__code__", None)
    # co_firstlineno у декорированной функции указывает на ПЕРВЫЙ декоратор,
    # у AST — на `def`; допускаем обе границы, но не чужое тело.
    if code is not None and code.co_firstlineno not in (sig["lineno"], sig["first_lineno"]):
        return None, "foreign:%s@%d!=%d" % (sig["qualname"],
                                            code.co_firstlineno, sig["first_lineno"])
    if owner is not None and isinstance(owner, type) and not sig["static"]             and not sig["classm"]:
        try:
            inst = owner()
        except Exception:
            return None, "no_instance:%s" % sig["qualname"]
        obj = getattr(inst, sig["qualname"].split(".")[-1])
    return obj, ""


ART_MSGS = ("is not iterable", "is not subscriptable", "has no len()",
            "object is not", "cannot be interpreted as an integer",
            "unsupported operand type", "not supported between instances")


def _is_type_artifact(got, msg, kwargs):
    """Скаляр int/float на месте контейнера — артефакт конструктора, не баг мишени."""
    if got not in ("TypeError", "AttributeError"):
        return False
    if not any(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in kwargs.values()):
        return False
    return any(m in (msg or "") for m in ART_MSGS)


def invoke(obj, kwargs, target=""):
    """Вызов + (тип, строка, кадров В ЦЕЛИ, текст исключения).

    ЗАМОК ПОДЛИННОСТИ №2: исключение, поднятое ДО входа в тело мишени (или
    глубоко в pandas), не доказывает найденный путь падения. Требуем хотя бы
    один кадр стека с именем целевого файла.
    """
    if obj is None:
        return "NO_FUNCTION", 0, 0, ""
    want_fn = (target or {}).get("fn") if isinstance(target, dict) else ""
    lo = (target or {}).get("lineno", 0) if isinstance(target, dict) else 0
    hi = (target or {}).get("end_lineno", 0) if isinstance(target, dict) else 0
    target = (target or {}).get("path", "") if isinstance(target, dict) else (target or "")
    name = Path(target).name if target else ""
    try:
        res = obj(**kwargs)
        if inspect.isgenerator(res):
            for _ in res:
                pass
        return "SURVIVED", 0, 0, ""
    except Exception as exc:
        tb = exc.__traceback__
        line, inside = 0, 0
        while tb is not None:
            code = tb.tb_frame.f_code
            if (name and Path(code.co_filename).name == name
                    and code.co_name == want_fn and lo <= tb.tb_lineno <= hi):
                line = tb.tb_lineno
                inside += 1
            tb = tb.tb_next
        return type(exc).__name__, line, inside, str(exc)


def replay_one(finding, mod, sig):
    """(verdict, detail) с ТОЧНЫМ репродьюсером для каждой CONFIRMED."""
    want = WANT.get(finding["kind"], "")
    if mod is None:
        return "NOT_REPLAYABLE", "import_failed"
    if sig is None:
        return "NOT_REPLAYABLE", "no_body_on_line"
    obj, err = resolve(mod, sig)
    if obj is None:
        return "NOT_REPLAYABLE", err
    # ЗАМОК 4 (Окно №28): нет края из Z3 — нет трофея. Шаблонные 'abc'/{'a':1}
    # дают падения, которые к делу не относятся. 0-аргументные вызовы и модели
    # с kern_len_*/len_self (boltons IndexedSet.pop) остаются законными.
    model = finding.get("model") or {}
    _hint = re.search(r":\s*(\w+)\s*==\s*0", finding["text"])
    _edge_from_text = bool(_hint and _hint.group(1) in sig["names"])
    # Только для div0/bounds край обязан приходить ИЗ МОДЕЛИ. Для None-края
    # законный вход даёт сам nullable-дефолт (`x=None`), модель не нужна.
    if (finding["kind"] in ("div0", "bounds")
            and sig["names"] and not model and not _edge_from_text):
        return "NO_Z3_EDGE", "модель Z3 пуста — вход шаблонный"
    tried, blocked = [], []
    for flat, empty in ((False, False), (True, False), (False, True)):
        kwargs, blk = build(finding, sig, flat=flat, force_empty=empty)
        blocked += [x for x in blk if x not in blocked]
        if blk:
            continue
        tried.append(kwargs)
        got, tb_line, inside, msg = invoke(obj, kwargs, {"path": finding["path"], "fn": finding["fn"], "lineno": sig["lineno"], "end_lineno": sig["end_lineno"]})
        if _is_type_artifact(got, msg, kwargs):
            return "TYPE_ARTIFACT", "%s kwargs=%s: %s" % (
                sig["qualname"], _short(kwargs), msg[:60])
        if got == want and inside >= 1:
            # ЗАМОК 3 (Окно №28): падение должно быть РЯДОМ со строкой находки,
            # иначе одно падение размножается на все ветки функции.
            if tb_line and abs(tb_line - finding["line"]) > 5:
                return "BRANCH_MISMATCH", "tb=%d vs line=%d" % (tb_line, finding["line"])
            return "CONFIRMED", "%s kwargs=%s tb=%d" % (
                sig["qualname"], _short(kwargs), tb_line)
    if not tried:
        return "NOT_REPLAYABLE", "needs " + ",".join(blocked)
    got, tb_line, inside, msg = invoke(obj, tried[0], {"path": finding["path"], "fn": finding["fn"], "lineno": sig["lineno"], "end_lineno": sig["end_lineno"]})
    if _is_type_artifact(got, msg, tried[0]):
        return "TYPE_ARTIFACT", "%s kwargs=%s: %s" % (
            sig["qualname"], _short(tried[0]), msg[:60])
    if got in ("NO_FUNCTION",):
        return "NOT_REPLAYABLE", got
    if got == "ValueError":
        return "GUARDED_RAISE", "ValueError tb=%d" % tb_line
    if got == "SURVIVED":
        return "SURVIVED", "no exception"
    return "OTHER:" + str(got), "%s tb=%d kwargs=%s" % (got, tb_line, _short(tried[0]))


def _short(kwargs, limit=90):
    parts = []
    for k, v in kwargs.items():
        if hasattr(v, "shape"):
            parts.append("%s=<%s %s>" % (k, type(v).__name__, getattr(v, "shape", "")))
        else:
            parts.append("%s=%r" % (k, v if not hasattr(v, "__len__") or len(str(v)) < 24
                                    else type(v).__name__ + "(%d)" % len(v)))
    txt = ", ".join(parts)
    return txt if len(txt) <= limit else txt[:limit] + "..."


def run_all(findings, stats_only=False):
    """Прогон всех находок: список вердиктов + сводка по пакетам/классам."""
    rows, mods = [], {}
    for f in findings:
        path = f["path"]
        if path not in mods:
            mods[path] = load_target(path)
        sig = signature(path, f["fn"], f["line"])
        verdict, detail = replay_one(f, mods[path], sig)
        rows.append(dict(f, verdict=verdict, detail=detail,
                         want=WANT.get(f["kind"], "")))
    if stats_only:
        from collections import Counter
        for key, n in sorted(Counter((r["kind"], r["verdict"]) for r in rows).items()):
            print("%-8s %-14s %d" % (key[0], key[1], n))
    return rows


FIXTURES = {
    "div0.py": "def f(period=5):\n    return 100 / period\n",
    "bounds.py": "def g(xs):\n    return xs[0]\n",
    "guarded.py": "def h(xs):\n    if not xs:\n        raise ValueError(\"empty\")\n    return xs[0]\n",
    "never_none.py": "def m(xs=None):\n    if xs is None:\n        raise TypeError(\"no none\")\n    return len(xs)\n",
    "ok.py": "def s(x):\n    return x + 1\n",
    "collect.py": "def f(xs):\n    return max(xs)\n",
}


CASES = [
    ("div0.py", "f", "возможно деление на ноль: period == 0", {}, "CONFIRMED"),
    ("bounds.py", "g", "возможен выход за границы", {'kern_len_xs': 0}, "CONFIRMED"),
    ("guarded.py", "h", "возможен выход за границы", {'kern_len_xs': 0}, "GUARDED_RAISE"),
    ("never_none.py", "m", "возможен выход за границы", {'kern_len_xs': 0}, "SURVIVED"),
    ("ok.py", "s", "возможно деление на ноль: x == 0", {'x': 0}, "SURVIVED"),
    ("collect.py", "f", "возможен выход за границы", {'xs': 0}, "GUARDED_RAISE"),
    ("collect.py", "f", "возможен выход за границы", {'kern_len_xs': 0}, "GUARDED_RAISE"),
]

NL = chr(10)


GHOSTS = {
    "ghost.py": NL.join(["class A:", "    @staticmethod", "    def PSAR(ohlc):",
                             "        return ohlc[0]", "", "",
                             "def PSAR(ohlc):", "    return 1", ""]),
    "klass.py": NL.join(["class Box:", "    def __init__(self):",
                             "        self.items = []", "",
                             "    def pop(self):", "        return self.items.pop()", ""]),
}


def selftest_resolver(work):
    """Три замка Окна №16: свой qualname, чужой qualname, метод экземпляра."""
    bad = 0
    for name, src in GHOSTS.items():
        (work / name).write_text(src, encoding="utf-8")
    cases = [
        ("ghost.py", "PSAR", 4, {"kern_len_ohlc": 0}, "CONFIRMED"),
        ("ghost.py", "PSAR", 9, {"kern_len_ohlc": 0}, "NOT_REPLAYABLE"),
        ("klass.py", "pop", 6, {"kern_len_items": 0}, "CONFIRMED"),
    ]
    for name, fn, line, model, want in cases:
        f = {"path": str(work / name), "kind": "bounds", "fn": fn,
             "line": line, "text": "возможен выход за границы", "model": model}
        verdict, detail = replay_one(f, load_target(f["path"]),
                                     signature(f["path"], fn, line))
        if verdict != want:
            print("[FAIL] resolver %-11s %-5s L%d -> %s (%s), ожидалось %s"
                  % (name, fn, line, verdict, detail, want))
            bad += 1
        else:
            print("[OK] resolver %-11s %-5s L%d -> %s" % (name, fn, line, verdict))
    return bad


def selftest():
    """5 точек: край из модели, закон легальности типа, штатный отказ, норма."""
    import tempfile
    work = Path(tempfile.mkdtemp(prefix="kern_replay_"))
    for name, src in FIXTURES.items():
        (work / name).write_text(src, encoding="utf-8")
    bad = 0
    bad += selftest_resolver(work)
    for name, fn, text, model, want in CASES:
        f = {"path": str(work / name), "kind": ("div0" if "деление" in text else "bounds"),
             "fn": fn, "line": 1, "text": text, "model": model}
        mod = load_target(f["path"])
        verdict, detail = replay_one(f, mod, signature(f["path"], fn, 1))
        if verdict != want:
            print("[FAIL] %-14s %-4s -> %s (%s), ожидалось %s" % (name, fn, verdict, detail, want))
            bad += 1
        else:
            print("[OK] %-14s %-4s -> %s" % (name, fn, verdict))
    print("[LIVE-REPLAY-SELFTEST] точек %d | провалов %d" % (len(CASES) + 3, bad))
    return 0 if bad == 0 else 1


def scan(target):
    """ЖИВОЙ скан исходника: `--xray` (div0/bounds) + `--xray-none` (None).

    В отличие от `collect` (разбор ГОТОВОГО отчёта), здесь kern_contracts
    запускается по файлу мишени, а находки дедуплицируются по (fn, line, kind).
    """
    import subprocess
    here = Path(__file__).resolve().parent / "kern_contracts.py"
    found, seen = [], set()
    for flag in ("--xray", "--xray-none"):
        proc = subprocess.run([sys.executable, str(here), flag, str(target)],
                              capture_output=True, text=True)
        for f in parse_findings(proc.stdout + chr(10) + proc.stderr,
                                default_path=str(target)):
            key = (f["fn"], f["line"], f["kind"])
            if key not in seen:
                seen.add(key)
                found.append(f)
    return found


def collect(target):
    """Находки из файла отчёта или из живого `--xray <каталог|файл>`."""
    p = Path(target)
    if not p.is_dir():
        return parse_findings(p.read_text(encoding="utf-8", errors="replace"),
                              default_path=str(p))
    import subprocess
    here = Path(__file__).resolve().parent / "kern_contracts.py"
    proc = subprocess.run([sys.executable, str(here), "--xray", str(p)],
                          capture_output=True, text=True)
    return parse_findings(proc.stdout + NL + proc.stderr, default_path=str(p))


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Live Replay, ведомый моделью Z3")
    ap.add_argument("--findings", help="файл с выводом --xray")
    ap.add_argument("--dir", help="каталог/файл: находки собираются живым --xray")
    ap.add_argument("--json", help="куда записать вердикты (JSON)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    src = a.findings or a.dir
    if not src:
        ap.error("нужен --findings или --dir")
    rows = run_all(collect(src), stats_only=True)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    confirmed = [r for r in rows if r["verdict"] == "CONFIRMED"]
    for r in confirmed:
        print("[CONFIRMED] %s:%d %s (%s)" % (Path(r["path"]).name, r["line"],
                                             r["fn"], r["detail"]))
    print("[LIVE-REPLAY] находок %d | CONFIRMED %d" % (len(rows), len(confirmed)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
