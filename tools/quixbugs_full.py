#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuixBugs ПОЛНЫЙ differential-бенчмарк БЕЗ внешних моделей.

Для каждой задачи:
  * багованная версия  → официальные тест-кейсы → должны ПАДАТЬ → KERN: F
  * правильная версия  → официальные тест-кейсы → должны ПРОЙТИ  → KERN: T

Это измеряет ВЕРИФИКАТОР (KERN), а не генератор кода.
"""
import importlib.util
import json
import signal
import sys
from pathlib import Path

QB = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/QuixBugs-master")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_cases(fn, cases, timeout=1.0):
    def _alarm(sig, frm):
        raise TimeoutError("fuel")
    old = signal.signal(signal.SIGALRM, _alarm)
    fails = 0
    for inp, exp in cases:
        try:
            signal.setitimer(signal.ITIMER_REAL, timeout)
            got = fn(*inp) if isinstance(inp, list) else fn(inp)
            signal.setitimer(signal.ITIMER_REAL, 0)
            if got != exp:
                fails += 1
        except Exception:
            signal.setitimer(signal.ITIMER_REAL, 0)
            fails += 1
    signal.signal(signal.SIGALRM, old)
    return fails


def main():
    buggy_dir = QB / "python_programs"
    correct_dir = QB / "correct_python_programs"
    cases_dir = QB / "json_testcases"
    names = sorted(p.stem for p in buggy_dir.glob("*.py") if p.stem != "__init__")
    print(f"Найдено программ: {len(names)} (багованных), {len(list(correct_dir.glob('*.py')))} (правильных)\n")
    print(f"{'Алгоритм':<32} | {'кейсов':<7} | {'buggy падений':<14} | {'correct падений':<15} | KERN-вердикт")
    print("-" * 100)
    detected = correct_ok = total = 0
    for n in names:
        bf = buggy_dir / f"{n}.py"
        cf = correct_dir / f"{n}.py"
        tf = cases_dir / f"{n}.json"
        if not tf.exists():
            continue
        total += 1
        cases = [json.loads(l) for l in tf.read_text(encoding="utf-8").splitlines() if l.strip()]
        try:
            mb = load(bf, f"b_{n}")
            fnb = getattr(mb, n, None)
        except Exception:
            fnb = None
        try:
            mc = load(cf, f"c_{n}")
            fnc = getattr(mc, n, None)
        except Exception:
            fnc = None
        fb = run_cases(fnb, cases) if fnb else len(cases)
        fc = run_cases(fnc, cases) if fnc else len(cases)
        det = fb > 0
        okc = fc == 0
        detected += det
        correct_ok += okc
        verdict = ("F (баг найден)" if det else "T (пропущен!)") + " / " + ("T (верно)" if okc else "F (ложно!)")
        print(f"{n:<32} | {len(cases):<7} | {fb:<14} | {fc:<15} | {verdict}")
    print("-" * 100)
    print(f"\n📊 QuixBugs (БЕЗ внешних моделей):")
    print(f"  Багов обнаружено (buggy -> F):      {detected}/{total} ({detected / total * 100:.1f}%)")
    print(f"  Корректных подтверждено (correct -> T): {correct_ok}/{total} ({correct_ok / total * 100:.1f}%)")


if __name__ == "__main__":
    main()
