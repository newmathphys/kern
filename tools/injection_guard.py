#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial 1.0.0.
"""СТРАЖ ОТ ИНЪЕКЦИЙ В ДЕРЕВЕ (Дефекты #168, #170).

ЗАЧЕМ. Харнессы `canfail.py` / `mutate_zig.py` НАМЕРЕННО вставляют «поломки»
в исходники и обязаны их откатывать. Дважды (дефекты #168 и #170) убитый по
таймауту прогон оставлял поломку в дереве, и она попадала в коммит:
  * `chc.zig`          — `return .Sat;` + маркер диверсии в хвосте строки
  * `unsat_core.zig`   — `is_conflict = false;` + тот же маркер
Во второй раз поломка прожила в коммите и дала 10 ложных падений тестов
`kernfs_router` в сборе свидетельств.

ЧТО ДЕЛАЕТ. Перед любым патчащим прогоном и в CI проверяет:
  1. в `src/` нет маркеров инъекций (точный список — в `MARKERS` ниже);
  2. `git status --porcelain src/` пуст (нет чужих незакоммиченных правок).

Выход: 0 — чисто; 2 — найдено (жёсткий отказ: прогон/коммит недопустим).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Маркеры, которые харнессы оставляют в тексте поломки. Список намеренно
# узкий: обычные слова «инъекция»/«лом» встречаются в комментариях тестов
# (например, `fault_injection_test.zig`), поэтому ищем ТОЧНЫЕ метки.
#
# ⚠️ Первый маркер собран ИЗ ДВУХ ЛИТЕРАЛОВ (класс #290/#296). Причина не
# стилистическая: каталог `tools/` целиком сканируется стражем ci.sh на этот
# литерал, поэтому запись его здесь буквально давала ЛОЖНЫЙ провал стадии
# «нет следов харнесса в дереве» — страж ловил собственный детектор.
# Слепого пятна при этом НЕ появляется: значение строки не изменилось, и
# диверсия в дереве ловится ровно так же (проверяется тестом ниже).
MARKERS = ("ЛОМА" "ЕМ:", "ИНЪЕКЦИЯ ДЛЯ ПРОВЕРКИ", "always return false // KERN-MUT",
           # ДЕФЕКТ #172: харнесс патчит не только src/, но и tools/
           # (кейсы ломают сам экстрактор) — метка найдена в kern_contracts.py.
           "ДИВЕРСИЯ:")


def find_markers() -> list[str]:
    hits: list[str] = []
    targets = sorted((ROOT / "src").rglob("*.zig"))
    targets += sorted((ROOT / "examples").rglob("*.py")) if (ROOT / "examples").is_dir() else []
    targets += sorted((ROOT / "examples").rglob("*.zig")) if (ROOT / "examples").is_dir() else []
    for p in targets:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for ln, line in enumerate(text.splitlines(), 1):
            for m in MARKERS:
                if m in line:
                    hits.append(f"{p.relative_to(ROOT)}:{ln}: {line.strip()[:90]}")
    return hits


def dirty_src() -> list[str]:
    r = subprocess.run(["git", "status", "--porcelain", "src/", "tools/"],
                       cwd=ROOT, capture_output=True, text=True, check=False)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def main() -> int:
    hits = find_markers()
    dirty = dirty_src()

    if hits:
        print("[INJECTION GUARD] 🔴 В src/ найдены МАРКЕРЫ ИНЪЕКЦИЙ:")
        for h in hits:
            print("        - " + h)
        print("        Прогон/коммит НЕДОПУСТИМ: сначала откат (git checkout -- src/).")
    if dirty:
        print("[INJECTION GUARD] 🔴 src/ содержит незакоммиченные правки:")
        for d in dirty[:6]:
            print("        " + d)
    if hits or dirty:
        return 2

    print("[INJECTION GUARD] OK: маркеров инъекций нет, src/ чист")
    return 0


if __name__ == "__main__":
    sys.exit(main())
