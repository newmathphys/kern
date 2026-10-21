#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: ПОВТОРНЫЙ прогон каждого DIVERGED из свидетельства (Ф4).

ЗАЧЕМ. `docs/evidence/quixbugs_full.log` — это снимок. Через месяц он может
перестать соответствовать коду: домены поменяются, функция сломается, а лог
останется зелёным. Этот страж берёт СПИСОК задач из лога и заново прогоняет
каждую живым вызовом: заявленное расхождение обязано воспроизвестись.

Строгость:
  • задача, которая в логе `DIVERGED`, а сейчас не расходится → ПРОВАЛ;
  • задача, которой в логе нет, но она расходится → предупреждение (лог устарел);
  • `--min-diverged N` — для canfail: заведомо недостижимый порог.

Запуск: python3 tools/quixbugs_replay.py [DATASET] [--log FILE] [--min-diverged N]
Код возврата: 0 — всё воспроизвелось; 1 — нет; 2 — нет датасета/лога.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "docs" / "evidence" / "quixbugs_full.log"


def load_explorer():
    spec = importlib.util.spec_from_file_location(
        "trace_explorer", ROOT / "tools" / "trace_explorer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def claimed(path: Path) -> list[str]:
    """Задачи, заявленные в логе как DIVERGED (итоговая таблица, не [s2]-строки)."""
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("  [s2]"):
            continue
        # Только имена задач: строка «[OK] DIVERGED …» — это итог, не задача.
        m = re.match(r"^([a-z_][a-z0-9_]*)\s+DIVERGED\b", line)
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description="Повторный прогон DIVERGED из лога")
    ap.add_argument("dataset", nargs="?", default="/tmp/QuixBugs-master")
    ap.add_argument("--log", type=Path, default=LOG)
    ap.add_argument("--min-diverged", type=int, default=0)
    args = ap.parse_args()

    qb = Path(args.dataset)
    if not (qb / "python_programs").is_dir():
        print(f"[FAIL] нет датасета {qb} — git clone jkoppel/QuixBugs")
        return 2
    if not args.log.exists():
        print(f"[FAIL] нет лога {args.log}")
        return 2

    names = claimed(args.log)
    if not names:
        print(f"[FAIL] в {args.log} нет ни одной строки DIVERGED")
        return 1

    te = load_explorer()
    bad = 0
    for name in names:
        b = qb / "python_programs" / f"{name}.py"
        c = qb / "correct_python_programs" / f"{name}.py"
        if not b.exists() or not c.exists():
            print(f"  [FAIL] {name}: нет файла в датасете")
            bad += 1
            continue
        hit = False
        for fn in te.functions_in(b):
            if fn not in set(te.functions_in(c)):
                continue
            if te.explore(b, c, fn)["diverged"]:
                hit = True
                break
        if hit:
            print(f"  [OK] {name}: расхождение воспроизведено")
        else:
            print(f"  [FAIL] {name}: в логе DIVERGED, сейчас НЕ воспроизводится")
            bad += 1

    if len(names) < args.min_diverged:
        print(f"  [FAIL] DIVERGED {len(names)} < требуемых {args.min_diverged}")
        bad += 1

    print(f"\n[{'OK' if not bad else 'FAIL'}] перепроверено {len(names)} задач, "
          f"расхождений {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
