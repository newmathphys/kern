#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""KERN: СЕМАНТИЧЕСКАЯ ЭКВИВАЛЕНТНОСТЬ КОМПИЛЯТОРОВ (Zig 0.13 vs 0.17).

ЗАЧЕМ (K2). Цель `portable-bench` была MEASURE: печатала времена и
не могла упасть. Но у неё есть ПРОВЕРЯЕМЫЙ инвариант, куда более
важный, чем скорость:

    Семантический результат (root0, acc) НЕ должен зависеть от компилятора.

Если 0.17 даёт другой `acc` или другой `root0` — компилятор меняет
семантику, и это КРИТИЧЕСКИЙ дефект (не «медленнее», а «неверно»).

Проверяются:
  1. детерминизм: два прогона одной сборки → одинаковые root0/acc;
  2. кросс-компиляторная эквивалентность: 0.13 и 0.17 → одинаковые root0/acc;
  3. форма root0/acc непустая (защита от вырожденного вывода).

Запуск:  python3 tools/portable_check.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "bench" / "portable_merkle.zig"
ZIG17 = Path.home() / "opt" / "zig-x86_64-linux-0.17.0" / "zig"
ZIG13 = ROOT / ".venv" / "bin" / "zig"


def build_and_run(zig: Path, out: str) -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{zig.parent}:{env.get('PATH','')}"
    b = subprocess.run([str(zig), "build-exe", str(SRC), "-O", "ReleaseFast",
                        "-lc", f"-femit-bin={out}"],
                       cwd=str(ROOT), capture_output=True, text=True, env=env)
    if b.returncode != 0:
        print(f"[!] сборка {zig} упала:\n{(b.stderr or '')[-400:]}")
        sys.exit(1)
    r = subprocess.run([out], cwd=str(ROOT), capture_output=True, text=True)
    out_txt = (r.stdout or "") + (r.stderr or "")
    d = {}
    for k in ("root0", "acc"):
        m = re.search(rf"^{k}=(\S+)", out_txt, re.M)
        if not m:
            print(f"[!] в выводе нет {k}=...")
            print(out_txt[-300:])
            sys.exit(1)
        d[k] = m.group(1)
    return d


def main() -> int:
    print("=== семантическая эквивалентность компиляторов ===")
    a1 = build_and_run(ZIG17, "/tmp/pc17_a")
    a2 = build_and_run(ZIG17, "/tmp/pc17_b")
    print(f"  0.17 прогон 1: root0={a1['root0']} acc={a1['acc']}")
    print(f"  0.17 прогон 2: root0={a2['root0']} acc={a2['acc']}")

    bad = 0
    if a1 != a2:
        print("[!] НЕДЕТЕРМИНИЗМ: два прогона 0.17 дали разные результаты")
        bad += 1
    if a1["acc"] in ("0", "") or a1["root0"] in ("0", ""):
        print("[!] ВЫРОЖДЕННЫЙ вывод (acc/root0 пусты) — загрузки могли быть выброшены")
        bad += 1

    if ZIG13.exists():
        b1 = build_and_run(ZIG13, "/tmp/pc13")
        print(f"  0.13         : root0={b1['root0']} acc={b1['acc']}")
        if b1 != a1:
            print("[!] КОМПИЛЯТОРЫ ДАЮТ РАЗНУЮ СЕМАНТИКУ — КРИТИЧЕСКИЙ ДЕФЕКТ")
            bad += 1
        else:
            print("[OK] 0.13 и 0.17 семантически эквивалентны (root0/acc совпали)")
    else:
        print("[i] Zig 0.13 нет — кросс-компиляторная проверка пропущена")

    if bad:
        print(f"[!] ПРОВАЛОВ: {bad}")
        return 1
    print("[OK] проверка пройдена")
    return 0


if __name__ == "__main__":
    sys.exit(main())
