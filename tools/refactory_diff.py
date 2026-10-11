#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refactory: ДИФФЕРЕНЦИАЛЬНАЯ верификация БЕЗ внешних моделей.

reference.py = СПЕЦИФИКАЦИЯ. Для каждого кандидата (wrong/ и correct/):
  * сравниваем выход с эталоном на множестве входов;
  * расхождение → KERN: F (контрпример найден);
  * совпадение  → KERN: T (эквивалентен на проверенной области).
"""
import importlib.util
import inspect
import random
import signal
import sys
from pathlib import Path

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/refactory/data/data")
N_INPUTS = int(sys.argv[2]) if len(sys.argv) > 2 else 300


def load(path, name):
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


def gen_args(fn, rnd):
    """Адаптивная генерация: определяем типы аргументов по эталону."""
    params = list(inspect.signature(fn).parameters)
    # пробуем int, затем list
    for kinds in _kind_orders(len(params)):
        args = [_val(k, rnd) for k in kinds]
        try:
            fn(*args)
            return kinds
        except Exception:
            continue
    return ["int"] * len(params)


def _kind_orders(n):
    if n == 0:
        return [[]]
    if n == 1:
        return [["int"], ["list"]]
    if n == 2:
        return [["int", "int"], ["int", "list"], ["list", "int"], ["list", "list"]]
    return [["int"] * n, ["list"] * n]


def _val(kind, rnd):
    if kind == "int":
        return rnd.choice([0, 1, 2, 3, 5, 10, -1, -5, 100])
    return [rnd.randint(-3, 10) for _ in range(rnd.randint(0, 6))]


def call_safe(fn, args, timeout=0.5):
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
    except Exception as e:
        signal.setitimer(signal.ITIMER_REAL, 0)
        return ("exc", type(e).__name__)
    finally:
        signal.signal(signal.SIGALRM, old)


def main():
    rnd = random.Random(42)
    questions = sorted(d for d in DATA.iterdir() if d.is_dir() and d.name.startswith("question"))
    print(f"Refactory: {len(questions)} вопросов | входов на кандидата: {N_INPUTS}\n")
    print(f"{'Вопрос':<12} | {'reference':<12} | {'wrong: поймано':<18} | {'correct: подтверждено':<22}")
    print("-" * 78)
    tot_w = det_w = tot_c = ok_c = 0
    for q in questions:
        refp = q / "code" / "reference" / "reference.py"
        if not refp.exists():
            continue
        try:
            ref = get_fn(load(refp, f"ref_{q.name}"))
        except Exception as e:
            print(f"{q.name:<12} | ошибка загрузки эталона: {e}")
            continue
        kinds = gen_args(ref, rnd)
        # входы
        inputs = [[_val(k, rnd) for k in kinds] for _ in range(N_INPUTS)]
        ref_out = [call_safe(ref, a) for a in inputs]

        def check(cand_dir, label):
            tot = det = 0
            for f in sorted(cand_dir.glob("*.py")):
                try:
                    fn = get_fn(load(f, f"c_{q.name}_{f.stem}"))
                except Exception:
                    continue
                if fn is None:
                    continue
                tot += 1
                diverged = False
                for a, ro in zip(inputs, ref_out):
                    got = call_safe(fn, a)
                    if got != ro:
                        diverged = True
                        break
                det += diverged
            return tot, det

        tw, dw = check(q / "code" / "wrong", "wrong")
        tc, dc = check(q / "code" / "correct", "correct")
        tot_w += tw; det_w += dw; tot_c += tc; ok_c += (tc - dc)
        wpct = f"{dw}/{tw}" if tw else "-"
        cpct = f"{tc-dc}/{tc}" if tc else "-"
        print(f"{q.name:<12} | {"+".join(kinds):<12} | {wpct:<18} | {cpct:<22}", flush=True)
    print("-" * 78)
    print(f"\n📊 Refactory (БЕЗ внешних моделей):")
    print(f"  Багованных (wrong) поймано:        {det_w}/{tot_w} ({det_w/tot_w*100:.1f}%)" if tot_w else "  wrong: нет")
    print(f"  Корректных (correct) подтверждено: {ok_c}/{tot_c} ({ok_c/tot_c*100:.1f}%)" if tot_c else "  correct: нет")


if __name__ == "__main__":
    main()
