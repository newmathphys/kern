#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""law_hunter: ТИХИЕ математические и денежные баги на ПУБЛИЧНОМ API.

ЧЕМ ОТЛИЧАЕТСЯ ОТ --xray. `--xray` ищет падения (div0, bounds, None). Зрелые
библиотеки их закрывают. Но функция может НЕ падать и молча вернуть НЕВЕРНОЕ
число: потерянный цент при разбиении суммы, `lcm(50000,50000) == -35899`,
`clamp`, вылезший за границу. Ровно на этом KERN ловил апстрим-баги.

ЖЕЛЕЗНЫЙ ФИЛЬТР ПУБЛИЧНОСТИ (урок `stftPitchShift`). Функция без ведущего `_`
— ещё НЕ публичный API. Кандидат рассматривается, только если имя реально
экспортируется корнем пакета (`__init__.py`: `__all__` либо `from .mod import name`).
Внутренний `resampler.linear` проваливает этот фильтр и не становится трофеем.

ЗАКОНЫ (каждый проверяется против ТОЧНОЙ арифметики Python, не эвристикой):
  * split   — sum(parts) == total на любых неделимых остатках;
  * clamp   — lo <= f(x, lo, hi) <= hi при lo <= hi и идемпотентность.

Находка обязана быть воспроизводима одной строкой публичного импорта.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

CLAMP_NAMES = ("clamp", "clip", "bound", "saturate")
SPLIT_NAMES = ("allocate", "allocate_split", "distribute", "split_amount", "split")
MONEY_ARGS = ((0, [1, 1, 1]), (1, [1, 1, 1]), (100, [1, 1, 1]), (1, [1, 2, 3]),
              (0, [0, 1]), (-1, [1, 1]))
CLAMP_CASES = ((5, 0, 3), (0, 0, 3), (3, 0, 3), (-7, -5, 5), (10, -5, 5))
# Известные «контрактные» имена Money-объектов: если сумма не приводится к числу,
# закон не применяется (честно молчим, а не обвиняем).
CONTRACT_TYPE = object


def exported_names(init_py: Path) -> set:
    """Имена, реально доступные из корня пакета (__all__ либо `from .m import n`)."""
    try:
        tree = ast.parse(Path(init_py).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    try:
                        names |= {str(x) for x in ast.literal_eval(node.value)}
                    except (ValueError, SyntaxError):
                        pass
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def _call(fn, *args):
    try:
        return fn(*args), None
    except Exception as exc:          # падение — не наш класс (это --xray)
        return None, type(exc).__name__


def check_clamp(fn) -> list:
    """Закон зажима: границы + идемпотентность. Возвращает находки."""
    out = []
    for x, lo, hi in CLAMP_CASES:
        got, err = _call(fn, x, lo, hi)
        if err or got is None:
            continue
        if not (lo <= got <= hi):
            out.append("clamp(%r, %r, %r) = %r вне [%r, %r]" % (x, lo, hi, got, lo, hi))
            continue
        again, err2 = _call(fn, got, lo, hi)
        if not err2 and again != got:
            out.append("clamp(clamp(%r)) = %r != %r (идемпотентность)" % (x, again, got))
    return out


def check_split(fn) -> list:
    """Закон сохранения денег: sum(parts) == total."""
    out = []
    for total, weights in MONEY_ARGS:
        got, err = _call(fn, total, weights)
        if err or got is None:
            continue
        try:
            parts = [int(p) for p in got]        # цент-целые части
        except (TypeError, ValueError):
            continue                              # Money-объекты: закон не применяем
        if sum(parts) != total:
            out.append("split(%r, %r) -> %r, сумма %d != %d (потеря/рождение цента)"
                       % (total, weights, got, sum(parts), total))
    return out


def hunt_symbol(name: str, fn) -> list:
    low = name.lower()
    if any(k in low for k in CLAMP_NAMES):
        return check_clamp(fn)
    if any(low.startswith(k) for k in SPLIT_NAMES):
        return check_split(fn)
    return []


def hunt_package(pkg_dir: Path, pkg_name: str) -> dict:
    """Проверить только ПУБЛИЧНЫЕ символы корня пакета."""
    import importlib
    import sys
    init = Path(pkg_dir) / "__init__.py"
    if not init.exists():
        return {"pkg": pkg_name, "checked": 0, "findings": [], "reason": "no __init__.py"}
    pub = exported_names(init)
    sys.path.insert(0, str(Path(pkg_dir).parent))
    try:
        mod = importlib.import_module(pkg_name)
    except Exception as exc:
        return {"pkg": pkg_name, "checked": 0, "findings": [],
                "reason": "import_failed: %s" % type(exc).__name__}
    checked, findings = 0, []
    for name in sorted(pub):
        fn = getattr(mod, name, None)
        if fn is None or not callable(fn):
            continue
        if inspect.isclass(fn):
            # ОКНО №42: деньги живут в МЕТОДАХ экспортируемого класса.
            hits = check_money_class(fn)
            if hits:
                checked += 1
                findings += [{"symbol": "%s.%s" % (pkg_name, name), "law": h} for h in hits]
            continue
        hits = hunt_symbol(name, fn)
        if hits:
            checked += 1
            findings += [{"symbol": "%s.%s" % (pkg_name, name), "law": h} for h in hits]
    return {"pkg": pkg_name, "checked": checked, "findings": findings, "reason": ""}


# ── ЗАКОН ДЕНЕГ ДЛЯ КЛАССОВ (Окно №42) ───────────────────────────────────────
# В py-moneyed / carlospalol/money сплит живёт в МЕТОДЕ экспортируемого класса:
#   Money("0.01", "USD").allocate([1, 1, 1])
# Свободной функции над int там нет, поэтому без этой ветки рейд даёт 0.
MONEY_METHODS = ("allocate", "split", "distribute", "divide")
MONEY_SUMS = ("0.00", "0.01", "-0.01", "-1.00", "1.00", "-0.05", "100.00")
MONEY_WEIGHTS = ([1, 1, 1], [1, 2, 3], [0, 1], [1, 0, 1])


def _money_amount(obj):
    """Сумма как Decimal; None, если объект не про деньги (честно молчим)."""
    from decimal import Decimal, InvalidOperation
    val = getattr(obj, "amount", obj)
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return None


def check_money_class(cls) -> list:
    """Инвариант Фаулера: sum(parts) == total, включая отрицательные суммы."""
    from decimal import Decimal
    out = []
    methods = [m for m in MONEY_METHODS if callable(getattr(cls, m, None))]
    if not methods:
        return out
    for text in MONEY_SUMS:
        try:
            money = cls(text, "USD")
        except Exception:
            try:
                money = cls(text)
            except Exception:
                return out            # конструктор не наш случай — не обвиняем
        total = _money_amount(money)
        if total is None:
            return out
        for mname in methods:
            for weights in MONEY_WEIGHTS:
                try:
                    parts = getattr(cls, mname)(money, weights)
                    parts = list(parts)
                except Exception:
                    continue          # падение — класс --xray, не наш
                amounts = [_money_amount(p) for p in parts]
                if any(a is None for a in amounts):
                    continue
                got = sum(amounts, Decimal(0))
                if got != total:
                    out.append(
                        "%s(%r).%s(%r) -> %s, сумма %s != %s (потеря/рождение цента)"
                        % (cls.__name__, text, mname, weights,
                           [str(a) for a in amounts], got, total))
                    continue
                # ОКНО №43: ИНВАРИАНТ ЗНАКА. На долге (-0.01) реализация может
                # вернуть [+0.01, -0.01, -0.01]: сумма сходится, но у должника
                # появился положительный актив. При total<0 долей >0 быть не может.
                if total < 0 and any(a > 0 for a in amounts):
                    bad = [str(a) for a in amounts if a > 0]
                    out.append(
                        "%s(%r).%s(%r) -> %s: положительные доли %s при долге %s"
                        % (cls.__name__, text, mname, weights, bad, total))
                elif total > 0 and any(a < 0 for a in amounts):
                    bad = [str(a) for a in amounts if a < 0]
                    out.append(
                        "%s(%r).%s(%r) -> %s: отрицательные доли %s при сумме %s"
                        % (cls.__name__, text, mname, weights, bad, total))
    return out


def hunt_symbol(name: str, fn) -> list:
    low = name.lower()
    if any(k in low for k in CLAMP_NAMES):
        return check_clamp(fn)
    if any(low.startswith(k) for k in SPLIT_NAMES):
        return check_split(fn)
    return []


def selftest() -> int:
    bad = 0

    def ok(cond, label):
        nonlocal bad
        print(("[OK]   " if cond else "[FAIL] ") + label)
        if not cond:
            bad += 1

    def broken_clamp(x, lo, hi):
        return max(lo, x)                      # верхнюю границу забыли

    def good_clamp(x, lo, hi):
        return max(lo, min(x, hi))

    def bad_split(total, weights):
        return [total // len(weights)] * len(weights)

    def good_split(total, weights):
        s = sum(weights) or 1
        parts = [total * w // s for w in weights]
        parts[0] += total - sum(parts)
        return parts

    ok(len(check_clamp(broken_clamp)) > 0, "сломанный clamp пойман")
    ok(check_clamp(good_clamp) == [], "правильный clamp молчит")
    ok(len(check_split(bad_split)) > 0, "потерянный цент пойман")
    ok(check_split(good_split) == [], "точный split молчит")

    import tempfile
    w = Path(tempfile.mkdtemp())
    pkg = w / "fixtpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .impl import public_fn\n", encoding="utf-8")
    (pkg / "impl.py").write_text(
        "def public_fn():\n    return 1\n\n\ndef linear(x, factor):\n    return x\n",
        encoding="utf-8")
    pub = exported_names(pkg / "__init__.py")
    ok("public_fn" in pub and "linear" not in pub,
       "внутренний linear отвергнут фильтром __init__")
    print("[LAW-HUNTER-SELFTEST] провалов: %d" % bad)
    return 0 if bad == 0 else 1


def main(argv) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="law_hunter: тихие математические баги")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--package", help="каталог пакета (с __init__.py)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.package:
        ap.error("нужен --package или --selftest")
    p = Path(a.package)
    res = hunt_package(p, p.name)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print("%s: проверено %d, находок %d %s"
              % (res["pkg"], res["checked"], len(res["findings"]), res["reason"]))
    for f in res["findings"]:
        print("  [LAW] %s :: %s" % (f["symbol"], f["law"]))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
