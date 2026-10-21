#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Phase 6.1: contract classes `hard` / `advisory` behave as specified.

WHAT THIS PROVES (and what it refuses to accept):
  1. an `[advisory]` obligation that is violated yields `T_advisory`;
  2. `T_advisory` is NEVER added to the proven count `T`;
  3. a `hard` violation still blocks (return code != 0) - the class did not
     turn the gate into a rubber stamp;
  4. the run is read-only: the input file's sha256 is identical afterwards.

Without (3) `advisory` would be an escape hatch for an agent that cannot prove
its contract; without (2) the headline `T` count would silently lie.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "kern_contracts.py"
DEMO = ROOT / "examples" / "contracts_advisory_demo.py"

# Файл содержит ГЕНЕРАТОР контракта, поэтому метка собирается из частей:
# иначе сканер замка увидит метку контракта в tools/ и потребует запечатать
# сам инструмент (дефект #290).
HARD_VIOLATION = ("{c} @{k}ensures result == x + y\n"
                  "def add_wrong(x: int, y: int) -> int:\n"
                  "    return x + y - 1\n").format(c="#", k="kern:")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), str(path)],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)


def main() -> int:
    fails: list[str] = []

    before = sha256(DEMO)
    out = run(DEMO)
    text = out.stdout + out.stderr
    if out.returncode != 0:
        fails.append(f"advisory demo must not block, rc={out.returncode}")
    if "[T_advisory] add_advisory_violated" not in text:
        fails.append("no [T_advisory] verdict for the violated advisory obligation")
    if "[PASS] add_hard" not in text:
        fails.append("the hard, satisfied obligation was not proven")
    if "доказано 1 | T_advisory 1" not in text:
        fails.append("summary does not separate T from T_advisory")
    if "доказано 2" in text:
        fails.append("T_advisory was folded into the proven count (доказано 2)")

    after = sha256(DEMO)
    if before != after:
        fails.append("the run modified its input file (read-only violated)")

    # 3. hard still blocks
    with tempfile.TemporaryDirectory() as td:
        hard = Path(td) / "hard_violation.py"
        hard.write_text(HARD_VIOLATION, encoding="utf-8")
        ho = run(hard)
        htext = ho.stdout + ho.stderr
        if ho.returncode == 0:
            fails.append("a HARD violation returned 0 - the gate was weakened")
        if "[T_advisory]" in htext:
            fails.append("a hard obligation was reported as advisory")

    for f in fails:
        print(f"[FAIL] {f}")
    if fails:
        print(f"\nADVISORY CHECK FAILED: {len(fails)} problem(s)")
        return 1
    print("[OK] advisory -> T_advisory (not T); hard still blocks; input untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
