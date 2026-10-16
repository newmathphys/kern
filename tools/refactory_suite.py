#!/usr/bin/env python3
"""KERN: Refactory на ИСТИННОМ оракуле датасета (тест-сьют `ans/`).

ПОЧЕМУ ЭТОТ СКРИПТ, А НЕ `refactory_diff.py`.

Метки `correct` / `wrong` в Refactory определены НЕ поведением `reference.py`
на произвольных входах, а ТЕСТ-СЬЮТОМ датасета (README, п. 1-4):

    correct_abc.py — проходит ВСЕ тест-кейсы
    wrong_xyz.py   — падает на ОДНОМ ИЛИ БОЛЕЕ тест-кейсах
    reference.py   — проходит полный тест-сьют

`tools/refactory_diff.py` сравнивает кандидата с `reference.py` на СЛУЧАЙНЫХ
входах. Это измеряет не то, что заявлено: на «правильных» файлах расхождение
с эталоном возникает постоянно (два разных корректных решения могут вести себя
по-разному вне тест-сьюта), поэтому метрика не различает классы.

Здесь оракул — сам тест-сьют: `ans/input_NNN.txt` (выражение) и
`ans/output_NNN.txt` (ожидаемый результат).

Запуск: python3 tools/refactory_suite.py [DATA_DIR]
"""
from __future__ import annotations

import contextlib
import io

import importlib.util
import inspect
import json
import re
import signal
import sys
from pathlib import Path

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/refactory/data/data")

CALL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", re.S)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def funcs(mod):
    out = {}
    for n in dir(mod):
        if n.startswith("_"):
            continue
        o = getattr(mod, n)
        if inspect.isfunction(o) and o.__module__ == mod.__name__:
            out[n] = o
    return out


def call_safe(fn, args, timeout=1.0):
    def _al(s, f):
        raise TimeoutError()

    old = signal.signal(signal.SIGALRM, _al)
    try:
        signal.setitimer(signal.ITIMER_REAL, timeout)
        r = fn(*args)
        signal.setitimer(signal.ITIMER_REAL, 0)
        return ("ok", r)
    except TimeoutError:
        return ("timeout", None)
    except Exception as e:  # noqa: BLE001
        signal.setitimer(signal.ITIMER_REAL, 0)
        return ("exc", type(e).__name__)
    finally:
        signal.signal(signal.SIGALRM, old)


def parse_case(text: str):
    """`search(42, (-5, 1, 3, 5, 7, 10))` -> ('search', (42, (-5,1,3,5,7,10)))"""
    m = CALL_RE.match(text.strip())
    if not m:
        return None
    fname, argstr = m.group(1), m.group(2)
    try:
        args = eval(f"({argstr},)")  # noqa: S307 — данные датасета, не ввод извне
    except Exception:  # noqa: BLE001
        return None
    return fname, args


def load_suite(q: Path):
    ans = q / "ans"
    cases = []
    for inp in sorted(ans.glob("input_*.txt")):
        outp = ans / inp.name.replace("input_", "output_")
        if not outp.exists():
            continue
        pc = parse_case(inp.read_text(encoding="utf-8", errors="replace"))
        if pc is None:
            continue
        want = outp.read_text(encoding="utf-8", errors="replace").strip()
        cases.append((pc[0], pc[1], want))
    return cases


def run_suite(fn_map, cases):
    """Возвращает (пройдено, всего, первый_провал)."""
    ok = 0
    first_fail = None
    # Имена функций у студентов отличаются от эталонных (например,
    # `sequential_search` вместо `search`), поэтому если по имени не нашли —
    # берём единственную публичную функцию модуля.
    fallback = list(fn_map.values())[0] if len(fn_map) == 1 else None
    for fname, args, want in cases:
        fn = fn_map.get(fname) or fallback
        if fn is None:
            if first_fail is None:
                first_fail = f"нет функции {fname}"
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            kind, val = call_safe(fn, args)
        got = repr(val) if kind == "ok" else f"<{kind}:{val}>"
        if kind == "ok" and got == want:
            ok += 1
        elif first_fail is None:
            first_fail = f"{fname}{args} -> {got[:40]}, ждали {want[:20]}"
    return ok, len(cases), first_fail


def main() -> int:
    questions = sorted(d for d in DATA.iterdir()
                       if d.is_dir() and d.name.startswith("question"))
    print(f"Refactory на тест-сьюте датасета: {len(questions)} вопросов\n")
    res = {}
    tw = cw = tc = cc = 0

    for q in questions:
        cases = load_suite(q)
        if not cases:
            print(f"{q.name}: тест-сьют не найден")
            continue
        q_w = q_wc = q_c = q_cc = 0
        for f in sorted((q / "code" / "wrong").glob("*.py")):
            try:
                fm = funcs(load(f, f"w_{q.name}_{f.stem}"))
            except Exception:  # noqa: BLE001
                continue
            if not fm:
                continue
            q_w += 1
            ok, tot, _ = run_suite(fm, cases)
            if ok < tot:
                q_wc += 1
        for f in sorted((q / "code" / "correct").glob("*.py")):
            try:
                fm = funcs(load(f, f"c_{q.name}_{f.stem}"))
            except Exception:  # noqa: BLE001
                continue
            if not fm:
                continue
            q_c += 1
            ok, tot, _ = run_suite(fm, cases)
            if ok == tot:
                q_cc += 1
        tw += q_w
        cw += q_wc
        tc += q_c
        cc += q_cc
        res[q.name] = {"wrong": q_w, "wrong_caught": q_wc,
                       "correct": q_c, "correct_confirmed": q_cc,
                       "cases": len(cases)}
        print(f"{q.name:<12} | кейсов={len(cases):<3} | wrong {q_wc}/{q_w} "
              f"| correct подтверждено {q_cc}/{q_c}", flush=True)

    print("\n" + "=" * 78)
    print(f"БАГОВАННЫХ поймано:        {cw}/{tw} ({cw/max(1,tw)*100:.1f}%)")
    print(f"КОРРЕКТНЫХ подтверждено:   {cc}/{tc} ({cc/max(1,tc)*100:.1f}%)")
    print(f"ЛОЖНЫХ СРАБАТЫВАНИЙ:       {tc-cc} "
          f"({(tc-cc)/max(1,tc)*100:.2f}%)  <- должно быть 0")
    out = {"wrong_total": tw, "wrong_caught": cw, "correct_total": tc,
           "correct_confirmed": cc, "per_question": res}
    Path("/tmp/refactory_suite.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
