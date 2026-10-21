#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: детерминизм вердикта (шаг 0K.6).

ЗАЧЕМ. Вердикт зависит от решателя, таймаута и машины. На медленном хосте
`T` может превратиться в `N` (таймаут) — и тогда «регресс» в отчёте окажется
сменой стенда, а не кода. Проверка фиксирует: один и тот же вход ДВА раза
даёт ОДИН И ТОТ ЖЕ вердикт, контрпример и счётчик доверенных шагов.

Фикстуры намеренно крошечные (миллисекунды):
  unsat — доказательство (посылки 2/2, trusted 0, дыр 0);
  sat   — контрпример `x = 6`.

Запуск: python3 tools/determinism_check.py [--repeat 2]
        python3 tools/determinism_check.py --override unsat=F   # для canfail
Код возврата: 0 — вердикты совпали и соответствуют ожиданию; 1 — нет.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"

UNSAT = ("(set-logic ALL)\n(declare-const x Int)\n"
         "(assert (> x 5))\n(assert (< x 3))\n(check-sat)\n")
SAT = ("(set-logic ALL)\n(declare-const x Int)\n(assert (> x 5))\n"
       "(check-sat)\n(get-model)\n")

EXPECT = {
    "unsat": {"eq2": "T", "verdict": "ДОКАЗАНО", "trusted": "0", "holes": "0"},
    "sat": {"eq2": "F", "verdict": "НЕ доказано", "counterexample": "x = 6"},
}


def run_once(smt: str) -> dict:
    """Один прогон `kernc prove`; возвращает ТОЛЬКО смысловые поля."""
    with __import__("tempfile").NamedTemporaryFile("w", suffix=".smt2",
                                                   delete=False) as tf:
        tf.write(smt)
        path = tf.name
    try:
        env = dict(os.environ)
        r = subprocess.run([str(KERNC), "prove", path], capture_output=True,
                           text=True, timeout=120, env=env)
    finally:
        Path(path).unlink(missing_ok=True)
    out = r.stdout + r.stderr
    def grab(pat: str) -> str | None:
        m = re.search(pat, out)
        return m.group(1).strip() if m else None
    return {
        "rc": str(r.returncode),
        "eq2": grab(r"KERN-EQ2\s*:\s*([NTFB])"),
        "verdict": grab(r"ВЕРДИКТ\s*:\s*([^\n]+)"),
        "counterexample": grab(r"\[КОНТРПРИМЕР\]\s*([^\n]+)"),
        "trusted": grab(r"ДОВЕРЕННЫХ\s*(\d+)"),
        "holes": grab(r"дыр\s*(\d+)"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Детерминизм вердикта kernc")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--override", default="", metavar="NAME=EQ2",
                    help="намеренно неверное ожидание (для canfail)")
    args = ap.parse_args()

    if not KERNC.exists():
        print(f"[FAIL] нет {KERNC} — сначала `zig build`")
        return 2
    if args.override:
        name, _, val = args.override.partition("=")
        if name in EXPECT and val:
            EXPECT[name] = dict(EXPECT[name], eq2=val)

    bad = 0
    for name, smt in (("unsat", UNSAT), ("sat", SAT)):
        runs = [run_once(smt) for _ in range(max(2, args.repeat))]
        first = runs[0]
        # ДЕФЕКТ #280: при отсутствии решателя вердикта нет вовсе, и старый код
        # падал с TypeError вместо внятного сообщения.
        if first.get("verdict") is None:
            print(f"  [FAIL] {name}: вердикта нет — решатель не найден в PATH "
                  f"(rc={first.get('rc')}). Активируйте .venv или поставьте z3-solver.")
            return 2
        same = all(r == first for r in runs[1:])
        exp = EXPECT[name]

        def ok(key: str, want: str) -> bool:
            got = first.get(key)
            if got is None:
                return False
            # Вердикт печатается с пояснением в скобках — сравниваем префикс.
            return got.startswith(want) if key == "verdict" else got == want

        match = all(ok(k, v) for k, v in exp.items())
        mark = "OK" if (same and match) else "FAIL"
        print(f"  [{mark}] {name}: eq2={first['eq2']} verdict={(first['verdict'] or '')[:24]!r} "
              f"rc={first['rc']} trusted={first['trusted']} holes={first['holes']}")
        if not same:
            print(f"        [FAIL] вердикты различаются между прогонами: {runs}")
            bad += 1
        if not match:
            diff = {k: (first.get(k), v) for k, v in exp.items() if not ok(k, v)}
            print(f"        [FAIL] не совпало с ожиданием: {diff}")
            bad += 1

    print("\n[OK] вердикт детерминирован" if not bad
          else f"\n[FAIL] расхождений: {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
