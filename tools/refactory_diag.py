#!/usr/bin/env python3
"""KERN: ДИАГНОСТИКА пропусков Refactory (только измерение).

ВАЖНО ПРО МЕТОД. `tools/refactory_diff.py` — это ДИФФЕРЕНЦИАЛЬНОЕ ИСПОЛНЕНИЕ,
а не трансляция Python AST в SMT: он запускает эталон и кандидата на случайных
входах и сравнивает (результат, тип исключения). Ни Z3, ни контрактов, ни
раскрутки циклов в нём нет. Значит причины пропусков надо искать не в
«неподдержанных узлах AST», а в ПОКРЫТИИ ВХОДОВ.

Этот скрипт отвечает на один вопрос: если расширить генерацию входов
(пустой список, один элемент, дубликаты, отрицательные, отсортированные,
обратный порядок, крупные значения), сколько пропущенных багов находится?

ЖЁСТКОЕ ТРЕБОВАНИЕ: на КОРРЕКТНЫХ решениях ложных срабатываний должно
остаться СТРОГО 0. Считается отдельно для старого и нового набора.

Запуск: python3 tools/refactory_diag.py [DATA_DIR] [N_OLD] [N_NEW]
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import random
import signal
import sys
from pathlib import Path

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/refactory/data/data")
N_OLD = int(sys.argv[2]) if len(sys.argv) > 2 else 100
N_NEW = int(sys.argv[3]) if len(sys.argv) > 3 else 200


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def get_fn(mod):
    for n in dir(mod):
        if n.startswith("_"):
            continue
        o = getattr(mod, n)
        if inspect.isfunction(o) and o.__module__ == mod.__name__:
            return o
    return None


def _kind_orders(n):
    if n == 0:
        return [[]]
    if n == 1:
        return [["int"], ["list"]]
    if n == 2:
        return [["int", "int"], ["int", "list"], ["list", "int"], ["list", "list"]]
    return [["int"] * n, ["list"] * n]


def gen_args(fn, rnd):
    params = list(inspect.signature(fn).parameters)
    for kinds in _kind_orders(len(params)):
        args = [_val_old(k, rnd) for k in kinds]
        try:
            fn(*args)
            return kinds
        except Exception:
            continue
    return ["int"] * len(params)


def _val_old(kind, rnd):
    """Набор А — ровно как в текущем бенчмарке."""
    if kind == "int":
        return rnd.choice([0, 1, 2, 3, 5, 10, -1, -5, 100])
    return [rnd.randint(-3, 10) for _ in range(rnd.randint(0, 6))]


def _val_new(kind, rnd):
    """Набор Б — граничные и структурные входы."""
    if kind == "int":
        return rnd.choice([0, 1, 2, 3, 4, 5, 7, 10, -1, -2, -5, 100, 1000])
    n = rnd.choice([0, 1, 1, 2, 2, 3, 4, 5, 6, 8])
    v = [rnd.randint(-3, 10) for _ in range(n)]
    shape = rnd.randint(0, 6)
    if shape == 0:
        return []
    if shape == 1:
        return [rnd.randint(-3, 10)]
    if shape == 2:
        return [rnd.randint(-3, 10)] * n
    if shape == 3:
        return sorted(v)
    if shape == 4:
        return sorted(v, reverse=True)
    if shape == 5:
        return [rnd.choice([0, 1, -1, 5, 100, 1000]) for _ in range(n)]
    return v


def call_safe(fn, args, timeout=0.5):
    def _al(s, f):
        raise TimeoutError()

    old = signal.signal(signal.SIGALRM, _al)
    try:
        signal.setitimer(signal.ITIMER_REAL, timeout)
        r = fn(*args)
        signal.setitimer(signal.ITIMER_REAL, 0)
        return ("ok", repr(r))
    except TimeoutError:
        return ("timeout", None)
    except Exception as e:
        signal.setitimer(signal.ITIMER_REAL, 0)
        return ("exc", type(e).__name__)
    finally:
        signal.signal(signal.SIGALRM, old)


def main() -> int:
    rnd = random.Random(42)
    questions = sorted(d for d in DATA.iterdir()
                       if d.is_dir() and d.name.startswith("question"))
    print(f"Refactory: {len(questions)} вопросов | входов А={N_OLD}, Б={N_NEW}\n")
    tot = {"wrong": 0, "correct": 0}
    caught_old = missed_then_new = missed_both = 0
    fp_old = fp_new = 0

    for q in questions:
        refp = q / "code" / "reference" / "reference.py"
        if not refp.exists():
            continue
        try:
            ref = get_fn(load(refp, f"ref_{q.name}"))
        except Exception as e:  # noqa: BLE001
            print(f"{q.name}: эталон не загрузился: {e}")
            continue
        if ref is None:
            continue
        kinds = gen_args(ref, rnd)
        inputs_a = [[_val_old(k, rnd) for k in kinds] for _ in range(N_OLD)]
        inputs_b = [[_val_new(k, rnd) for k in kinds] for _ in range(N_NEW)]
        ref_a = [call_safe(ref, a) for a in inputs_a]
        ref_b = [call_safe(ref, a) for a in inputs_b]

        def diverges(fn, inputs, ref_out):
            for a, ro in zip(inputs, ref_out):
                if call_safe(fn, a) != ro:
                    return True
            return False

        q_caught = q_new = q_both = q_w = 0
        for f in sorted((q / "code" / "wrong").glob("*.py")):
            try:
                fn = get_fn(load(f, f"w_{q.name}_{f.stem}"))
            except Exception:  # noqa: BLE001
                continue
            if fn is None:
                continue
            tot["wrong"] += 1
            q_w += 1
            if diverges(fn, inputs_a, ref_a):
                caught_old += 1
                q_caught += 1
            elif diverges(fn, inputs_b, ref_b):
                missed_then_new += 1
                q_new += 1
            else:
                missed_both += 1
                q_both += 1

        q_fp_old = q_fp_new = q_c = 0
        for f in sorted((q / "code" / "correct").glob("*.py")):
            try:
                fn = get_fn(load(f, f"c_{q.name}_{f.stem}"))
            except Exception:  # noqa: BLE001
                continue
            if fn is None:
                continue
            tot["correct"] += 1
            q_c += 1
            if diverges(fn, inputs_a, ref_a):
                fp_old += 1
                q_fp_old += 1
            if diverges(fn, inputs_b, ref_b):
                fp_new += 1
                q_fp_new += 1

        print(f"{q.name:<12} | wrong={q_w:<4} A={q_caught:<4} +Б={q_new:<4} "
              f"оба-мимо={q_both:<4} | correct={q_c:<4} FP_A={q_fp_old} FP_Б={q_fp_new}",
              flush=True)

    tw = max(1, tot["wrong"])
    print("\n" + "=" * 78)
    print(f"багованных (wrong) всего:   {tot['wrong']}")
    print(f"  поймано набором А:        {caught_old} ({caught_old/tw*100:.1f}%)")
    print(f"  ДОБРАНО набором Б:        {missed_then_new}")
    print(f"  осталось непойманными:    {missed_both}")
    print(f"  ИТОГО с Б:                {caught_old + missed_then_new} "
          f"({(caught_old+missed_then_new)/tw*100:.1f}%)")
    print(f"корректных (correct) всего: {tot['correct']}")
    print(f"  ЛОЖНЫХ СРАБАТЫВАНИЙ А:    {fp_old}")
    print(f"  ЛОЖНЫХ СРАБАТЫВАНИЙ Б:    {fp_new}")
    Path("/tmp/refactory_diag.json").write_text(json.dumps({
        "wrong_total": tot["wrong"], "caught_old": caught_old,
        "caught_by_new_only": missed_then_new, "missed_both": missed_both,
        "correct_total": tot["correct"], "fp_old": fp_old, "fp_new": fp_new,
        "n_old": N_OLD, "n_new": N_NEW}, indent=2), encoding="utf-8")
    return 0 if fp_new == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
