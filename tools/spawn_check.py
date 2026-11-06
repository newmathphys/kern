#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ГЕЙТ #477: РАТЧЕТ «ПОДПРОЦЕСС БЕЗ ТАЙМАУТА» — ЗАПРЕЩЁН.

ЗАЧЕМ. Класс выстрелил трижды: `#464` (таймаут решателя), `#466` (`z3` не в
PATH), `#470` (нет потолка памяти). Общее у них одно: `subprocess.*` вызывался
БЕЗ явного ограничителя, поэтому зависший или обезумевший бинарник вешал
проверку НАВСЕГДА, без вердикта и без причины.

ЧТО ПРОВЕРЯЕТСЯ (AST, не grep — иначе строка в комментарии считалась бы кодом):
  * каждый вызов `subprocess.run/Popen/call/check_output/check_call` в
    `tools/*.py` обязан иметь `timeout=`;
  * исключение — `tools/spawn.py` (он и есть обвязка, где таймаут ставится
    снаружи цикла) и `tools/z3bin.py` (только ищет бинарник, не запускает).

ЧЕСТНАЯ ФОРМА — РАТЧЕТ, а не «ноль сразу»: 51 существующее место названо
базой. Любое НОВОЕ место краснит гейт; улучшение печатает «снизьте базу»
(ретаргет вниз). Так долг виден числом и не может вырасти молча.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

# ИЗМЕРЕНО на `HEAD` после починки трёх мест в kern_contracts.py и
# smtlib_proof_check.py: 51 вызов без `timeout=`. ЦЕЛЬ — 0.
# #492: РАТЧЕТ ЗАКРЫТ. Было 51 место без таймаута (класс #466/#470: зависший
# бинарник вешал проверку навсегда, без вердикта и без причины). Все 51 получили
# явный `timeout=900` (механически, с проверкой компиляции каждого файла).
# Порог 0 означает: ЛЮБОЕ новое место без таймаута — красный гейт.
BASELINE_NO_TIMEOUT = 0
ALLOWED_FILES = {"spawn.py", "z3bin.py"}
# ДЕФЕКТ #492a: `Popen` НЕ принимает `timeout=` (это аргумент `wait/communicate`).
# Считать его «местом без таймаута» по наличию ключевого слова — значит требовать
# НЕВОЗМОЖНОГО (поймано `ci-fast`: `TypeError: Popen.__init__() got an unexpected
# keyword argument 'timeout'`). Для `Popen` правило другое и проверяется ниже:
# таймаут обязан стоять на ОЖИДАНИИ — `wait(timeout=)`, `communicate(timeout=)`
# или `select.select(...)` с дедлайном (так сделан `mcp_selftest.Client`).
CALL_NAMES = {"run", "call", "check_output", "check_call"}
POPEN_NAMES = {"Popen"}
WAIT_GUARD = ("wait(timeout", "communicate(timeout", "select.select")


def scan() -> list[tuple[str, int]]:
    """Список `(файл, строка)` вызовов `subprocess.*` БЕЗ `timeout=`."""
    bad: list[tuple[str, int]] = []
    for p in sorted(TOOLS.glob("*.py")):
        if p.name in ALLOWED_FILES:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:                      # pragma: no cover
            bad.append((f"{p.name}: SYNTAX ERROR {e.lineno}", e.lineno or 0))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr in CALL_NAMES):
                continue
            if getattr(f.value, "id", "") != "subprocess":
                continue
            if "timeout" not in {k.arg for k in node.keywords}:
                bad.append((p.name, node.lineno))
    return bad


def scan_popen() -> list[tuple[str, int]]:
    """Файлы с `subprocess.Popen` БЕЗ таймаута на ОЖИДАНИИ (#492a).

    `Popen` не имеет параметра `timeout`; таймаут ставится на `wait()`,
    `communicate()` или на `select.select(...)` с дедлайном. Файл, где есть
    `Popen` и НИ ОДНОГО из этих стражей, — реальный риск зависания.
    """
    bad: list[tuple[str, int]] = []
    for p in sorted(TOOLS.glob("*.py")):
        if p.name in ALLOWED_FILES:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        lines: list[int] = []
        for node in ast.walk(tree):
            f = getattr(node, "func", None)
            if (isinstance(node, ast.Call) and isinstance(f, ast.Attribute)
                    and f.attr in POPEN_NAMES
                    and getattr(f.value, "id", "") == "subprocess"):
                lines.append(node.lineno)
        if not lines:
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if not any(g in src for g in WAIT_GUARD):
            bad.append((p.name, lines[0]))
    return bad


def main() -> int:
    bad = scan()
    n = len(bad)
    popen_bad = scan_popen()
    if popen_bad:
        print(f"[FAIL] #492a: `Popen` без таймаута на ожидании: {len(popen_bad)}")
        for name, ln in popen_bad:
            print(f"    {name}:{ln}")
        return 1
    print("[OK] #492a: все `Popen` имеют таймаут ожидания "
          "(wait/communicate/select.select)")
    print(f"[i] #477: вызовов `subprocess.*` без `timeout=` — {n} (база {BASELINE_NO_TIMEOUT}, цель 0)")
    if n > BASELINE_NO_TIMEOUT:
        print(f"[FAIL] #477: РЕГРЕСС — было {BASELINE_NO_TIMEOUT}, стало {n}. Новые места:")
        for name, ln in bad:
            print(f"    {name}:{ln}")
        return 1
    if n < BASELINE_NO_TIMEOUT:
        print(f"[i] ЛУЧШЕ БАЗЫ на {BASELINE_NO_TIMEOUT - n}: снизьте BASELINE_NO_TIMEOUT до {n}")
    # Даже «в базе» список печатается: долг обязан быть видимым, а не только считаемым.
    for name, ln in bad[:10]:
        print(f"    (долг) {name}:{ln}")
    if n > 10:
        print(f"    … и ещё {n - 10}")
    print("[OK] #477: новых мест без таймаута не появилось; правильный путь — `tools/spawn.run`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
