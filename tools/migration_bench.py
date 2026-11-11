#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Стенд «переписка эквивалентна?» — одна команда, вердикт или вход расхождения.

ЗАЧЕМ. Человек (или агент) переписал функцию «почище». Нужно узнать не «стало ли
красивее», а «осталось ли поведение». Закон писать НЕ надо: он универсален —
    ∀x: f_old(x) == f_new(x)
и `--diff-equiv` проверяет именно его, а пруф-чекер перепроверяет вывод.

ИСПОЛЬЗОВАНИЕ
    python3 tools/migration_bench.py                      # встроенные пары
    python3 tools/migration_bench.py old.py new.py        # своя пара

ЧЕСТНО: сравнение идёт в ЛИНЕЙНОЙ арифметике. Произведение двух переменных
(`amount * rate`) — вне подмножества; стенд печатает это как `НЕ СРАВНИМО`,
а не «эквивалентно».
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAIRS = [
    ("examples/migration/legacy.py", "examples/migration/rewritten_ok.py",
     "чистая переписка clamp"),
    ("examples/migration/legacy.py", "examples/migration/rewritten_bad.py",
     "переписка с переставленными границами"),
]


def run_pair(a: str, b: str) -> tuple[str, str]:
    p = subprocess.run([sys.executable, "tools/kern_contracts.py", "--diff-equiv",
                        str(ROOT / a), str(ROOT / b)],
                       capture_output=True, text=True, timeout=300, cwd=str(ROOT))
    out = p.stdout + p.stderr
    for line in out.splitlines():
        s = line.strip()
        if "[EQUIVALENT]" in s or "[DIVERGED]" in s:
            return ("ЭКВИВАЛЕНТНО" if "[EQUIVALENT]" in s else "РАСХОЖДЕНИЕ", s)
    for line in out.splitlines():
        if "нелинейное" in line or "не входит" in line or "сравнивать нечего" in line:
            return "НЕ СРАВНИМО", line.strip()[:120]
    return "НЕИЗВЕСТНО", (out.strip().splitlines() or ["—"])[-1][:120]


def main() -> int:
    pairs = PAIRS
    if len(sys.argv) == 3:
        pairs = [(sys.argv[1], sys.argv[2], "своя пара")]
    bad = 0
    print(f"{'вердикт':<16} {'кейс':<42} detail")
    print("-" * 110)
    for a, b, title in pairs:
        verdict, detail = run_pair(a, b)
        print(f"{verdict:<16} {title:<42} {detail[:70]}")
        if verdict == "НЕИЗВЕСТНО":
            bad += 1
    print("-" * 110)
    print("Смысл: ЭКВИВАЛЕНТНО — поведение сохранено (сертификат), "
          "РАСХОЖДЕНИЕ — ниже напечатан вход, где версии врут по-разному.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
