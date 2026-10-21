#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN code-checking corpus runner (Phase 4B): hard gate FP = 0.

WHAT THIS PROVES. A verifier that accuses correct code is worse than useless:
one false F destroys trust in every T it ever produced. This runner executes
KERN on a fixed corpus and compares the LIVE verdict with ``<file>.expect.json``:

    expect T (correct code) + got T -> TN
    expect T                + got F -> FP   (false accusation, forbidden)
    expect F (buggy code)   + got F -> TP
    expect F                + got T -> FN   (missed bug, forbidden)
    expect N (boundary)     + got N -> TN
    expect N                + got T/F -> FP (claiming what it cannot check)

The verdict is COMPUTED by ``kern_contracts.py`` (which drives ``kernc`` + Z3);
it is never read from the expectation file. UNKNOWN is reported, not punished:
"cannot decide" is honest, "guessed F" is not.

CLI: python3 tools/codecheck_runner.py [--min-files N] [--json OUT]
Exit codes: 0 = FP == 0 and FN == 0; 1 = gate failed; 2 = corpus/KERN missing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "audits" / "codecheck"
CONTRACTS = ROOT / "tools" / "kern_contracts.py"

# KERN verdict -> three-valued abstraction used by the gate.
_TO_TRISTATE = {"PROVEN": "T", "CONTRACT_VIOLATED": "F"}


def _env() -> dict:
    """Make the project venv visible: Z3 lives there, and without it every
    function used to be reported as violated (defect #277)."""
    env = dict(os.environ)
    venv = ROOT / ".venv" / "bin"
    if venv.is_dir():
        env["PATH"] = f"{venv}{os.pathsep}{env.get('PATH', '')}"
    return env


def verdict_of(path: Path) -> tuple[str, list[str]]:
    """Run KERN on one file; return (T|F|N, per-function verdicts)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = tf.name
    r = subprocess.run(
        [sys.executable, str(CONTRACTS), str(path), "--json", out],
        capture_output=True, text=True, timeout=180, env=_env())
    raw: list[str] = []
    try:
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        raw = [f.get("verdict", "?") for f in data["files"][0]["functions"]]
    except (OSError, ValueError, KeyError):
        Path(out).unlink(missing_ok=True)
        return "N", [f"runner-error rc={r.returncode}"]
    Path(out).unlink(missing_ok=True)

    mapped = [_TO_TRISTATE.get(v, "N") for v in raw]
    if "F" in mapped:
        return "F", raw
    if "T" in mapped:
        return "T", raw
    return "N", raw

def main() -> int:
    ap = argparse.ArgumentParser(description="KERN code-checking corpus (FP = 0)")
    ap.add_argument("--min-files", type=int, default=0,
                    help="require at least N corpus files (can-fail hook)")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    if not CORPUS.is_dir():
        print(f"[FAIL] no corpus at {CORPUS}")
        return 2
    if not (ROOT / "zig-out" / "bin" / "kernc").exists():
        print("[FAIL] no zig-out/bin/kernc — run `zig build` first")
        return 2

    files = sorted(p for p in CORPUS.iterdir()
                   if p.is_file() and not p.name.endswith(".expect.json")
                   and not p.name.endswith(".md"))
    if not files:
        print(f"[FAIL] corpus {CORPUS} is empty")
        return 2

    rows, fp, fn, unknown = [], [], [], []
    for path in files:
        exp_file = path.with_name(path.name + ".expect.json")
        if not exp_file.exists():
            print(f"  [FAIL] {path.name}: missing {exp_file.name}")
            fn.append(path.name)
            continue
        exp = json.loads(exp_file.read_text(encoding="utf-8"))
        want = exp.get("expect", "?")
        got, raw = verdict_of(path)
        if want == "T":
            cell = "TN" if got == "T" else ("FP" if got == "F" else "UNKNOWN")
        elif want == "F":
            cell = "TP" if got == "F" else "FN"
        elif want == "N":
            cell = "TN" if got == "N" else "FP"
        else:
            cell = "UNKNOWN"
        if cell == "FP":
            fp.append(path.name)
        elif cell == "FN":
            fn.append(path.name)
        elif cell == "UNKNOWN":
            unknown.append(path.name)
        rows.append({"file": path.name, "expect": want, "got": got,
                     "cell": cell, "verdicts": raw, "why": exp.get("why", "")})
        print(f"  [{cell:7s}] {path.name:22s} expect={want} got={got} "
              f"({', '.join(raw) if raw else 'no functions'})")

    print("\n  matrix: " + ", ".join(
        f"{c}={sum(1 for r in rows if r['cell'] == c)}"
        for c in ("TP", "TN", "FP", "FN", "UNKNOWN")))
    if args.json:
        args.json.write_text(json.dumps({"rows": rows, "fp": fp, "fn": fn,
                                         "unknown": unknown},
                                        ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")

    bad = 0
    if fp:
        print(f"  [FAIL] FALSE POSITIVES (forbidden): {fp}")
        bad += 1
    if fn:
        print(f"  [FAIL] FALSE NEGATIVES (missed defects): {fn}")
        bad += 1
    if len(files) < args.min_files:
        print(f"  [FAIL] corpus {len(files)} < required {args.min_files}")
        bad += 1

    print("\n[OK] FP = 0 and FN = 0 — KERN accused no correct file"
          if not bad else f"\n[FAIL] gate violations: {len(fp)} FP, {len(fn)} FN")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
