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


# ========================================================================
# LAW derive-ord-mismatch (Rust): лексикографический порядок на числовом типе
# ========================================================================
# `#[derive(PartialOrd)]` над `struct Fraction { n, d }` сравнивает СНАЧАЛА `n`,
# потом `d`. Это порядок ПОЛЕЙ, а не чисел: (1,3) > (1,2), хотя 1/3 < 1/2.
# Компилятор молчит (синтаксис безупречен), rug/GMP не спасает (переполнения
# нет вовсе), и баг уходит в публичный API.
#
# ЧЕСТНЫЙ ФИЛЬТР (никаких обвинений Point{x,y} и Meter(i64)):
#   * есть derive(...PartialOrd...) либо derive(...Ord...);
#   * >= 2 полей числового типа;
#   * имена полей имеют МАТЕМАТИЧЕСКИЙ смысл дроби (num/den) или фиксированной
#     точки (mantissa/scale) — только для них лексикографика заведомо неверна;
#   * в файле есть нетривиальная алгебра (impl Add/Mul/Div) — иначе это пара
#     чисел без арифметики.
# Свидетели считаются ТОЧНО (fractions.Fraction), а не на глаз.

import re as _re
import tempfile as _tempfile

RUST_DERIVE_RE = _re.compile(
    r"#\[derive\((?P<derive>[^)]*)\)\]\s*(?:#\[[^\]]*\]\s*)*"
    r"(?:pub(?:\([^)]*\))?\s+)?struct\s+(?P<name>\w+)\s*\{(?P<body>[^}]*)\}", _re.S)
RUST_NUMERIC = ("i8", "i16", "i32", "i64", "i128", "isize",
                "u8", "u16", "u32", "u64", "u128", "usize", "f32", "f64")
# Произвольная точность: переполнения нет вовсе, но лексикографика так же неверна.
RUST_BIG = ("BigInt", "BigUint", "BigRational", "Int", "Integer", "Decimal", "Rational")
BIG_SCALARS = RUST_NUMERIC + RUST_BIG
FRAC_NUM = {"num", "n", "numerator", "numer", "nom"}
FRAC_DEN = {"den", "d", "denominator", "denom", "den_"}
DEC_MANT = {"mantissa", "mant", "unscaled", "coeff", "coefficient", "value"}
DEC_SCALE = {"scale", "exp", "exponent"}


def _rust_fields(body: str) -> list:
    """[(name, type)] из тела struct, только числовые поля."""
    out = []
    for line in body.split(","):
        part = line.split("//")[0].strip()
        m = _re.match(r"(?:pub\s+)?(\w+)\s*:\s*([\w:]+)", part)
        if m and m.group(2).split("::")[-1] in BIG_SCALARS:
            out.append((m.group(1), m.group(2).split("::")[-1]))
    return out


def _frac_witness():
    """(1,3) vs (1,2): по полям Greater, как дроби 1/3 < 1/2."""
    from fractions import Fraction as F
    a, b = (1, 3), (1, 2)
    lex = "Greater" if a > b else ("Less" if a < b else "Equal")
    va, vb = F(*a), F(*b)
    num = "Greater" if va > vb else ("Less" if va < vb else "Equal")
    return a, b, lex, num, va, vb


def _dec_witness():
    """(2,0) vs (100,2): по полям Less (2 < 100), как 2 vs 1.00 — Greater."""
    from fractions import Fraction as F
    a, b = (2, 0), (100, 2)
    lex = "Greater" if a > b else ("Less" if a < b else "Equal")
    va, vb = F(a[0], 10 ** a[1]), F(b[0], 10 ** b[1])
    num = "Greater" if va > vb else ("Less" if va < vb else "Equal")
    return a, b, lex, num, va, vb


def check_rust_derive_ord(src: str) -> list:
    """Находки derive-ord-mismatch в одном .rs файле."""
    out = []
    for m in RUST_DERIVE_RE.finditer(src):
        derive = m.group("derive")
        if "PartialOrd" not in derive and not _re.search(r"\bOrd\b", derive):
            continue
        name = m.group("name")
        fields = _rust_fields(m.group("body"))
        if len(fields) < 2:
            continue
        names = {f[0] for f in fields}
        has_alg = _re.search(r"impl\s+(?:Add|Sub|Mul|Div)\s*(?:<[^>]*>)?\s+for\s+"
                            + _re.escape(name) + r"\b", src) is not None
        big = any(t in RUST_BIG for _, t in fields)
        if not has_alg and not big:
            continue
        if (names & FRAC_NUM) and (names & FRAC_DEN):
            a, b, lex, num, va, vb = _frac_witness()
            out.append({
                "symbol": name, "law": "derive-ord-mismatch",
                "detail": "lexicographic (n, d): %s > %s by fields, but %s < %s as fractions"
                          % (a, b, va, vb),
                "witness": {"a": a, "b": b, "derive_says": lex, "math_says": num},
            })
        elif (names & DEC_MANT) and (names & DEC_SCALE):
            a, b, lex, num, va, vb = _dec_witness()
            out.append({
                "symbol": name, "law": "derive-ord-mismatch",
                "detail": "lexicographic (mantissa, scale): %s vs %s is %s by fields, "
                          "but %s vs %s is %s as decimals" % (a, b, lex, va, vb, num),
                "witness": {"a": a, "b": b, "derive_says": lex, "math_says": num},
            })
    return out


def hunt_rust_tree(root: Path) -> dict:
    """.rs вне target/tests/examples: сколько проверено и что найдено."""
    checked = 0
    findings = []
    for p in sorted(Path(root).rglob("*.rs")):
        if set(p.parts) & {"target", "tests", "examples", "benches"}:
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        checked += 1
        for f in check_rust_derive_ord(src):
            f["file"] = str(p)
            findings.append(f)
    return {"root": str(root), "checked": checked, "findings": findings}


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
    broken_frac = '''
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Fraction { pub n: i64, pub d: i64 }
impl Add for Fraction {
    fn add(self, rhs: Self) -> Self {
        Fraction::new(self.n * rhs.d + rhs.n * self.d, self.d * rhs.d)
    }
}
'''
    broken_dec = '''
#[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
pub struct Decimal { pub mantissa: i64, pub scale: u8 }
impl Add for Decimal { fn add(self, o: Self) -> Self { self } }
'''
    good_newtype = '''
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Meter(i64);
'''
    good_money = '''
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Money { pub dollars: i64, pub cents: u8 }
impl Add for Money { fn add(self, o: Self) -> Self { self } }
'''
    good_manual = '''
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Fraction { pub n: i64, pub d: i64 }
impl Add for Fraction { fn add(self, o: Self) -> Self { self } }
impl PartialOrd for Fraction {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        ((self.n as i128) * (o.d as i128)).partial_cmp(&((o.n as i128) * (self.d as i128)))
    }
}
'''
    f1 = check_rust_derive_ord(broken_frac)
    f2 = check_rust_derive_ord(broken_dec)
    ok(len(f1) == 1 and f1[0]["witness"]["derive_says"] == "Greater"
       and f1[0]["witness"]["math_says"] == "Less",
       "derive-ord: Fraction{n,d} пойман (1/3 > 1/2 по полям)")
    ok(len(f2) == 1 and f2[0]["witness"]["derive_says"] == "Less"
       and f2[0]["witness"]["math_says"] == "Greater",
       "derive-ord: Decimal{mantissa,scale} пойман (2 vs 1.00)")
    ok(check_rust_derive_ord(good_newtype) == [], "derive-ord: newtype Meter(i64) молчит")
    ok(check_rust_derive_ord(good_money) == [], "derive-ord: Money{dollars,cents} молчит")
    ok(check_rust_derive_ord(good_manual) == [], "derive-ord: ручной i128 PartialOrd молчит")
    w2 = Path(_tempfile.mkdtemp())
    (w2 / "a.rs").write_text(broken_frac, encoding="utf-8")
    (w2 / "b.rs").write_text(good_money, encoding="utf-8")
    big_rat = '''
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Rational { pub numerator: BigInt, pub denominator: BigInt }
'''
    f3 = check_rust_derive_ord(big_rat)
    ok(len(f3) == 1 and f3[0]["witness"]["derive_says"] == "Greater"
       and f3[0]["witness"]["math_says"] == "Less",
       "derive-ord: Rational{numerator: BigInt, denominator: BigInt} без impl Add пойман")
    r2 = hunt_rust_tree(w2)
    ok(r2["checked"] == 2 and len(r2["findings"]) == 1,
       "derive-ord: hunt_rust_tree — 2 файла, 1 находка")

    print("[LAW-HUNTER-SELFTEST] провалов: %d" % bad)
    return 0 if bad == 0 else 1


def main(argv) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="law_hunter: тихие математические баги")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--package", help="каталог пакета (с __init__.py)")
    ap.add_argument("--rust", help="каталог с .rs: закон derive-ord-mismatch")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.rust:
        res = hunt_rust_tree(Path(a.rust))
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        else:
            print("%s: проверено %d .rs, находок %d"
                  % (res["root"], res["checked"], len(res["findings"])))
            for f in res["findings"]:
                print("  [LAW] %s :: %s" % (f["symbol"], f["detail"]))
        return 0
    if not a.package:
        ap.error("нужен --package, --rust или --selftest")
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
