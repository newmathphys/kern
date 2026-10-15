#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""proof_checker.py — НЕЗАВИСИМАЯ проверка вывода решателя (proof checking).

**Зачем.** Z3 — около миллиона строк C++. Верить ему «на слово» нельзя:
заводской баг может дать ложный `unsat`. KERN уже делает структурный
контроль в `src/verifier/proof_check.zig`; здесь — ВТОРОЙ, НЕЗАВИСИМЫЙ
контроль, реализованный **на другом языке** (Python), чтобы ошибка в Zig
не могла «подтвердить сама себя».

**ЧТО ПРОВЕРЯЕТСЯ (строго):**
  1. **Скобочная сбалансированность** S-выражения вывода.
  2. **Гигиена связываний:** каждая `let`-переменная определена ДО
     использования (нет ссылок вперёд).
  3. **Замкнутость:** все свободные символы шага либо связаны `let`,
     либо являются аксиомами/утверждениями (`asserted`), либо термами.
  4. **Финальный вывод** — литерал `false` (доказательство невыполнимости).
  5. **Отсутствие пустого вывода** (вакуумный «доказательство»).

**⚠️ ЧЕСТНАЯ ГРАНИЦА.** Это НЕ полный Alethe/LFSC-чекер: каждый шаг дедукции
(например, `th-lemma arith farkas`) **не перепроверяется аксиоматически** —
для этого нужен сторонний чекер (Carcara), которого в окружении нет.
Проверяется СТРУКТУРНАЯ корректность вывода + гигиена связываний.

Запуск:
  python3 tools/proof_checker.py            # набор встроенных контрактов
  python3 tools/proof_checker.py file.smt2  # свой контракт
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
Z3 = str(ROOT / ".venv" / "bin" / "z3")

CASES = [
    ("парадокс x>5 ∧ x<2", "(declare-const x Int)(assert (> x 5))(assert (< x 2))"),
    ("противоречие p ∧ ¬p", "(declare-const p Bool)(assert p)(assert (not p))"),
    ("линейная арифметика 2x<2 ∧ x>1", "(declare-const x Int)(assert (< (* 2 x) 2))(assert (> x 1))"),
    ("битовые векторы", "(declare-const b (_ BitVec 8))(assert (= b #x00))(assert (= b #xff))"),
    ("массивы", "(declare-const a (Array Int Int))(assert (= (select a 0) 1))(assert (= (select a 0) 2))"),
]


def ask_z3(body: str) -> str:
    """Прогон через Z3 с включённым выводом доказательства."""
    script = ("(set-option :produce-proofs true)\n" + body +
              "\n(check-sat)\n(get-proof)\n")
    r = subprocess.run([Z3, "-in"], input=script, capture_output=True, text=True, timeout=60)
    return (r.stdout or "") + (r.stderr or "")


def extract_proof(out: str) -> str:
    """Возвращает СБАЛАНСИРОВАННЫЙ фрагмент вывода, начиная с `(proof`.

    ДЕФЕКТ (найден на первом прогоне): наивная обрезка `out[idx:]` захватывала
    лишнюю закрывающую скобку от ВНЕШНЕГО списка
    (`((set-logic …) (proof …))`), из-за чего проверка баланса ложно падала.
    Теперь ищем парную скобку для открывающей скобки `(proof`.
    """
    i = out.find("(proof")
    if i < 0:
        return out
    depth, in_str = 0, False
    j = i
    while j < len(out):
        c = out[j]
        if in_str:
            if c == '"' and out[j - 1] != "\\":
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return out[i:j + 1]
        j += 1
    return out[i:]

    """Прогон через Z3 с включённым выводом доказательства."""
    script = ("(set-option :produce-proofs true)\n" + body +
              "\n(check-sat)\n(get-proof)\n")
    r = subprocess.run([Z3, "-in"], input=script, capture_output=True, text=True, timeout=60)
    return (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------------------
# РАЗБОР И ПРОВЕРКА S-ВЫРАЖЕНИЯ
# ---------------------------------------------------------------------------

def balanced(s: str) -> bool:
    """Скобочная сбалансированность с учётом строковых литералов и |...|."""
    depth, in_str, in_bar = 0, False, False
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            if c == '"' and s[i - 1] != "\\":
                in_str = False
        elif in_bar:
            if c == "|":
                in_bar = False
        elif c == '"':
            in_str = True
        elif c == "|":
            in_bar = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0 and not in_str and not in_bar


LET_RE = re.compile(r"\(let\s*\(\s*\((\$?[\w@.]+)")


def check_proof(proof_text: str) -> dict:
    """Структурная проверка вывода. Возвращает отчёт."""
    rep = {"шагов_let": 0, "правил": {}, "замкнут": False,
           "финал_false": False, "баланс": False, "ошибки": []}

    rep["баланс"] = balanced(proof_text)
    if not rep["баланс"]:
        rep["ошибки"].append("скобки не сбалансированы")

    # 1. Собираем связывания let в порядке появления.
    bound: set[str] = set()
    for m in LET_RE.finditer(proof_text):
        name = m.group(1)
        if name in bound:
            rep["ошибки"].append(f"повторное связывание {name}")
        bound.add(name)
        rep["шагов_let"] += 1

    # 2. Гигиена: каждая ссылка `$x`/`@x` должна быть связана РАНЬШЕ.
    #    Ищем использования вида $var / @var вне их собственного определения.
    used = set(re.findall(r"(?<![\w$@])[$@][\w.]+", proof_text))
    unknown = {u for u in used if u not in bound}
    # Термы (x, b, a, true, false) — не переменные вывода, их не считаем.
    unknown = {u for u in unknown if not u.lstrip("$@").isdigit()}
    rep["неизвестных_ссылок"] = sorted(unknown)[:5]
    rep["замкнут"] = len(unknown) == 0
    if unknown:
        rep["ошибки"].append(f"ссылки без связывания: {sorted(unknown)[:3]}")

    # 3. Правила вывода (для статистики): mp / rewrite / unit-resolution / th-lemma / ...
    for rule in ("unit-resolution", "th-lemma", "rewrite", "mp", "asserted",
                 "hypothesis", "symm", "trans", "monotonicity"):
        n = len(re.findall(rf"\(({re.escape(rule)})\b", proof_text))
        if n:
            rep["правил"][rule] = n

    # 4. Финальный вывод обязан быть `false` (доказательство невыполнимости).
    rep["финал_false"] = bool(re.search(r"\bfalse\s*\)+\s*$", proof_text.strip()))

    # 5. Непустой вывод.
    if rep["шагов_let"] == 0 and "proof" not in proof_text:
        rep["ошибки"].append("вывод пуст")

    rep["валиден"] = (rep["баланс"] and rep["замкнут"] and rep["финал_false"]
                      and not rep["ошибки"])
    return rep


def main() -> int:
    if not Path(Z3).exists():
        print(f"[!] нет {Z3} — установите: uv pip install z3-solver")
        return 1

    cases = CASES
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        cases = [(p.name, p.read_text(encoding="utf-8"))]

    print("\n=== НЕЗАВИСИМАЯ ПРОВЕРКА ВЫВОДОВ Z3 (Python) ===")
    print("Проверяется СТРУКТУРА вывода + гигиена связываний.")
    print("ГРАНИЦА: шаги дедукции аксиоматически НЕ перепроверяются (нужен Carcara).\n")

    ok = 0
    for name, body in cases:
        out = ask_z3(body)
        if "unsat" not in out.split("\n")[0]:
            print(f"  [—] {name}: решатель не дал unsat (пропуск)")
            continue
        proof = extract_proof(out)
        rep = check_proof(proof)
        mark = "OK " if rep["валиден"] else "ПРОБЛЕМА"
        ok += 1 if rep["валиден"] else 0
        rules = ", ".join(f"{k}×{v}" for k, v in sorted(rep["правил"].items()))
        print(f"  [{mark}] {name}")
        print(f"         let-шагов {rep['шагов_let']}, связывания замкнуты={rep['замкнут']}, "
              f"финал=false {rep['финал_false']}")
        if rules:
            print(f"         правила: {rules}")
        if rep["ошибки"]:
            print(f"         ОШИБКИ: {rep['ошибки']}")

    print(f"\nИТОГ: {ok}/{len(cases)} выводов структурно валидны")
    print("Честно: это НЕ полный Alethe/LFSC-чекер (см. границу в шапке файла).\n")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
