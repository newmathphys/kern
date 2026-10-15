#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: проверка ДЕТЕРМИНИЗМА семантического дайджеста.

ЗАЧЕМ (K2). Цель `probe` была MEASURE: печатала `SEMANTIC_DIGEST=...`
и не могла упасть. Но у дайджеста есть ПРОВЕРЯЕМЫЙ инвариант:
два прогона на одном коде обязаны дать ОДИН И ТОТ ЖЕ дайджест.
Если дайджест «плывёт» — семантика недетерминирована, и это дефект.

Запуск:  python3 tools/probe_check.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run() -> str:
    env = dict(os.environ)
    env["PATH"] = f"{Path.home()}/opt/zig-x86_64-linux-0.17.0:{ROOT}/.venv/bin:{env.get('PATH','')}"
    p = subprocess.run(["zig", "build", "bench-semantic"], cwd=str(ROOT),
                       capture_output=True, text=True, env=env)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        print(f"[!] сборка/прогон упал (rc={p.returncode})")
        print(out[-500:])
        sys.exit(1)
    m = re.search(r"SEMANTIC_DIGEST=([0-9a-f]+)", out)
    if not m:
        print("[!] SEMANTIC_DIGEST не найден в выводе")
        sys.exit(1)
    return m.group(1)


def main() -> int:
    d1 = run()
    d2 = run()
    print(f"SEMANTIC_DIGEST (1-й прогон): {d1}")
    print(f"SEMANTIC_DIGEST (2-й прогон): {d2}")
    if d1 != d2:
        print("[!] ДАЙДЖЕСТ НЕДЕТЕРМИНИРОВАН — проверка ПРОВАЛЕНА")
        return 1
    if not re.fullmatch(r"[0-9a-f]{64}", d1):
        print("[!] дайджест не похож на SHA-256 (64 hex)")
        return 1
    print("[OK] дайджест детерминирован (SHA-256, 64 hex)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
