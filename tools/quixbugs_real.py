#!/usr/bin/env python3
"""QuixBugs: РЕАЛЬНАЯ проверка — прогон багованных программ по официальным тест-кейсам."""
import importlib.util
import json
import signal
import sys
from pathlib import Path

QB = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/QuixBugs-master")
ALGOS = ["bitcount", "bucketsort", "find_in_sorted", "gcd", "knapsack",
         "longest_common_subsequence", "max_sublist_sum", "mergesort", "quicksort",
         "rpn_eval", "sieve", "sqrt"]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    print(f"{'Алгоритм':<30} | {'кейсов':<7} | {'падений':<8} | вердикт")
    print("-" * 74)
    caught = total = 0
    for a in ALGOS:
        total += 1
        pf = QB / "python_programs" / f"{a}.py"
        tf = QB / "json_testcases" / f"{a}.json"
        if not pf.exists() or not tf.exists():
            print(f"{a:<30} | -       | -        | нет файлов")
            continue
        cases = [json.loads(l) for l in tf.read_text(encoding="utf-8").splitlines() if l.strip()]
        try:
            m = load_module(pf, f"qb_{a}")
        except Exception as e:
            print(f"{a:<30} | {len(cases):<7} | -        | ошибка импорта: {str(e)[:20]}")
            continue
        fn = getattr(m, a, None)
        if fn is None:
            for n in dir(m):
                if not n.startswith("_") and callable(getattr(m, n)):
                    fn = getattr(m, n)
                    break

        def _alarm(sig, frm):
            raise TimeoutError("fuel")

        old_h = signal.signal(signal.SIGALRM, _alarm)
        fails = 0
        for inp, exp in cases:
            try:
                signal.setitimer(signal.ITIMER_REAL, 1.0)
                got = fn(*inp) if isinstance(inp, list) else fn(inp)
                signal.setitimer(signal.ITIMER_REAL, 0)
                if got != exp:
                    fails += 1
            except Exception:
                signal.setitimer(signal.ITIMER_REAL, 0)
                fails += 1
        signal.signal(signal.SIGALRM, old_h)
        verdict = "F (БАГ ОБНАРУЖЕН)" if fails else "T (прошёл)"
        caught += 1 if fails else 0
        print(f"{a:<30} | {len(cases):<7} | {fails:<8} | {verdict}", flush=True)
    print("-" * 74)
    print(f"\nИТОГ: реальным ИСПОЛНЕНИЕМ обнаружено багов {caught}/{total} ({caught / total * 100:.0f}%).")


if __name__ == "__main__":
    main()
