#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Vector 3: stress-test `explain --hypotheses` on the real corpus.

WHAT THIS PROVES (each item is a way an abductive tool lies):
  1. READ-ONLY     - sha256 of every corpus file is unchanged after the report;
  2. DETERMINISTIC - two consecutive runs are byte-identical;
  3. SOUND         - every reported hypothesis, applied to a TEMPORARY COPY,
                     makes the contract actually PROVEN by kern_contracts/kernc;
  4. NON-VACUOUS   - and that run does not report a VACUOUS precondition, which
                     is how a contradictory `requires` would fake a proof.

The round-trip is the important part: the generator's own filter is not trusted,
because a filter bug and a generation bug cancel out. Here the claim is replayed
through the contract runner, which has its own independent vacuity detector.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "kern_contracts.py"
CORPUS = ROOT / "audits" / "codecheck"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=timeout)


def inject_into_copy(src: Path, candidate: str, out: Path) -> None:
    """Add `and (candidate)` to the existing requires, or insert a requires line."""
    lines = src.read_text(encoding="utf-8").splitlines()
    # Метка собирается из частей: иначе сканер замка считает этот инструмент
    # файлом с контрактами и требует его запечатать (дефект #290).
    mark = "@" + "kern:"
    req_re = re.compile(r"^(\s*(?:///|//|#)\s*" + re.escape(mark + "requires") + r"\s+)(.+?)\s*$")
    ens_re = re.compile(r"^\s*(?:///|//|#)\s*" + re.escape(mark + "ensures"))
    for i, ln in enumerate(lines):
        m = req_re.match(ln)
        if m:
            lines[i] = f"{m.group(1)}({m.group(2)}) and ({candidate})"
            break
    else:
        for i, ln in enumerate(lines):
            if ens_re.match(ln):
                indent = ln[: len(ln) - len(ln.lstrip())]
                lines.insert(i, f"{indent}# " + mark + f"requires {candidate}")
                break
        else:
            raise RuntimeError(f"{src}: no {mark}ensures to attach a requires to")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    fails: list[str] = []
    stats = {"files": 0, "skipped": 0, "hypotheses": 0,
             "self_sufficient": 0, "fragile": 0, "replayed": 0,
             "trivializing": 0}

    files = sorted(CORPUS.glob("*.py"))
    if not files:
        print(f"[FAIL] no python files in {CORPUS}")
        return 1

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        for src in files:
            stats["files"] += 1
            before = sha256(src)
            jpath = tmpdir / (src.stem + ".json")
            # Детерминизм сравниваем на ИДЕНТИЧНЫХ вызовах: раньше первый
            # прогон печатал лишнюю строку `JSON: <path>`, и разница в stdout
            # выдавалась за недетерминизм (артефакт проверки, не дефект).
            first = run("explain", "--hypotheses", str(src))
            second = run("explain", "--hypotheses", str(src))
            run("explain", "--hypotheses", str(src),
                "--hypotheses-json", str(jpath))
            after = sha256(src)

            if before != after:
                fails.append(f"{src.name}: input modified by the report")
                continue
            if first.returncode == 2:
                stats["skipped"] += 1   # unsupported body (nonlinear/recursive)
                continue
            if first.returncode != 0:
                fails.append(f"{src.name}: rc={first.returncode}")
                continue
            if first.stdout != second.stdout:
                fails.append(f"{src.name}: report is not deterministic")
            if not jpath.exists():
                fails.append(f"{src.name}: no JSON report")
                continue

            data = json.loads(jpath.read_text(encoding="utf-8"))
            if data.get("kind") != "hypothesis":
                fails.append(f"{src.name}: JSON kind is not 'hypothesis'")
            hyps = data.get("hypotheses") or []
            fn = data.get("function")
            if data.get("status") in ("proven", "unbounded") and not hyps:
                stats["skipped"] += 1
                continue
            for h in hyps:
                stats["hypotheses"] += 1
                cand = h.get("candidate", "")
                if h.get("fragile"):
                    stats["fragile"] += 1
                else:
                    stats["self_sufficient"] += 1

                copy = tmpdir / f"rt_{src.stem}_{stats['hypotheses']}.py"
                try:
                    inject_into_copy(src, cand, copy)
                except RuntimeError as exc:
                    fails.append(f"{src.name}: {exc}")
                    continue
                rt = run(str(copy))
                rtext = rt.stdout + rt.stderr
                stats["replayed"] += 1
                if f"[PASS] {fn}" not in rtext:
                    fails.append(
                        f"{src.name}: hypothesis `{cand}` does NOT prove {fn} "
                        f"when applied (rc={rt.returncode})")
                if "[VACUOUS]" in rtext:
                    fails.append(
                        f"{src.name}: `{cand}` makes the precondition contradictory "
                        f"(vacuous proof)")
                # «обнуляющая» гипотеза: домен сужается до тривиального
                if re.search(r"\b([A-Za-z_]\w*)\s*<=\s*0\b", cand) and h.get("fragile"):
                    stats["trivializing"] += 1

    print("hypotheses corpus report:")
    for k, v in stats.items():
        print(f"  {k:16s} {v}")
    for f in fails:
        print(f"[FAIL] {f}")
    if fails:
        print(f"\nHYPOTHESES CORPUS CHECK FAILED: {len(fails)} problem(s)")
        return 1
    print("\n[OK] read-only · deterministic · every hypothesis replayed to PROVEN · no vacuity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
