#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: порог производительности (шаг 0K.12).

ЗАЧЕМ. Планы Ф3 меняют горячий путь (13-польный ключ кэша, лишние проверки).
Без базовой линии «стало медленнее в 4 раза» никто не заметит: тесты
останутся зелёными, а кэш перестанет спасать.

Метод: N прогонов `kernc prove` на фиксированном SMT, берётся МЕДИАНА
(устойчива к выбросам планировщика). Сравнение с базовой линией:
`median / baseline > threshold` (по умолчанию 1.5) И абсолютная дельта
больше `--slack-ms` (по умолчанию 5 мс) — иначе шум на быстрых прогонах
даёт ложные провалы.

Запуск:
  python3 tools/perf_check.py --update      # записать базовую линию
  python3 tools/perf_check.py               # проверить (CI)
  python3 tools/perf_check.py --threshold 0.01   # для canfail: гарантированный провал
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
BASELINE = ROOT / "docs" / "evidence" / "bench_baseline.json"

SMT = ("(set-logic ALL)\n(declare-const x Int)\n(declare-const y Int)\n"
       "(assert (> x 5))\n(assert (< y 3))\n(assert (= (+ x y) 10))\n"
       "(assert (< x 3))\n(check-sat)\n")


def measure(runs: int) -> list[float]:
    samples: list[float] = []
    with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False) as tf:
        tf.write(SMT)
        path = tf.name
    try:
        for _ in range(runs):
            t0 = time.perf_counter()
            subprocess.run([str(KERNC), "prove", path], capture_output=True, timeout=120)
            samples.append((time.perf_counter() - t0) * 1000.0)
    finally:
        Path(path).unlink(missing_ok=True)
    return samples


def main() -> int:
    ap = argparse.ArgumentParser(description="Порог производительности kernc prove")
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--threshold", type=float, default=1.5)
    ap.add_argument("--slack-ms", type=float, default=5.0)
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--update", action="store_true")
    args = ap.parse_args()

    if not KERNC.exists():
        print(f"[FAIL] нет {KERNC} — сначала `zig build`")
        return 2

    samples = measure(max(3, args.runs))
    med = statistics.median(samples)

    if args.update:
        doc = {"median_ms": round(med, 2), "runs": len(samples),
               "min_ms": round(min(samples), 2), "max_ms": round(max(samples), 2),
               "smt_sha256": __import__("hashlib").sha256(SMT.encode()).hexdigest()}
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"[OK] базовая линия: {med:.2f} мс ({len(samples)} прогонов) -> {args.baseline}")
        return 0

    if not args.baseline.exists():
        print(f"[FAIL] нет базовой линии {args.baseline} — запустите --update")
        return 2
    base = json.loads(args.baseline.read_text(encoding="utf-8"))
    old = float(base.get("median_ms", 0)) or 1.0
    ratio = med / old
    delta = med - old
    too_slow = ratio > args.threshold and delta > args.slack_ms
    print(f"  база {old:.2f} мс · сейчас {med:.2f} мс · отношение {ratio:.2f}× "
          f"(порог {args.threshold}×, допуск {args.slack_ms:.1f} мс)")
    if too_slow:
        print(f"[FAIL] регресс производительности: +{delta:.1f} мс")
        return 1
    print("[OK] в пределах порога")
    return 0


if __name__ == "__main__":
    sys.exit(main())
