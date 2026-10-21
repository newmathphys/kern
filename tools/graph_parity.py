#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: паритет графа `G_src` между ядром и витриной (шаг Ф2).

ЗАЧЕМ. Граф для Эго-Линзы и матрицы фильтров строится `kernx graph --json`
(ядро, Zig). Пока витрина собиралась отдельным Python-сканером, это были два
расходящихся графа. Теперь ядро — источник, а этот скрипт — сторож: множества
узлов и рёбер обязаны совпадать ПОБАЙТОВО (по идентификаторам).

Проверяется:
  • `kernx` собран и отвечает;
  • набор `id` узлов совпадает;
  • набор пар `(source, target)` рёбер совпадает.

Запуск: python3 tools/graph_parity.py [--min-nodes N]
Код возврата: 0 — совпало; 1 — расхождение; 2 — нет входа.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNX = ROOT / "zig-out" / "bin" / "kernx"
SHOWCASE = ROOT / "docs" / "showcase-graph.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Паритет графа kernx ↔ showcase")
    ap.add_argument("--min-nodes", type=int, default=0,
                    help="требовать минимум N узлов (для canfail)")
    args = ap.parse_args()

    if not KERNX.exists():
        print(f"[FAIL] нет {KERNX} — сначала `zig build`")
        return 2
    if not SHOWCASE.exists():
        print(f"[FAIL] нет {SHOWCASE} — запустите tools/gen_showcase_graph.py")
        return 2

    r = subprocess.run([str(KERNX), "graph"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        print(f"[FAIL] kernx graph: rc={r.returncode} {r.stderr[:200]}")
        return 2
    zig = json.loads(r.stdout)
    py = json.loads(SHOWCASE.read_text(encoding="utf-8"))

    zn = {n["id"] for n in zig.get("nodes", [])}
    pn = {n["id"] for n in py.get("nodes", [])}
    ze = {(e["source"], e["target"]) for e in zig.get("edges", [])}
    pe = {(e["source"], e["target"]) for e in py.get("edges", [])}

    bad = 0
    if len(zn) < args.min_nodes:
        print(f"  [FAIL] узлов {len(zn)} < требуемых {args.min_nodes}")
        bad += 1
    if zn != pn:
        print(f"  [FAIL] узлы: только kernx {sorted(zn - pn)[:6]}; только витрина {sorted(pn - zn)[:6]}")
        bad += 1
    if ze != pe:
        print(f"  [FAIL] рёбра: только kernx {sorted(ze - pe)[:4]}; только витрина {sorted(pe - ze)[:4]}")
        bad += 1

    # Метрики узлов тоже обязаны совпадать: иначе граф «тот же», а числа в нём
    # врут (именно так разошлись loc в Zig и Python: +1 на файлах с переводом
    # строки в конце).
    zm = {n["id"]: (n.get("loc"), n.get("imports_out"))
          for n in zig.get("nodes", [])}
    pm = {n["id"]: (n.get("loc"), n.get("imports_out"))
          for n in py.get("nodes", [])}
    diff = [k for k in sorted(zm.keys() & pm.keys()) if zm[k] != pm[k]]
    if diff:
        k = diff[0]
        print(f"  [FAIL] метрики расходятся у {len(diff)} узлов, напр. {k}: kernx={zm[k]} витрина={pm[k]}")
        bad += 1

    if not bad:
        print(f"  [OK] паритет: {len(zn)} узлов, {len(ze)} рёбер — kernx == showcase")
    print("\n[OK] граф един" if not bad else f"\n[FAIL] расхождений: {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
