#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: фиксация тулчейна Lean/Mathlib (шаг 0K.7).

ЗАЧЕМ. 137 теорем зависят от версии Lean и ревизии Mathlib. Пока они не
записаны в репозитории, «0 sorry» воспроизводится «на удачу»: другая
ревизия Mathlib может изменить тактики и сломать доказательство, а CI
об этом не узнает.

Что фиксируется:
  `lean-toolchain`          — тег тулчейна (его читает elan);
  `formal/mathlib.lock`     — ревизия mathlib + версии пакетов из манифеста.

Проверка:
  • `lean --version` содержит версию из `lean-toolchain`  (FAIL при расхождении);
  • если проект Mathlib найден, его `lean-toolchain` и ревизия mathlib
    в манифесте совпадают с замком (FAIL при расхождении);
  • если Mathlib не найден — WARN (CI без Mathlib не должен падать).

Запуск: python3 tools/lean_pin_check.py [--override-lean X]  # override — для canfail
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLCHAIN = ROOT / "lean-toolchain"
LOCK = ROOT / "formal" / "mathlib.lock"


def lean_version(binary: str) -> str:
    try:
        r = subprocess.run([binary, "--version"], capture_output=True, text=True)
    except OSError:
        return ""
    m = re.search(r"version\s+([0-9]+\.[0-9]+\.[0-9]+)", r.stdout)
    return m.group(1) if m else ""


def find_mathlib() -> Path | None:
    cands = [os.environ.get("MATHLIB_PROJ", ""), str(Path.home() / "mathlib_proj"),
             str(Path.home() / "mathlib4"), str(ROOT / ".mathlib")]
    for c in cands:
        if c and (Path(c) / "lake-manifest.json").exists():
            return Path(c)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверить пин Lean/Mathlib")
    ap.add_argument("--override-lean", default="", help="подменить ожидание (canfail)")
    args = ap.parse_args()

    if not TOOLCHAIN.exists() or not LOCK.exists():
        print("[FAIL] нет lean-toolchain или formal/mathlib.lock")
        return 1

    pinned = TOOLCHAIN.read_text(encoding="utf-8").strip()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    want_raw = args.override_lean or lock.get("lean", "")
    bad = 0

    def norm(x: str) -> str:
        """`leanprover/lean4:v4.34.0` -> `4.34.0`; строка `9.9.9` -> `9.9.9`."""
        return x.split(":")[-1].strip().lstrip("v")

    tag = norm(pinned)
    want = norm(want_raw)
    if want and tag != want:
        print(f"[FAIL] lean-toolchain={tag}, а замок ждёт {want}")
        bad += 1

    lean_bin = os.environ.get("LEAN", str(Path.home() / ".elan" / "bin" / "lean"))
    got = lean_version(lean_bin)
    if not got:
        print(f"  [i] Lean не найден ({lean_bin}) — версия не проверена")
    elif got != tag:
        print(f"[FAIL] установлен Lean {got}, а закреплён {tag}")
        bad += 1
    else:
        print(f"  [OK] Lean {got} == lean-toolchain")

    ml = find_mathlib()
    if ml is None:
        print("  [i] Mathlib не найден — ревизия не проверена (WARN, не FAIL)")
    else:
        try:
            rev = ""
            man = json.loads((ml / "lake-manifest.json").read_text(encoding="utf-8"))
            for p in man.get("packages", []):
                if p.get("name") == "mathlib":
                    rev = p.get("rev", "")
            mt = (ml / "lean-toolchain").read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            rev, mt = "", ""
        if rev != lock.get("mathlib"):
            print(f"[FAIL] mathlib {rev[:12] or '?'} != замок {str(lock.get('mathlib'))[:12]}")
            bad += 1
        elif mt != pinned:
            print(f"[FAIL] toolchain проекта {mt!r} != {pinned!r}")
            bad += 1
        else:
            print(f"  [OK] Mathlib {rev[:12]} и toolchain совпадают с замком")

    print("\n[OK] тулчейн закреплён" if not bad else f"\n[FAIL] расхождений: {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
