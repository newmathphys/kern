#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
"""ПУНКТ 39: ОХОТА ЗА НАСТОЯЩИМИ БАГАМИ В ЖИВОМ ЧУЖОМ КОДЕ.

ЗАЧЕМ. Прогоняем наш БЕЗАННОТАЦИОННЫЙ рентген (`--xray`) по реальным файлам
стандартной библиотеки Python и честно печатаем, что найдено. Никаких «5000
функций проверено»: печатается ВОРОНКА (`checked N / M, skipped K с причинами`).

КОНТРОЛЬ (анти-вакуум): помимо stdlib сканируется НАША фикстура
`examples/xray_demo.py` с ИЗВЕСТНЫМИ находками — если детектор перестал их
находить, цель обязана покраснеть (иначе «0 находок в stdlib» ничего не значит).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"
CONTROL = ROOT / "examples" / "xray_demo.py"
RE_FIND = re.compile(r"\[(DEAD BRANCH|REDUNDANT GUARD|CRASH PATH|BOUNDS PATH|IMPURE)\]")
RE_SUM = re.compile(r"\[XRAY SUMMARY\] checked (\d+) / (\d+) functions, skipped (\d+)")

def scan(path: Path) -> tuple[int, int, int, list[str]]:
    r = subprocess.run([sys.executable, str(EXTRACTOR), "--xray", str(path)],
                       capture_output=True, text=True, timeout=300)
    out = (r.stdout or "") + (r.stderr or "")
    m = RE_SUM.search(out)
    checked, total, skipped = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
    found = [ln.strip() for ln in out.splitlines() if RE_FIND.search(ln)]
    return checked, total, skipped, found

def main() -> int:
    ap = argparse.ArgumentParser(description="Охота за багами в живом коде")
    ap.add_argument("--dir", default=None, help="каталог (по умолчанию stdlib Python)")
    ap.add_argument("--max-files", type=int, default=25)
    args = ap.parse_args()

    # 1) КОНТРОЛЬ: детектор обязан находить ИЗВЕСТНЫЕ находки.
    c_checked, c_total, _cs, c_found = scan(CONTROL)
    print(f"[контроль] {CONTROL.name}: checked {c_checked}/{c_total}, находок {len(c_found)}")
    if len(c_found) < 2:
        print("[!] КОНТРОЛЬ НЕ ПРОЙДЕН: детектор не видит известные находки")
        return 2

    base = Path(args.dir) if args.dir else Path(os.path.dirname(os.__file__))
    files = sorted(p for p in base.rglob("*.py") if p.is_file())[: args.max_files]
    total_found = 0
    files_with = 0
    checked_sum = total_sum = skipped_sum = 0
    print("-" * 78)
    print(f"[i] каталог: {base} | файлов к сканированию: {len(files)}")
    for f in files:
        try:
            ck, tot, sk, found = scan(f)
        except Exception as e:
            print(f"  [SKIP] {f.name}: {e}")
            continue
        checked_sum += ck
        total_sum += tot
        skipped_sum += sk
        if found:
            files_with += 1
            total_found += len(found)
            print(f"  {f.name}: находок {len(found)}")
            for ln in found[:3]:
                print(f"     {ln[:150]}")
    print("-" * 78)
    print(f"[BUG HUNT] файлов {len(files)} | функций checked {checked_sum} / {total_sum} "
          f"(skipped {skipped_sum}) | файлов с находками {files_with} | находок {total_found}")
    print("[i] Честно: находки в чужом коде НЕ являются приговором — каждая требует "
          "проверки контрпримером (--xray печатает его для CRASH PATH).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
