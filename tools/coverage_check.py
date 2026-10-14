#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""KERN: проверка ПОКРЫТИЯ РЕШЕНИЙ с ПОРОГОМ.

ЗАЧЕМ (дефект #41, найден can-fail). Цель `make coverage` была
`zig test ... | grep -A40 'ПОКРЫТИЕ РЕШЕНИЙ'` — то есть только ПЕЧАТАЛА
отчёт. Если счётчики перестанут расти (покрытие 0 %), цель останется
ЗЕЛЁНОЙ: `grep` найдёт заголовок и вернёт 0.

Здесь значение покрытия ПАРСИТСЯ и сравнивается с порогом.
Порог по умолчанию 100 % (сейчас покрытие именно такое: 30/30 решений).

Запуск:  python3 tools/coverage_check.py [порог]
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    threshold = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0

    env = dict(os.environ)
    env["PATH"] = f"{Path.home()}/opt/zig-x86_64-linux-0.17.0:{ROOT}/.venv/bin:{env.get('PATH','')}"
    cmd = ["zig", "test", "--dep", "compat",
           "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig"]
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=env)
    out = (p.stdout or "") + (p.stderr or "")

    # Печатаем блок отчёта о покрытии (как делала прежняя цель).
    lines = out.splitlines()
    for i, ln in enumerate(lines):
        if "ПОКРЫТИЕ РЕШЕНИЙ" in ln:
            for l in lines[i:i + 40]:
                print(l)
            break
    else:
        print("[!] блок «ПОКРЫТИЕ РЕШЕНИЙ» не найден в выводе тестов")
        return 1

    # Падения тестов — сразу провал.
    if p.returncode != 0 or "0 failed" not in out:
        if "All " not in out:
            print(f"[!] тесты упали (rc={p.returncode})")
            return 1

    m = re.search(r"ПОКРЫТИЕ РЕШЕНИЙ:\s*([0-9.]+)%", out)
    if not m:
        print("[!] не удалось разобрать значение покрытия")
        return 1
    pct = float(m.group(1))
    print(f"\n[порог {threshold:.1f}%] ФАКТ: {pct:.1f}%", end="  ")
    if pct + 1e-9 < threshold:
        print("-> ПРОВАЛ")
        return 1
    print("-> OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
