#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: прогон тестов ядра с ОБЯЗАТЕЛЬНЫМ фильтром.

ЗАЧЕМ (дефект #34, найден can-fail харнессом).
Цели вида
    zig test ... | grep -E "ARRAY|passed"
ВАКУУМНЫ: если ARRAY-тесты исчезли (удалены, переименованы, отключены),
слово `passed` из итоговой строки всё равно совпадёт с шаблоном, `grep`
вернёт 0 — и цель останется ЗЕЛЁНОЙ, хотя проверять больше нечего.

Здесь проверяются ТРИ условия, и любое нарушение -> НЕНУЛЕВОЙ код возврата:
  1. тесты с данным фильтром РЕАЛЬНО НАЙДЕНЫ (>= 1 строка);
  2. прогон не содержит падений (`0 failed`);
  3. вывод печатается для человека (без обрезки).

Использование:  python3 tools/run_filtered.py "ARRAY"
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print("использование: run_filtered.py <regex-фильтр>")
        return 2
    flt = sys.argv[1]

    env = dict(os.environ)
    env["PATH"] = f"{Path.home()}/opt/zig-x86_64-linux-0.17.0:{ROOT}/.venv/bin:{env.get('PATH','')}"
    cmd = ["zig", "test", "--dep", "compat",
           "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig"]
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=env)
    out = (p.stdout or "") + (p.stderr or "")

    # 3. Печатаем релевантные строки (и итог) — для человека.
    for ln in out.splitlines():
        if re.search(flt, ln) or "passed" in ln or "failed" in ln:
            print(ln)

    # 2. Падения тестов. Формат итога бывает двух видов:
    #    "All 192 tests passed."  |  "188 passed; 4 skipped; 0 failed."
    m = re.search(r"(\d+)\s+passed;\s+(\d+)\s+skipped;\s+(\d+)\s+failed", out)
    if m:
        passed, skipped, failed = map(int, m.groups())
    else:
        m2 = re.search(r"All\s+(\d+)\s+tests passed", out)
        if not m2:
            print(f"[!] не удалось разобрать итог прогона тестов (rc={p.returncode})")
            return 1
        passed, skipped, failed = int(m2.group(1)), 0, 0
    if failed != 0 or p.returncode != 0:
        print(f"[!] ЕСТЬ ПАДЕНИЯ: failed={failed} rc={p.returncode}")
        return 1

    # 1. ГЛАВНОЕ: тесты с данным фильтром реально найдены?
    # ⚠️ ФИКС (#34, уточнение): матчить надо ИМЯ ТЕСТА, а не произвольный вывод.
    # Тест может САМ печатать строку с ключевым словом (напр. `[LITMUS SB] ...`),
    # и тогда фильтр срабатывал бы на вывод, хотя самих тестов уже нет.
    # Формат заголовка теста у Zig: "<i>/<N> <модуль>.<имя>...OK"
    hits = []
    for ln in out.splitlines():
        mh = re.match(r"\s*\d+/\d+\s+(.*?)\.\.\.", ln)
        if mh and re.search(flt, mh.group(1)):
            hits.append(mh.group(1))
    if not hits:
        print(f"[!] ВАКУУМНО: ни одного теста по фильтру '{flt}' не найдено "
              f"(всего прошло {passed}) — проверять нечего")
        return 1

    print(f"[OK] фильтр '{flt}': найдено тестов {len(hits)}, "
          f"прогон {passed} passed / {skipped} skipped / {failed} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
