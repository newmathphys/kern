#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: `--xray` против MBPP+ — ОРАКУЛ ЖИВОГО ЗАПУСКА PYTHON.

ГЛАВНАЯ ИДЕЯ. Считать `MBPP+` оракулом истинности для `[CRASH PATH]` НЕЛЬЗЯ:
`MBPP+` — это набор тестов, а тесты покрывают не всё. ИЗМЕРЕНО: 3 решения
прошли И базовый `MBPP`, И 80-кратный `MBPP+` (`pass/pass`), и при этом наш
`--xray` указал в них на деление на ноль, а ЖИВОЙ ЗАПУСК подтвердил
`ZeroDivisionError`:

    Mbpp/265  list_split(lst, n)              -> `n = 0`
    Mbpp/292  find(a, b)                      -> `b = 0`
    Mbpp/422  find_Average_Of_Cube(n)         -> `n = 0`

ПОЭТОМУ ОРАКУЛ — ИНТЕРПРЕТАТОР, А НЕ ТАБЛИЦА:

  * `[CRASH PATH]` — ОБВИНЕНИЕ, проверяется ЖИВЫМ вызовом функции на найденном
    контрпримере (нулевой делитель);
      - Python упал  -> `confirmed_blindspot` — НАСТОЯЩАЯ находка KERN в коде,
        прошедшем весь MBPP+ (слепое пятно самого бенчмарка);
      - Python НЕ упал -> `false_crash_accusation` — ЛОЖНОЕ обвинение,
        АБСОЛЮТНЫЙ провал гейта;
  * `[BOUNDS] … длина НЕ известна` — ИНФОРМАЦИОННАЯ строка («не смог
    проверить»), а НЕ обвинение.

ИСТОРИЯ (оба дефекта найдены ЭТИМ оракулом и закрыты):
  #377 — обвинение `arr[i % n]` внутри `for i in range(n * k)` было ЛОЖНЫМ:
    при `n == 0` граница равна нулю, `range(0)` пуст, тела нет. Закрыто гардом
    непустоты цикла (для произведения `A * B` — линейные `(distinct A 0)` и
    `(distinct B 0)` по свойству кольца целых).
  #378 — тело цикла было СЛЕПОЙ ЗОНОЙ: значения присваиваний (`x = …`,
    `x += …`) не проходили краш-обход вообще, поэтому настоящие обвинения в
    теле `for` не выдавались.

Запуск:  python3 tools/mbpp_xray_check.py [--selftest]
Код возврата: 0 — инварианты выполнены; 1 — нарушение; 2 — нет датасета (SKIP).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
KERN_CONTRACTS = ROOT / "tools" / "kern_contracts.py"
DATASET = ROOT / "evalplus_results" / "samples_mbpp_eval_results.json"

ACCUSATIONS = ("[CRASH PATH]", "[DEAD BRANCH]", "[REDUNDANT GUARD]")
EXPECTED_BLINDSPOTS = 3


def load_split() -> tuple[list, list]:
    d = json.loads(DATASET.read_text(encoding="utf-8"))
    bad, ok = [], []
    for lst in d["eval"].values():
        for e in lst:
            if e.get("base_status") != "pass":
                continue
            (ok if e.get("plus_status") == "pass" else bad).append(e)
    return bad, ok


def write_all(items: list, d: Path) -> None:
    for e in items:
        (d / f"{e['task_id'].replace('/', '_')}.py").write_text(
            e["solution"], encoding="utf-8")


def xray(directory: Path) -> dict:
    r = subprocess.run([PY, str(KERN_CONTRACTS), "--xray", str(directory)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=3600)
    out = r.stdout + r.stderr
    res: dict = {}
    for line in out.splitlines():
        m = re.search(r"/([A-Za-z0-9_.\-]+\.py):\s*\[([A-Z ]+)\]\s*(.*)", line)
        if not m:
            continue
        res.setdefault(m.group(1), []).append((f"[{m.group(2)}]", m.group(3).strip()))
    return res


def accusations(entries: list) -> list:
    return [e for e in entries if e[0] in ACCUSATIONS]


def parse_finding(text: str) -> tuple[str | None, str | None]:
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*):", text.strip())
    fn = m.group(1) if m else None
    m2 = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*==\s*0", text)
    return fn, (m2.group(1) if m2 else None)


def base_args(src: str, fn: str) -> tuple[list | None, list | None]:
    """Параметры функции и ПРИМЕРНЫЕ аргументы из `assert` в докстринге.

    Докстринг MBPP содержит `assert f(аргументы) == ожидание` — готовая
    КОРРЕКТНАЯ точка входа, поэтому контрпример подставляется в неё, а не
    выдумывается.
    """
    try:
        t = ast.parse(src)
    except SyntaxError:
        return None, None
    params, args = None, None
    for node in ast.walk(t):
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            params = [a.arg for a in node.args.args]
    doc = ast.get_docstring(t) or ""
    for line in doc.splitlines():
        s = line.strip()
        if not s.startswith("assert "):
            continue
        try:
            expr = ast.parse(s[len("assert "):].split("==")[0].strip()).body[0].value
        except SyntaxError:
            continue
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == fn:
            vals, ok = [], True
            for a in expr.args:
                try:
                    vals.append(ast.literal_eval(a))
                except (ValueError, SyntaxError):
                    ok = False
                    break
            if ok:
                args = vals
            break
    return params, args


def live_verify(path: Path, text: str) -> tuple[bool, str]:
    """ОРАКУЛ: живой вызов функции Python с нулевым делителем."""
    src = path.read_text(encoding="utf-8")
    fn, var = parse_finding(text)
    if fn is None or var is None:
        return False, "не разобрана находка"
    params, args = base_args(src, fn)
    if params is None or args is None:
        return False, "нет примера вызова в докстринге"
    if var not in params:
        return False, f"`{var}` не является параметром"
    if len(args) != len(params):
        args = (args + [0] * len(params))[: len(params)]
    args[params.index(var)] = 0
    code = ("import sys\n"
            f"sys.path.insert(0, {str(path.parent)!r})\n"
            f"import {path.stem} as m\n"
            f"m.{fn}(*{args!r})\n")
    try:
        r = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False, "таймаут"
    if r.returncode != 0:
        return True, (r.stderr.strip().splitlines() or ["?"])[-1][:80]
    return False, "не упал"


def collect() -> dict:
    bad, ok = load_split()
    rep: dict = {"bad_total": len(bad), "ok_total": len(ok),
                 "bad_crashes": 0, "blindspots": [], "false": [],
                 "informational": 0}
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        bd, od = base / "bad", base / "ok"
        bd.mkdir()
        od.mkdir()
        write_all(bad, bd)
        write_all(ok, od)
        bx, ox = xray(bd), xray(od)
        for _f, entries in bx.items():
            acc = accusations(entries)
            rep["bad_crashes"] += len(acc)
            rep["informational"] += len(entries) - len(acc)
        for f, entries in ox.items():
            acc = accusations(entries)
            rep["informational"] += len(entries) - len(acc)
            for _kind, text in acc:
                crashed, detail = live_verify(od / f, text)
                row = {"file": f, "task": f[:-3].replace("_", "/", 1),
                       "finding": text[:70], "detail": detail}
                (rep["blindspots"] if crashed else rep["false"]).append(row)
    return rep


def verdict(rep: dict) -> list[str]:
    """Список нарушений. Пустой = гейт зелёный.

    КРАСНИТ: ЛОЖНОЕ ОБВИНЕНИЕ (Python не упал) — абсолютное требование;
    НЕДОБОР СЛЕПЫХ ПЯТЕН (меньше ожидаемого — детектор ослеп); ВАКУУМ
    (обвинений не было вообще).

    НЕ КРАСНИТ: 0 краш-путей на 43 СЕМАНТИЧЕСКИХ провалах ИИ — эти баги
    возвращают неверное число, не роняя интерпретатор (граница слоя).
    """
    if rep.get("error"):
        return [rep["error"]]
    bad: list[str] = []
    if rep["false"]:
        names = ", ".join(r["task"] for r in rep["false"][:5])
        bad.append(f"ЛОЖНЫЕ ОБВИНЕНИЯ: {len(rep['false'])} `[CRASH PATH]` НЕ "
                   f"подтверждены живым Python — {names}")
    n = len(rep["blindspots"])
    if n + len(rep["false"]) == 0:
        bad.append("ВАКУУМ: `--xray` не дал ни одного обвинения (класс #345)")
    elif n < EXPECTED_BLINDSPOTS:
        bad.append(f"НЕДОБОР СЛЕПЫХ ПЯТЕН: подтверждено {n}, ожидалось "
                   f"{EXPECTED_BLINDSPOTS}")
    return bad


def print_report(rep: dict) -> None:
    print("=" * 78)
    print("KERN: `--xray` ПРОТИВ MBPP+ — ОРАКУЛ ЖИВОГО ЗАПУСКА PYTHON")
    print("=" * 78)
    print(f"\n  выборки: провалов ИИ {rep['bad_total']} | честных {rep['ok_total']}")
    print(f"  обвинений `[CRASH PATH]` на 43 СЕМАНТИЧЕСКИХ провалах: "
          f"{rep['bad_crashes']} (граница безаннотационного слоя)")
    print(f"  информационных `[BOUNDS]` (НЕ обвинения)               : "
          f"{rep['informational']}")
    print(f"\n  ПОДТВЕРЖДЕНО живым Python (слепые пятна MBPP+): "
          f"{len(rep['blindspots'])}")
    for r in rep["blindspots"]:
        print(f"    {r['task']:<12} {r['detail'][:42]:<44} <- {r['finding'][:34]}")
    print(f"  ЛОЖНЫХ ОБВИНЕНИЙ (Python НЕ упал)              : "
          f"{len(rep['false'])}")
    for r in rep["false"]:
        print(f"    {r['task']:<12} {r['detail'][:60]}")


def selftest() -> int:
    """Мета-тест: (1) ЛОЖНОЕ ОБВИНЕНИЕ; (2) НЕДОБОР; (3) ВАКУУМ; (4) здоровый."""
    bad = 0
    bs = [{"task": f"Mbpp/{t}", "file": "x.py", "finding": "f: n == 0",
           "detail": "ZeroDivisionError"} for t in (265, 292, 422)]
    okrep = {"bad_total": 43, "ok_total": 264, "bad_crashes": 0,
             "blindspots": bs, "false": [], "informational": 5}

    def expect_red(label, rep):
        nonlocal bad
        if verdict(rep):
            print(f"[OK] selftest: {label} ловится")
        else:
            print(f"[FAIL] selftest: {label} НЕ поймано")
            bad += 1

    def expect_green(label, rep):
        nonlocal bad
        if not verdict(rep):
            print(f"[OK] selftest: {label} проходит")
        else:
            print(f"[FAIL] selftest: {label} ошибочно краснит")
            bad += 1

    expect_green("здоровый прогон (3 слепых пятна, 0 ложных)", okrep)
    expect_red("ЛОЖНОЕ ОБВИНЕНИЕ (Python не упал)",
               dict(okrep, false=[{"task": "Mbpp/1", "file": "a.py",
                                   "finding": "f: n == 0", "detail": "не упал"}]))
    expect_red("НЕДОБОР слепых пятен", dict(okrep, blindspots=bs[:2]))
    expect_red("ВАКУУМ (обвинений не было)", dict(okrep, blindspots=[], false=[]))
    print(f"[{'OK' if bad == 0 else 'FAIL'}] mbpp-xray selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MBPP+: --xray против живого Python")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.selftest:
        return selftest()
    if not DATASET.exists():
        print(f"[SKIP] нет {DATASET} — датасета нет, проверять нечего")
        print("[i] Это НЕ «зелёный гейт»: прогон не зачтён.")
        return 2
    rep = collect()
    print_report(rep)
    bad = verdict(rep)
    print("\n" + "-" * 78)
    if bad:
        for b in bad:
            print(f"[FAIL] {b}")
        return 1
    print(f"[OK] {len(rep['blindspots'])} СЛЕПЫХ ПЯТЕН MBPP+ подтверждено живым "
          f"Python (`ZeroDivisionError`), ЛОЖНЫХ ОБВИНЕНИЙ 0.")
    print("[i] ОРАКУЛ — интерпретатор, а не таблица: `pass/pass` в MBPP+ "
          "означает «прошло ЕГО тесты», а не «падений нет».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
