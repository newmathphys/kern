#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Phase 6.3 gate: `explain --hypotheses` is read-only and honest.

FOUR THINGS ARE PROVED, and each one is a way abductive tooling usually lies:
  1. READ-ONLY - the input file's sha256 is identical before and after;
  2. DETERMINISTIC - two runs produce byte-identical output;
  3. NO VACUOUS HYPOTHESIS - a candidate that makes `requires` contradictory is
     REJECTED out loud (otherwise "proved" would be vacuous truth);
  4. NO WISHFUL ANSWER - when nothing prunes the counterexample the tool says so
     instead of inventing a condition.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "kern_contracts.py"
DEMO = ROOT / "examples" / "hypotheses_demo.py"
BUGGY = ROOT / "examples" / "contracts_demo.py"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=900)


def main() -> int:
    fails: list[str] = []

    before = sha256(DEMO)
    first = run("explain", "--hypotheses", str(DEMO))
    second = run("explain", "--hypotheses", str(DEMO))
    after = sha256(DEMO)
    text = first.stdout + first.stderr

    if before != after:
        fails.append("input changed: the report is not read-only")
    if first.returncode != 0:
        fails.append(f"rc={first.returncode} on a file with a fixable contract")
    if first.stdout != second.stdout:
        fails.append("two runs differ: the report is not deterministic")
    if "HYPOTHESIS, not a proof. File not modified." not in text:
        fails.append("missing the HYPOTHESIS banner")
    if "[1] requires +=" not in text:
        fails.append("no hypothesis reported for a contract that is fixable")
    if "x >= 0" not in text:
        fails.append("the obvious `x >= 0` hypothesis is missing")

    # 3+4: a case where the CODE is wrong - the tool must not invent a condition
    buggy = run("explain", "--hypotheses", str(BUGGY), "--fn", "withdraw_buggy")
    btext = buggy.stdout + buggy.stderr
    if buggy.returncode != 0:
        fails.append(f"rc={buggy.returncode} on a refuted contract")
    if "не найдено" not in btext:
        fails.append("invented a hypothesis although only the code is wrong")
    if "делает requires противоречивым" not in btext:
        fails.append("vacuous candidates were not rejected out loud")

    # 5. machine-readable report carries kind=hypothesis (never a verdict)
    import json as _json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out_json = Path(td) / "hyp.json"
        jr = run("explain", "--hypotheses", str(DEMO),
                 "--hypotheses-json", str(out_json))
        if jr.returncode != 0 or not out_json.exists():
            fails.append("no JSON report produced")
        else:
            data = _json.loads(out_json.read_text(encoding="utf-8"))
            if data.get("kind") != "hypothesis":
                fails.append("JSON kind is not 'hypothesis'")
            if not data.get("hypotheses"):
                fails.append("JSON has no hypotheses")

    for f in fails:
        print(f"[FAIL] {f}")
    if fails:
        print(f"\nEXPLAIN-HYPOTHESES CHECK FAILED: {len(fails)} problem(s)")
        return 1
    print("[OK] read-only · deterministic · vacuous rejected · no wishful answers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
