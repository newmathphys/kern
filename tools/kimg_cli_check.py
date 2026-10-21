#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: проверка CLI `fsck` / `inspect` / `diff` на golden-фикстурах (Ф3.2).

ЗАЧЕМ. Тесты в Zig проверяют парсер на массивах байтов, но внешний
`conformance_check.py` (Фаза 5, раздел 10) вызывает КОМАНДЫ на ФАЙЛАХ.
Этот скрипт — тот же взгляд снаружи: он не знает внутренностей и судит
только по коду возврата и выводу.

Ожидания:
  kimg_unknown_optional.kimg → fsck rc=0, inspect = валидный JSON, 1 объект «a.zig»
  kimg_unknown_required.kimg → fsck rc=1, в выводе UnsupportedRequiredFeature
  kimg_big_endian.kimg       → fsck rc=1, в выводе WrongEndianness
  diff X X → rc=0; diff optional required → rc≠0

Запуск: python3 tools/kimg_cli_check.py [--min-objects N]
Код возврата: 0 — всё как ожидалось; 1 — расхождение; 2 — нет бинаря/фикстур.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
FIX = ROOT / "tests" / "fixtures"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(KERNC), *args], capture_output=True, text=True, timeout=120)


def main() -> int:
    ap = argparse.ArgumentParser(description="CLI-проверка KIMG на фикстурах")
    ap.add_argument("--min-objects", type=int, default=1,
                    help="минимум объектов в inspect (для canfail)")
    args = ap.parse_args()

    if not KERNC.exists():
        print(f"[FAIL] нет {KERNC} — сначала `zig build`")
        return 2
    opt = FIX / "kimg_unknown_optional.kimg"
    req = FIX / "kimg_unknown_required.kimg"
    be = FIX / "kimg_big_endian.kimg"
    missing = [p.name for p in (opt, req, be) if not p.exists()]
    if missing:
        print(f"[FAIL] нет фикстур: {missing} (см. src/gen_kimg_fixtures.zig)")
        return 2

    bad = 0

    r = run("fsck", str(opt))
    if r.returncode != 0:
        print(f"  [FAIL] fsck(optional): rc={r.returncode}, ожидался 0")
        bad += 1
    else:
        print("  [OK] fsck(unknown-optional): rc=0")

    r = run("fsck", str(req))
    if r.returncode == 0 or "UnsupportedRequiredFeature" not in (r.stdout + r.stderr):
        print(f"  [FAIL] fsck(unknown-required): rc={r.returncode}, ожидался отказ с UnsupportedRequiredFeature")
        bad += 1
    else:
        print("  [OK] fsck(unknown-required): отказ UnsupportedRequiredFeature")

    r = run("fsck", str(be))
    if r.returncode == 0 or "WrongEndianness" not in (r.stdout + r.stderr):
        print(f"  [FAIL] fsck(big-endian): rc={r.returncode}, ожидался отказ с WrongEndianness")
        bad += 1
    else:
        print("  [OK] fsck(big-endian): отказ WrongEndianness")

    r = run("inspect", str(opt))
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        print(f"  [FAIL] inspect: вывод не JSON (rc={r.returncode})")
        bad += 1
        doc = None
    if doc is not None:
        n = len(doc.get("objects", []))
        if doc.get("hash_algo") != 1 or n < args.min_objects:
            print(f"  [FAIL] inspect: hash_algo={doc.get('hash_algo')}, объектов {n} < {args.min_objects}")
            bad += 1
        elif doc["objects"][0].get("path") != "a.zig":
            print(f"  [FAIL] inspect: путь {doc['objects'][0].get('path')!r} != 'a.zig'")
            bad += 1
        else:
            print(f"  [OK] inspect: JSON, {n} объект(ов), path=a.zig")

    r = run("diff", str(opt), str(opt))
    if r.returncode != 0:
        print(f"  [FAIL] diff(одинаковые): rc={r.returncode}, ожидался 0")
        bad += 1
    else:
        print("  [OK] diff(одинаковые): rc=0")

    r = run("diff", str(opt), str(req))
    if r.returncode == 0:
        print("  [FAIL] diff(разные): rc=0, ожидался ненулевой")
        bad += 1
    else:
        print("  [OK] diff(разные): rc≠0")

    print("\n[OK] CLI fsck/inspect/diff работают на фикстурах" if not bad
          else f"\n[FAIL] расхождений: {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
