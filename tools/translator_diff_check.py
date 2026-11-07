#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""KERN gate: ДИФФЕРЕНЦИАЛЬНАЯ ПРОВЕРКА ЗВУЧИМОСТИ ПЕРЕВОДА (Испытание 1, класс #349).

ЗАЧЕМ ЭТОТ ГЕЙТ СУЩЕСТВУЕТ.

Дефект #349: в SMT-LIB2 `(div a b)`/`(mod a b)` — ЕВКЛИДОВЫ (остаток всегда
неотрицателен), а в C/Rust/Go/JS целочисленное деление — УСЕЧЕНИЕ К НУЛЮ
(знак остатка совпадает со знаком делимого). Транслятор однажды перевёл C-путь
через питоновское `//` (округление к -inf) и «доказал» ложь: для `a = -7, b = 2`
он утверждал `-7 / 2 == -4` и `-7 % 2 == +1`, тогда как живой `gcc` возвращает
`-3` и `-1`.

Существующие гейты (`arith-semantics-check`) сверяют АДАПТЕРЫ против таблицы
семантики, но требуют питоновского пакета `z3`. Этот гейт устроен иначе и
потому проверяет ИНУЮ грань:

  * эталон берётся у ЖИВОГО компилятора/рантайма (`gcc`/`rustc`/`node`),
    а не у таблицы;
  * проверяется ВЕСЬ конвейер `tools/kern_contracts.py` на внешнем файле,
    а не отдельная функция перевода;
  * решателем служит Зиг-ядро `kernc`, поэтому питоновский `z3` не нужен.

ЧТО ПРОВЕРЯЕТСЯ (матрица выражений и четыре квадранта знаков).

  1. `a / b` и `a % b` при `(7,2), (-7,2), (7,-2), (-7,-2)` — ЯДРО класса #349;
  2. левоассоциативное вычитание `a - b - 3`, унарный минус `-a + b`, `-(a + b)`;
  3. тернарник `a > b ? a : b`;
  4. `if / else` и ВЛОЖЕННЫЙ `if / else` (`if { if {…} else {…} } else {…}`);
  5. побитовые `& | ^ << >>` (маршрут QF_BV).

Для каждой точки:
  • `ensures result == <живое значение>`  -> ОБЯЗАНО быть `[PASS]`;
  • `ensures result == <питоновское значение>` (ЛОВУШКА) -> ОБЯЗАНО НЕ быть
    `[PASS]`: если бы C-путь снова стал floor, гейт покраснел бы.

ОТКАЗ ЧЕСТНЫЙ. Если живого компилятора нет — точка НАЗЫВАЕТСЯ пропущенной
(`SKIP`), а не «проверенной». Выход 1 — только при РАСХОЖДЕНИИ или при
ПРОЙДЕННОЙ ловушке.

Запуск:  python3 tools/translator_diff_check.py [--selftest]
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "tools" / "kern_contracts.py"

# Четыре квадранта знаков — то место, где усечение и floor расходятся.
QUADRANTS = ((7, 2), (-7, 2), (7, -2), (-7, -2))
# Положительные пары для побитовых (усечение знака там не участвует).
BIT_PAIRS = ((7, 3), (12, 5), (6, 10))

# Выражения с ОДИНАКОВЫМ синтаксисом в C/Rust/JS.
COMMON = (
    ("sub_assoc", "a - b - 3"),
    ("unary", "-a + b"),
    ("unary_paren", "-(a + b)"),
    ("ternary", "a > b ? a : b"),
)
BITWISE = (
    ("band", "a & b"),
    ("bor", "a | b"),
    ("bxor", "a ^ b"),
    ("shl", "a << 1"),
    ("shr", "a >> 1"),
)
# Операторы-СТАТЕМЕНТЫ (тело функции целиком).
STMT = (
    ("ifelse", "if (a > b) { return a; } else { return b; }"),
    ("nested",
     "if (a > b) { if (a > 0) { return a; } else { return -a; } } else { return b; }"),
)



def div_expr(lang: str) -> str:
    # В JS `/` — ВЕЩЕСТВЕННОЕ, поэтому усечение к нулю выражается `| 0`.
    return "(a / b) | 0" if lang == "js" else "a / b"


def mod_expr(lang: str) -> str:
    return "a % b"


# --- ЖИВОЙ ЭТАЛОН -----------------------------------------------------------
def live_value(lang: str, body: str, va: int, vb: int):
    """Значение `body` (тело функции `f(a, b)`) у ЖИВОГО компилятора.

    `None` — компилятора нет либо сборка/запуск не удались (точка пропускается).
    """
    exe = {"c": shutil.which("gcc"), "rust": shutil.which("rustc"),
           "js": shutil.which("node")}[lang]
    if exe is None:
        return None
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        if lang == "c":
            src = d / "m.c"
            src.write_text(
                "#include <stdio.h>\n"
                f"static long f(long a, long b) {{ {body} }}\n"
                f"int main(void) {{ printf(\"%ld\\n\", f({va}L, {vb}L)); return 0; }}\n",
                encoding="utf-8")
            out = d / "m"
            cc = subprocess.run([exe, "-O0", "-w", "-o", str(out), str(src)],
                                capture_output=True, text=True, timeout=60)
            if cc.returncode != 0:
                return None
            run = subprocess.run([str(out)], capture_output=True, text=True, timeout=30)
        elif lang == "rust":
            src = d / "m.rs"
            src.write_text(
                f"fn f(a: i64, b: i64) -> i64 {{ {body} }}\n"
                f"fn main() {{ println!(\"{{}}\", f({va}, {vb})); }}\n",
                encoding="utf-8")
            out = d / "m"
            cc = subprocess.run([exe, "-A", "warnings", "-o", str(out), str(src)],
                                capture_output=True, text=True, timeout=120)
            if cc.returncode != 0:
                return None
            run = subprocess.run([str(out)], capture_output=True, text=True, timeout=30)
        else:
            src = d / "m.js"
            src.write_text(f"function f(a, b) {{ {body} }}\n"
                           f"console.log(f({va}, {vb}));\n", encoding="utf-8")
            run = subprocess.run([exe, str(src)], capture_output=True, text=True,
                                 timeout=30)
        if run.returncode != 0:
            return None
        m = re.search(r"-?\d+", run.stdout)
        return int(m.group(0)) if m else None


def kernel_source(lang: str, body: str, va: int, vb: int, expected: int) -> str:
    """Внешний файл с контрактом для `tools/kern_contracts.py`."""
    head = (f"// @kern:requires a == {va} and b == {vb}\n"
            f"// @kern:ensures result == {expected}\n")
    if lang == "c":
        return head + f"int f(int a, int b) {{ {body} }}\n"
    if lang == "rust":
        return head + f"fn f(a: i32, b: i32) -> i32 {{ {body} }}\n"
    return head + f"function f(a, b) {{ {body} }}\n"


def translator_says_pass(src_text: str, suffix: str) -> bool:
    """Прогнать внешний файл через ВЕСЬ конвейер и вернуть «[PASS] f: ДОКАЗАНО»."""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / f"t{suffix}"
        f.write_text(src_text, encoding="utf-8")
        p = subprocess.run([sys.executable, str(KERNC), str(f)],
                           capture_output=True, text=True, errors="replace",
                           cwd=str(ROOT), timeout=300)
    out = (p.stdout or "") + (p.stderr or "")
    return re.search(r"\[PASS\]\s+f:\s*ДОКАЗАНО", out) is not None

LANGS = ("c", "rust", "js")
EXT = {"c": ".c", "rust": ".rs", "js": ".js"}


def _py_expr(lang: str, name: str, body: str) -> str:
    """Выражение ЛОВУШКИ в питоновской семантике (floor)."""
    if name == "div":
        return "a // b"
    if name == "mod":
        return "a % b"
    return body.removeprefix("return ").removesuffix(";")


def py_value(expr: str, va: int, vb: int) -> int:
    """ПИТОНОВСКАЯ (floor) семантика выражения — источник ЛОВУШКИ."""
    return int(eval(expr, {"__builtins__": {}}, {"a": va, "b": vb}))  # noqa: S307


def _selftest() -> int:
    """Мета-тест НЕВАКУУМНОСТИ: неверное ожидание ОБЯЗАНО быть опровергнуто.

    Изолирован от основной матрицы (одна точка) — иначе мета-тест сам стал бы
    долгим прогоном. Названный SKIP при отсутствии gcc: это не «зелено».
    """
    live = live_value("c", "return a / b;", -7, 2)
    if live is None:
        print("  [!] --selftest: нет gcc — мета-тест не выполним (названный SKIP)")
        return 1
    bad = kernel_source("c", "return a / b;", -7, 2, live + 1)
    if not translator_says_pass(bad, EXT["c"]):
        print(f"  [OK] --selftest: неверное ожидание {live + 1} НЕ доказано "
              f"(гейт способен падать)")
        return 0
    print("  [FAIL] --selftest: неверное ожидание объявлено ДОКАЗАННЫМ")
    return 1


def check(sabotage: bool = False) -> int:
    if sabotage:
        return _selftest()
    fails: list[str] = []
    live_points = traps = skips = 0

    def one(lang: str, name: str, body: str, va: int, vb: int, live: int) -> None:
        nonlocal live_points, traps
        live_points += 1
        if not translator_says_pass(kernel_source(lang, body, va, vb, live), EXT[lang]):
            fails.append(f"{lang}/{name}({va},{vb}): живое значение {live} "
                         f"НЕ доказано — перевод расходится с компилятором")
        try:
            pv = py_value(_py_expr(lang, name, body), va, vb)
        except (ArithmeticError, SyntaxError, ValueError, TypeError, NameError) as e:
            # класс #198/#457: здесь ОЖИДАЕМЫ только «выражение не вычислимо»
            # (деление на ноль = ArithmeticError, разбор = SyntaxError, нет имени
            # = NameError, приведение = ValueError/TypeError). Программные и
            # средовые ошибки (AttributeError/ImportError/OSError) НЕ глушим:
            # иначе сломанный харнесс выглядел бы как «ловушки нет».
            print(f"  [i] {lang}/{name}: выражение не вычислимо ({e!r}) — ловушка пропущена")
            return
        if pv == live:
            return
        traps += 1
        if translator_says_pass(kernel_source(lang, body, va, vb, pv), EXT[lang]):
            fails.append(f"{lang}/{name}({va},{vb}): ЛОВУШКА ПРОЙДЕНА — "
                         f"floor-значение {pv} объявлено доказанным (класс #349)")

    for lang in LANGS:
        for name, mk in (("div", div_expr), ("mod", mod_expr)):
            body = f"return {mk(lang)};"
            for va, vb in QUADRANTS:
                live = live_value(lang, body, va, vb)
                if live is None:
                    skips += 1
                    continue
                one(lang, name, body, va, vb, live)
        for name, expr in COMMON + BITWISE:
            # У Rust НЕТ тернарного оператора `?:` — это свойство языка, а не
            # отсутствие компилятора, поэтому конструкция не «пропускается», а
            # не существует (её роль играет `if/else`-выражение в STMT).
            if lang == "rust" and name == "ternary":
                continue
            pairs = BIT_PAIRS if name in {b[0] for b in BITWISE} else QUADRANTS
            for va, vb in pairs:
                live = live_value(lang, f"return {expr};", va, vb)
                if live is None:
                    skips += 1
                    continue
                one(lang, name, f"return {expr};", va, vb, live)
        for name, stmt in STMT:
            # В Rust тернарного оператора НЕТ (роль играет `if c { a } else { b }`),
            # поэтому точка не «падает по компиляции», а не проверяется осознанно.
            if name == "ternary" and lang == "rust":
                continue
            for va, vb in QUADRANTS:
                live = live_value(lang, stmt, va, vb)
                if live is None:
                    skips += 1
                    continue
                one(lang, name, stmt, va, vb, live)

    print("=" * 68)
    print("KERN: дифференциальная проверка звучимости перевода (Испытание 1)")
    print("=" * 68)
    for lang in LANGS:
        exe = {"c": shutil.which("gcc"), "rust": shutil.which("rustc"),
               "js": shutil.which("node")}[lang]
        print(f"  эталон {lang:4s}: {exe or 'НЕТ — точки этого языка пропущены'}")
    print(f"  живых точек: {live_points} | ловушек: {traps} | названных SKIP: {skips}")
    if fails:
        print(f"\n[!] РАСХОЖДЕНИЙ: {len(fails)}")
        for x in fails:
            print(f"    {x}")
        return 1
    if live_points == 0:
        print("\n[!] ни одного живого компилятора — проверка НЕ выполнена")
        return 1
    print("\n[OK] перевод совпал с живыми компиляторами; ловушки НЕ пройдены")
    return 0


def main(argv: list[str]) -> int:
    return check(sabotage="--selftest" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

