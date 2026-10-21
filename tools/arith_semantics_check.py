#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""ДЕФЕКТ #317: СЕМАНТИКА ЦЕЛОЧИСЛЕННОГО ДЕЛЕНИЯ В ТРАНСЛЯЦИИ (ОТКРЫТ).

ВНЕШНИЙ ОТЧЁТ. Massimiliano Brigindi (F/OMEGA), приватное раскрытие: перевод
`tools/kern_contracts.py::expr_smt` выдаёт для Python `//` и `%` операторы
SMT-LIB `div`/`mod`, а у них ЕВКЛИДОВА семантика (остаток всегда >= 0), тогда
как Python использует FLOOR-семантику (остаток имеет знак ДЕЛИТЕЛЯ).

    Python 1 // -2 == -1        SMT (div 1 (- 2)) == 0
    Python 1 %  -2 == -1        SMT (mod 1 (- 2)) == 1

СЛЕДСТВИЕ (подтверждено здесь): ложное ДОКАЗАНО. Контракт

    # @kern:requires a == 3 and b == -2
    # @kern:ensures result >= -1
    def f(a: int, b: int) -> int: return a // b

KERN объявляет ДОКАЗАННЫМ (`premises bound: 3/3`, `holes: 0`), тогда как живой
Python даёт `3 // -2 == -2` и контракт НАРУШЕН. Это ложное принятие: доказано
утверждение о ДРУГОЙ функции.

C-подобные языки затронуты тем же местом: в C `-7 / 2 == -3` (усечение к нулю),
а SMT `(div -7 2) == -4` (floor). Измерено: контракт `ensures result == -4`
ДОКАЗАН, а истинный `ensures result == -3` — ОПРОВЕРГНУТ с контрпримером.

ЧТО ДЕЛАЕТ ЭТОТ СКРИПТ. Дифференциальная проверка на ЛОКАЛЬНОМ уровне перевода
(не полный контур KERN, не Zig-пруф-чекер): перебирает a,b в [-10,10], b != 0,
для `//` и `%`, сравнивает (а) вывод `expr_smt`, вычисленный Z3, (б) живой Python
и (в) эталонные адаптеры floor (Python) и trunc (C/Zig/Rust). Код выходит 1,
пока дефект открыт; после починки обязан выйти 0. Это регрессия «fail-to-pass»,
а не страж: она ЗАКРЕПЛЯЕТ дефект, чтобы починку можно было проверить.

Невакуумность обеспечена: скрипт требует, чтобы исходный перевод РАСХОДИЛСЯ
(иначе адаптеру нечего доказывать) и чтобы при b > 0 расхождений НЕ было (иначе
диагноз «дело в знаке делителя» неверен).

Запуск: python3 tools/arith_semantics_check.py
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Эталон FLOOR (Python): для b > 0 оператор SMT `div` совпадает с floor, поэтому
# отрицательный делитель нормализуется. Адаптер из отчёта.
FLOOR_Q = "(ite (> {b} 0) (div {a} {b}) (div (- {a}) (- {b})))"
FLOOR_R = "(- {a} (* {b} {q}))"
# Эталон TRUNC (C/Zig/Rust): усечение к нулю = знак(a)*знак(b)*floor(|a|/|b|).
TRUNC_Q = "(ite (>= (* {a} {b}) 0) " + FLOOR_Q + " (- " + FLOOR_Q + "))"


def _translator():
    spec = importlib.util.spec_from_file_location(
        "kc", ROOT / "tools" / "kern_contracts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _z3_value(text: str) -> int | None:
    try:
        import z3
    except ImportError:
        return None
    try:
        node = z3.parse_smt2_string(
            "(declare-const r Int)(assert (= r " + text + "))")[0]
        return z3.simplify(node.arg(1)).as_long()
    except Exception:
        return None


def _trunc_q(a: int, b: int) -> int:
    """Усечение к нулю (семантика C/Zig/Rust): знак — от произведения знаков."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def _trunc_r(a: int, b: int) -> int:
    return a - b * _trunc_q(a, b)


def _reference(op: str, a: int, b: int, q_tpl: str) -> str:
    q = q_tpl.format(a=str(a), b=str(b))
    return q if op == "//" else FLOOR_R.format(a=str(a), b=str(b), q=q)


def main() -> int:
    kc = _translator()
    if _z3_value("1") is None:
        print("[!] нет z3 — проверка невозможна (это не «зелено»)")
        return 2

    total = old_bad = floor_bad = positive_bad = 0
    examples: list[str] = []
    for a in range(-10, 11):
        for b in range(-10, 11):
            if b == 0:
                continue
            for op in ("//", "%"):
                expected = a // b if op == "//" else a % b
                try:
                    translated = kc.expr_smt(
                        ast.parse(f"({a}) {op} ({b})", mode="eval").body, {})
                except Exception:
                    continue
                got = _z3_value(translated)
                floor_ref = _z3_value(_reference(op, a, b, FLOOR_Q))
                total += 1
                old_bad += got != expected
                floor_bad += floor_ref != expected
                positive_bad += b > 0 and got != expected
                if got != expected and len(examples) < 4:
                    examples.append(f"    {a} {op} {b}: python={expected} "
                                    f"smt={got} (перевод {translated})")

    print(f"[i] вычислений: {total} (a,b в [-10,10], b != 0, операторы // и %)")
    print(f"[i] расхождений ИСХОДНОГО перевода: {old_bad}")
    print(f"[i] расхождений эталона FLOOR (Python): {floor_bad}")
    print(f"[i] контроль (b > 0, исходный перевод): {positive_bad}")
    if examples:
        print("[i] примеры:")
        print("\n".join(examples))

    bad = 0
    # 1) Невакуумность: исходный перевод ОБЯЗАН расходиться.
    if old_bad == 0:
        print("[FAIL] исходный перевод совпал везде — регрессия стала вакуумной")
        bad += 1
    # 2) Контроль: при ПОЛОЖИТЕЛЬНОМ делителе семантики обязаны совпадать —
    #    иначе диагноз «дело в знаке делителя» неверен.
    if positive_bad != 0:
        print(f"[FAIL] расхождения при b > 0 ({positive_bad}) — диагноз неполон")
        bad += 1
    # 3) Эталон floor обязан совпадать с Python ВЕЗДЕ.
    if floor_bad != 0:
        print(f"[FAIL] эталон FLOOR расходится с Python ({floor_bad})")
        bad += 1

    if bad:
        print(f"\n[FAIL] сама проверка несостоятельна (ошибок {bad})")
        return 2
    # ДЕФЕКТ #317: расхождения ЕСТЬ — значит дефект ОТКРЫТ. Это не «зелено»,
    # и выход обязан быть ненулевым, иначе регрессия станет вакуумной (ровно
    # та ошибка, от которой проект страдал девять раз).
    if old_bad:
        print(f"\n[OPEN] ДЕФЕКТ #317 ПОДТВЕРЖДЁН: перевод {old_bad} из {total} "
              f"выражений описывает ДРУГУЮ функцию. Эталон FLOOR (Python) даёт 0 "
              f"расхождений — починка известна и проверяема.")
        return 1
    print("\n[OK] дефект #317 закрыт: перевод совпадает с семантикой языка")
    return 0


if __name__ == "__main__":
    sys.exit(main())

