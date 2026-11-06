#!/usr/bin/env python3
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
BASELINE_NO_TIMEOUT = 51
ALLOWED_FILES = {"spawn.py", "z3bin.py"}
CALL_NAMES = {"run", "Popen", "call", "check_output", "check_call"}


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


def main() -> int:
    bad = scan()
    n = len(bad)
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
