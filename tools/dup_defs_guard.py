#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Страж от ДУБЛИРУЮЩИХСЯ определений (дефект #174).

ЗАЧЕМ. В `tools/kern_contracts.py` исторически накопилось 51 имя, определённое
ДВАЖДЫ (2024 строки мёртвого кода). Python использует ПОСЛЕДНЕЕ определение,
поэтому правка в первой копии **молча не работает** — именно так правки
`--xray` выглядели применёнными, но не действовали.

Полная перестройка файла — отдельная работа с полным прогоном гейтов; здесь
мы делаем **ratchet**: фиксируем текущее состояние в базисе и запрещаем его
УХУДШАТЬ. Новый дубликат (или третья копия) → `rc=1`.

  python3 tools/dup_defs_guard.py            # проверить (rc=1 при росте долга)
  python3 tools/dup_defs_guard.py --baseline # перезаписать базис (осознанно)

ЧЕСТНО: страж НЕ чинит дубликаты и НЕ считает их нормой — он лишь не даёт
долгу расти, пока идёт перестройка.
"""
from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tools" / "kern_contracts.py"
BASELINE = ROOT / "tools" / "dup_defs_baseline.json"


def counts() -> Counter:
    tree = ast.parse(TARGET.read_text(encoding="utf-8"))
    names = [n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return Counter(names)


def main() -> int:
    cur = counts()
    dup_now = {k: v for k, v in cur.items() if v > 1}

    if "--baseline" in sys.argv[1:]:
        BASELINE.write_text(json.dumps(dict(sorted(dup_now.items())), indent=1) + "\n",
                            encoding="utf-8")
        print(f"[ok] базис записан: {len(dup_now)} дублирующихся имён -> {BASELINE}")
        return 0

    if not BASELINE.is_file():
        print(f"[!] нет базиса {BASELINE} — создайте: python3 tools/dup_defs_guard.py --baseline")
        return 2
    base = json.loads(BASELINE.read_text(encoding="utf-8"))

    grew = []
    for name, n in dup_now.items():
        was = base.get(name, 1)
        if n > was:
            grew.append(f"{name}: было {was} определений, стало {n}")
    added = [name for name in dup_now if name not in base]

    if grew or added:
        print("[!] ДОЛГ ДУБЛИКАТОВ ВЫРОС (дефект #174):")
        for x in grew:
            print("   -", x)
        for x in added:
            print(f"   - {x}: новый дубликат (не было в базисе)")
        print("   Python исполняет ПОСЛЕДНЕЕ определение: правки в первой копии")
        print("   не работают. Уберите дубликат или (осознанно) обновите базис.")
        return 1

    print(f"[ok] дубликатов {len(dup_now)} — не больше базиса ({len(base)}); "
          f"всего определений {sum(cur.values())}, уникальных {len(cur)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
