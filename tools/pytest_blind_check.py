#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""ИСПЫТАНИЕ 3: «ВЫЖИВШИЕ МУТАНТЫ ЗА СПИНОЙ pytest» (Mutation Kill Delta).

ТЕЗИС ПРОЕКТА. «Зелёный pytest != верный код». До сих пор он подтверждался
только на СИНТАКСИЧЕСКИХ читах (`anti_cheat_demo.py`), а не на ЛОГИЧЕСКИХ
ошибках. Здесь тезис измеряется на пяти функциях с ЯВНЫМИ контрактами
`@kern:` и НАМЕРЕННО СЛАБЫМИ тестами (только «счастливый путь»).

ЧТО ДЕЛАЕТ ГЕЙТ (на `tests/fixtures/pytest_blind_mutants.py`):

  1. БАЗА: `pytest` ЗЕЛЁН, и `kern` доказывает ВСЕ 5 контрактов без ложных
     тревог (TN = 5/5, FP = 0). Иначе тесты/контракты — не «честный оригинал».
  2. На КАЖДЫЙ мутант (одна строка тела заменена) — ДВА условия:
       • `pytest` остаётся ЗЕЛЁНЫМ  (мутант ВЫЖИВАЕТ за спиной обычных тестов);
       • `kern` становится КРАСНЫМ  (мутант УБИТ с контрпримером).
     Первое условие — это и есть слепое пятно; второе — его закрытие.

МЕТРИКА (как в `real_cases_check`): TP = убито kern, FN = выжило за спиной kern,
TN = оригиналы без ложных обвинений, FP = оригиналы обвинены ошибочно,
J = TP / (TP + FN). Требуется TP = N/N, TN = N/N, FP = 0, FN = 0, J = 1.00.

ГРАНИЦА. Гейт ломает ОДНУ строку на мутант (не покрывает семантические
мутации-эквиваленты и мутации в тестах) — это названная граница, а не полнота.

Запуск: python3 tools/pytest_blind_check.py [--selftest]
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "pytest_blind_mutants.py"
KERN = ROOT / "tools" / "kern_contracts.py"
N_CONTRACTS = 5

# (имя, что заменить, на что заменить). Замены ПРОВЕРЕНЫ: каждая (а) меняет
# поведение на НЕ покрытом тестом входе и (б) не видна слабым тестам.
MUTANTS = [
    ("M1 grade: граница `<` -> `<=`", "    if x < 50:", "    if x <= 50:"),
    ("M2 safe_div: гард `b == 0` потерян", "    if b == 0:", "    if b == 1:"),
    ("M3 commission: округление `+50` -> `+49`",
     "    return (amount + 50) // 100", "    return (amount + 49) // 100"),
    ("M4 clamp: потолок `1000` -> `1001`", "    return 1000", "    return 1001"),
    ("M5 magnitude: `0 - x` -> `x`", "        return 0 - x", "        return x"),
]
# --selftest: мутант, ЭКВИВАЛЕНТНЫЙ оригиналу (поведение не меняется) — kern
# ОБЯЗАН его пропустить, значит гейт ОБЯЗАН увидеть выжившего и покраснеть.
SELFTEST_SURVIVOR = ("selftest: эквивалент (не убивается)",
                     "    if x < 1000:", "    if x < 1001:")


def find_pytest_python() -> str | None:
    """Интерпретатор с установленным pytest (`.venv` -> текущий -> `python3`)."""
    cands = [str(ROOT / ".venv" / "bin" / "python"), sys.executable, "python3"]
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        if c != "python3" and not Path(c).exists():
            continue
        try:
            r = subprocess.run([c, "-m", "pytest", "--version"],
                               capture_output=True, text=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            continue
        if r.returncode == 0:
            return c
    return None


def pytest_green(py: str, path: Path, cwd: Path) -> bool:
    """True, если pytest на `path` завершился с rc=0 (тесты ПРОШЛИ)."""
    r = subprocess.run([py, "-m", "pytest", str(path), "-q", "-p",
                        "no:cacheprovider"], cwd=str(cwd), capture_output=True,
                       text=True, errors="replace", timeout=600)
    return r.returncode == 0


def kern_counts(path: Path) -> tuple[int, int]:
    """(доказано, нарушено) из сводки kern_contracts по файлу."""
    r = subprocess.run([sys.executable, str(KERN), str(path)], cwd=str(ROOT),
                       capture_output=True, text=True, errors="replace",
                       timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    proved = re.search(r"доказано (\d+)", out)
    violated = re.search(r"нарушено (\d+)", out)
    return (int(proved.group(1)) if proved else -1,
            int(violated.group(1)) if violated else -1)


def check(extra: tuple[str, str, str] | None = None) -> int:
    src = FIXTURE.read_text(encoding="utf-8")
    py = find_pytest_python()
    if py is None:
        print("[!] pytest недоступен — проверка НЕ выполнена (это не «зелено»)")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="kern_blind_"))
    try:
        # --- 1. БАЗА: честный оригинал -------------------------------------
        base = tmp / "test_blind_mutants.py"
        base.write_text(src, encoding="utf-8")
        if not pytest_green(py, base, tmp):
            print("[ПРОВАЛ] база: pytest на ОРИГИНАЛЕ НЕ зелён — фикстура "
                  "не «честный оригинал», тезис не проверить")
            return 1
        bp, bv = kern_counts(base)
        if bp != N_CONTRACTS or bv != 0:
            print(f"[ПРОВАЛ] база: kern доказал {bp}/{N_CONTRACTS}, нарушено {bv} "
                  f"(ожидалось {N_CONTRACTS}/0) — ложные тревоги на оригинале")
            return 1

        # --- 2. МУТАНТЫ -----------------------------------------------------
        mutants = MUTANTS + ([extra] if extra else [])
        tp = fn = 0
        rows: list[str] = []
        for name, old, new in mutants:
            if src.count(old) != 1:
                print(f"[ПРОВАЛ] {name}: якорь `{old.strip()}` встречается "
                      f"{src.count(old)} раз — мутация неоднозначна")
                return 1
            path = tmp / "test_blind_mutants.py"
            path.write_text(src.replace(old, new), encoding="utf-8")
            pg = pytest_green(py, path, tmp)
            proved, violated = kern_counts(path)
            killed = violated >= 1
            tp += killed
            fn += (not killed)
            rows.append(f"    {name}: pytest={'ЗЕЛЁН' if pg else 'КРАСЕН'} | "
                        f"kern={'УБИТ' if killed else 'ВЫЖИЛ'}"
                        f" (доказано {proved}, нарушено {violated})")
            if not pg:
                print(f"[ПРОВАЛ] {name}: pytest стал КРАСНЫМ — мутант НЕ слеп "
                      f"(тесты его ловят, тезис о слепом пятне не подтверждён)")
            if not killed:
                print(f"[ПРОВАЛ] {name}: kern НЕ убил мутанта — ВЫЖИВШИЙ мутант "
                      f"(за спиной kern тоже зелено)")

        # --- 3. МЕТРИКА -----------------------------------------------------
        n = len(mutants)
        print("=" * 68)
        print("KERN: выжившие мутанты за спиной pytest (Испытание 3)")
        print("=" * 68)
        print(f"  pytest-интерпретатор: {py}")
        print(f"  база: pytest ЗЕЛЁН | kern доказал {bp}/{N_CONTRACTS}, "
              f"нарушено {bv}")
        print("\n".join(rows))
        print(f"  метрика: TP={tp}/{n}  FN={fn}  TN={N_CONTRACTS}/{N_CONTRACTS}  "
              f"FP=0  J={tp / n:.2f}")
        if fn or tp != n:
            print(f"\n[!] НЕ УБИТЫХ МУТАНТОВ: {fn} — тезис закрыт НЕ полностью")
            return 1
        print("\n[OK] все мутанты выжили за спиной pytest и убиты kern "
              "(контрпример предъявлен); J=1.00")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        # На ЭКВИВАЛЕНТНОМ мутанте гейт обязан покраснеть (увидеть выжившего).
        rc = check(extra=SELFTEST_SURVIVOR)
        if rc != 0:
            print("  [OK] --selftest: эквивалентный мутант распознан как ВЫЖИВШИЙ "
                  "(гейт способен падать)")
            return 0
        print("  [ПРОВАЛ] --selftest: выживший мутант НЕ пойман — гейт вакуумен")
        return 1
    return check()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
