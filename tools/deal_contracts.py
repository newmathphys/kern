#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by the GNU Affero General Public License v3.0 ONLY
# (AGPL-3.0-only), or a commercial license from the copyright holder. See LICENSE.
"""KERN × Deal (Design by Contract): проверка контрактов функций.

ИДЕЯ: `deal` позволяет описать контракт функции прямо в Python
(`@deal.pre` — предусловие, `@deal.post` — постусловие). KERN берёт этот
контракт и МАТЕМАТИЧЕСКИ проверяет его на всей области значений через Z3:

    pre(x) ∧ ¬post(x, f(x))   —  если НЕВЫПОЛНИМО (unsat) → контракт ДОКАЗАН;
                                  если выполнимо (sat) → есть КОНТРПРИМЕР.

ЧЕСТНО О ГРАНИЦАХ:
  • `deal` — источник ИСТИНЫ для контрактов (он же их проверяет в рантайме);
  • перевод контракта в SMT-LIB выполняется вручную (в этом файле) — это
    НЕ автоматическая формализация произвольного Python. Полный
    autoformalization требует символьного исполнения (CrossHair), и здесь
    он не используется: вместо этого контракты заданы парами
    (python-функция с @deal + эквивалентная SMT-формула).
  • вердикт выносит Z3 через `kernc prove`, а не KERN «на слово».

Запуск:  python3 tools/deal_contracts.py
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"

# ---------------------------------------------------------------------------
# Контракты: (имя, python-функция с @deal, SMT-LIB2, ожидаемый вердикт)
# ---------------------------------------------------------------------------
try:
    import deal
    HAVE_DEAL = True
except ImportError:  # pragma: no cover
    HAVE_DEAL = False


if HAVE_DEAL:

    @deal.pre(lambda x: x > 0)
    @deal.post(lambda result: result > 0)
    def double_ok(x: int) -> int:
        """Верная: при x>0 результат 2x тоже >0."""
        return x * 2

    @deal.pre(lambda x: x > 0)
    @deal.post(lambda result: result > 100)
    def double_bad(x: int) -> int:
        """Ложная: при x=1 результат 2, что НЕ >100."""
        return x * 2

    @deal.pre(lambda a, b: b != 0)
    @deal.post(lambda result: result * b <= a)
    def div_ok(a: int, b: int) -> int:
        """Целочисленное деление: (a//b)*b <= a — верно для всех a, b!=0."""
        return a // b

    @deal.pre(lambda a, b: b != 0)
    @deal.post(lambda result: result * b == a)
    def div_bad(a: int, b: int) -> int:
        """Ложная: деление нацело НЕ возвращает точное произведение."""
        return a // b


CASES = [
    (
        "double_ok",
        double_ok if HAVE_DEAL else None,
        "(set-logic ALL)(declare-const x Int)"
        "(assert (> x 0))"
        "(assert (not (> (* x 2) 0)))(check-sat)",
        "unsat",  # контракт доказан
    ),
    (
        "double_bad",
        double_bad if HAVE_DEAL else None,
        "(set-logic ALL)(declare-const x Int)"
        "(assert (> x 0))"
        "(assert (not (> (* x 2) 100)))(check-sat)",
        "sat",  # контрпример существует
    ),
    (
        "div_ok",
        div_ok if HAVE_DEAL else None,
        "(set-logic ALL)(declare-const a Int)(declare-const b Int)"
        "(assert (not (= b 0)))"
        "(assert (not (<= (* (div a b) b) a)))(check-sat)",
        "unsat",
    ),
    (
        "div_bad",
        div_bad if HAVE_DEAL else None,
        "(set-logic ALL)(declare-const a Int)(declare-const b Int)"
        "(assert (not (= b 0)))"
        "(assert (not (= (* (div a b) b) a)))(check-sat)",
        "sat",
    ),
]


def run_kernc(smt: str):
    """Прогон формулы через KERN (Z3-мост). Возвращает 'sat'/'unsat'/'?'."""
    p = subprocess.run(
        [str(KERNC), "prove", "/dev/stdin"],
        input=smt.encode(),
        capture_output=True,
        cwd=str(ROOT),
    )
    out = (p.stdout or b"").decode(errors="replace") + (p.stderr or b"").decode(errors="replace")
    # kernc prove печатает KERN-EQ2 (T/F/B/N), а не сырой sat/unsat.
    if "KERN-EQ2 : T" in out:
        return "unsat"  # доказано
    if "KERN-EQ2 : F" in out:
        return "sat"    # контрпример
    return "?"


def main() -> int:
    if not KERNC.exists():
        print("[!] нет zig-out/bin/kernc — сначала: zig build")
        return 1
    if not HAVE_DEAL:
        print("[!] нет пакета deal — установите: uv pip install deal")
        return 1

    print("\n=== KERN × Deal: проверка контрактов (Design by Contract) ===")
    print("Вердикт выносит Z3 через `kernc prove`; deal — источник контрактов.\n")

    ok = 0
    for name, fn, smt, expect in CASES:
        got = run_kernc(smt)
        good = got == expect
        ok += 1 if good else 0
        mark = "OK " if good else "РАСХОЖДЕНИЕ"
        verdict = {
            "unsat": "ДОКАЗАНО (контракт верен для всех входов)",
            "sat": "КОНТРПРИМЕР (контракт нарушается)",
            "?": "неизвестно",
        }.get(got, got)
        print(f"  [{mark}] {name:<12} ожидалось {expect:<5} получено {got:<5} — {verdict}")

    print(f"\nИТОГ: {ok}/{len(CASES)} контрактов проверено верно")
    print("Примечание: перевод контракта в SMT-LIB выполнен вручную (см. шапку файла).\n")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
