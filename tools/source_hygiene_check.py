#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Хигиена исходников: управляющих байт в СТРОКОВЫХ КОНСТАНТАХ быть не должно.

ДЕФЕКТ #413. В `tools/kern_contracts.py` шесть раз вместо границы слова `\\b`
стоял ЛИТЕРАЛЬНЫЙ backspace (0x08): в raw-строке Python это не escape, а сам
символ, которого в исходниках не бывает, поэтому такие регулярки не совпадали
НИКОГДА. Так родились МЁРТВЫЕ дубликаты правил C (переполнение `uint16`-поля,
CVE-класс `ac80f7b`) и D (off-by-one `<=` ёмкости) внутри цикла, а также точная
перепись насыщения `+|` / `-|` (`_saturate_rewrite`), которая не выполнялась ни
разу, хотя её докстрока утверждала обратное.

ЧТО ПРОВЕРЯЕТСЯ. В AST каждого `tools/*.py` ни одна строковая константа не
содержит управляющих символов C0, кроме `\\n`, `\\t`, `\\r` (они осмысленны в
шаблонах и сообщениях). Это ХРАПОВИК: класс «невидимый байт убил регулярку»
больше не может вернуться молча.

ГРАНИЦА (честно). Проверяются СТРОКОВЫЕ КОНСТАНТЫ в AST, а не текст файла:
упоминание байта в комментарии или в докстроке — это ОПИСАНИЕ, а не работающий
шаблон, и запрещать его значило бы запретить объяснять сам дефект.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
# КЛАСС ДЕФЕКТА (#413) — ИМЕННО ЛИТЕРАЛЬНЫЙ BACKSPACE. Сужаю сознательно:
# ИЗМЕРЕНО, что в `tools/*.py` есть и другие управляющие байты, и они ЗАКОННЫ:
#   * 0x1b (ESC) — ANSI-цвета в `registry.py` и `canfail.py` (7 мест);
#   * 0x00 (NUL) — намеренные БАЙТОВЫЕ тесты (`ai_traces_check.py`,
#     `oracle_string_check.py`, `secrets_check.py`).
# Запрещать их значило бы ломать работающий код ради красоты правила. Поэтому
# храповик ловит РОВНО тот байт, который родился из забытого `r` перед `"\b"`,
# и делает это по ВСЕМ строкам, а не по эвристике «похоже на шаблон».
FORBIDDEN = {0x08: "0x08 (литеральный backspace — забыт `r` перед `\"\\b\"`)"}


def scan_text(name: str, src: str) -> list[tuple[str, int, str]]:
    """Управляющие символы в строковых константах: [(файл, строка, код)]."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(name, e.lineno or 0, "SyntaxError")]
    bad: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for ch in node.value:
            code = ord(ch)
            if code not in FORBIDDEN:
                continue
            bad.append((name, getattr(node, "lineno", 0), f"0x{code:02x}"))
            break
    return bad


def scan_files(paths) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for p in paths:
        try:
            out += scan_text(p.name, p.read_text(encoding="utf-8"))
        except OSError:
            continue
    return out


def selftest() -> int:
    """Мета-тест: храповик ОБЯЗАН покраснеть на подсаженном байте."""
    bad_byte = chr(0x08)
    dirty = f'import re\nP = re.compile(r"{bad_byte}(\\w+)")\n'
    clean = 'import re\nP = re.compile(r"\\b(\\w+)")\n'
    ok = True
    got = scan_text("dirty.py", dirty)
    if not got or got[0][2] != "0x08":
        print(f"  [FAIL] подсаженный 0x08 НЕ найден: {got}")
        ok = False
    else:
        print(f"  [OK]   подсаженный 0x08 найден: строка {got[0][1]}")
    if scan_text("clean.py", clean):
        print("  [FAIL] чистая регулярка ложно обвинена")
        ok = False
    else:
        print("  [OK]   чистая регулярка не обвинена")
    # Граница: упоминание байта В КОММЕНТАРИИ — это описание, а не шаблон.
    comment = f"# дефект: байт {bad_byte} вместо границы слова\nX = 1\n"
    if scan_text("comment.py", comment):
        print("  [FAIL] упоминание в комментарии обвинено (нарушена граница)")
        ok = False
    else:
        print("  [OK]   упоминание в комментарии не обвиняется")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        print("KERN: мета-тест храповика против управляющих байт")
        return selftest()
    bad = scan_files(sorted(TOOLS.glob("*.py")))
    if bad:
        print(f"[!] #413: управляющие байты в строковых константах: {len(bad)}")
        for name, ln, code in bad:
            print(f"    {name}:{ln}: {code} (литеральный backspace вместо \\b?)")
        print("    Лечение: замените байт на `\\\\b` в raw-строке.")
        return 1
    n = len(list(TOOLS.glob("*.py")))
    print(f"[OK] #413: в {n} файлах tools/*.py нет управляющих байт в строковых константах")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
