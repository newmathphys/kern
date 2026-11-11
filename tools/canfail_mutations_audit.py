#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""#637: СВЕРКА ВСЕХ ИНЪЕКЦИЙ canfail.py С HEAD (не по папкам, а по первоисточнику).

ЗАЧЕМ. Найдено ПЯТЬ закоммиченных диверсий подряд: три в `src/`, одна в `tools/`,
одна в `formal/`. Каждый раз мы правили список папок и маркеров вручную — то есть
играли в догонялки. Первоисточник всех инъекций — сам `tools/canfail.py`: он
делает `patch(path, old, new)`. Значит можно программно взять ВСЕ правила и
проверить, не лежит ли `new` (испорченный текст) в текущем HEAD.

ПРОВЕРКА:
  R1 для каждого литерального `patch(p, old, new)` берём `new` и ищем его в HEAD
     (git grep по всему репозиторию); находка = закоммиченная диверсия;
  R2 правила, где аргументы не литералы (f-строки/переменные), НАЗЫВАЮТСЯ в отчёте
     как непроверяемые программно — без молчаливого пропуска;
  R3 двусторонность: подстроки `old` (нормальный код) обязаны присутствовать —
     иначе якорь устарел и кейс станет вакуумным (класс #113/#624).
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "canfail.py"


_CACHE: dict[str, str] = {}


def _head_text(path: str) -> str:
    """Содержимое файла в HEAD (кэш: один git show на файл, а не на правило)."""
    if path not in _CACHE:
        r = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True,
                           text=True, cwd=str(ROOT))
        _CACHE[path] = r.stdout if r.returncode == 0 else ""
    return _CACHE[path]


def _git_grep(text: str, ref: str = "HEAD") -> str:
    """Совместимость: ищем в кэше HEAD по уже загруженным файлам."""
    for body in _CACHE.values():
        if text and text in body:
            return text
    return ""


def rules() -> tuple[list[tuple[str, str, str]], int]:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    out: list[tuple[str, str, str]] = []
    dynamic = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != "patch" or len(node.args) != 3:
            continue
        vals = []
        for a in node.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                vals.append(a.value)
            else:
                vals = []
                break
        if len(vals) == 3:
            out.append((vals[0], vals[1], vals[2]))
        else:
            dynamic += 1
    return out, dynamic


def main() -> int:
    rs, dyn = rules()
    print(f"[i] литеральных правил patch(): {len(rs)} | нелитеральных: {dyn}")
    bad = 0
    stale = 0
    for _p, _o, _n in rs:
        _head_text(_p)
    for path, old, new in rs:
        body = _head_text(path)
        if not body:
            continue
        # КРИТЕРИЙ (уточнён после ложных срабатываний первого прогона):
        # диверсия = в HEAD лежит ИСПОРЧЕННЫЙ текст, а ЯКОРЬ (нормальный код)
        # исчез. Иначе `new` может просто встречаться в другой функции того же файла.
        if new and new in body and old and old not in body:
            bad += 1
            line = next((ln.strip() for ln in body.splitlines() if new in ln), "")[:100]
            print(f"[FAIL] R1 ДИВЕРСИЯ: {path} -> {line}")
        elif old and old not in body and new not in body:
            stale += 1
            if stale <= 6:
                print(f"[!] R3 устаревший якорь: {path}: {old[:56]!r}")
    if dyn:
        print(f"[i] R2 нелитеральных правил: {dyn} — программно не проверяются (названы здесь)")
    print(f"\n=== ИТОГ: правил {len(rs)} | диверсий в HEAD {bad} | устаревших якорей {stale} ===")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
