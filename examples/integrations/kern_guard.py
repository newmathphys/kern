#!/usr/bin/env python3
"""KERN guard — turn the contract checker into a plain function any agent framework can call.

VERIFIED PART: this module uses only the standard library and shells out to
`tools/kern_contracts.py` (which needs `kernc` built and `z3` in PATH). Run it:

    python3 examples/integrations/kern_guard.py examples/contracts_demo.py

It prints a JSON verdict per function, so an agent can act on it:

    {"ok": false, "proven": 7, "violated": 1, "vacuous": 1, "skipped": 1,
     "functions": [{"name": "withdraw_missing_neg", "verdict": "violated",
                    "counterexample": "balance = 0, amount = -1, result = 1",
                    "runtime_confirmed": true}, ...]}

The framework wrappers next to this file (`langchain_tool.py`, `crewai_tool.py`) are thin
glue that needs that framework installed — the KERN side they call is this verified part.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "tools" / "kern_contracts.py"

VERDICT_LINE = re.compile(r"^\s*\[(PASS|FAIL|VACUOUS|DIVERGED|SECURITY)\]\s+([^:]+):\s*(.*)$")
COUNTEREXAMPLE = re.compile(r"^\s*\[(?:КОНТРПРИМЕР|COUNTEREXAMPLE)\]\s*(.*)$")
RUNTIME_CONFIRMED = "RUNTIME CONFIRMED"

# The tool prints Russian verdict words on purpose: the can-fail gates in
# tools/canfail.py and tools/mcp_selftest.py match those exact strings.
RU = {
    "ДОКАЗАНО": "proven",
    "КОНТРАКТ НАРУШЕН": "violated",
    "ДЕЛЕНИЕ НА НОЛЬ": "violated",          # division by zero
    "ПЕРЕПОЛНЕНИЕ": "violated",             # integer overflow / underflow
    "ПРОТИВОРЕЧИВО": "vacuous",             # contradictory precondition
    "ИЗМЕНИЛ ПОВЕДЕНИЕ": "diverged",        # refactoring changed behaviour
    "УДАЛЁН": "contract_removed",           # sealed contract deleted
}


def _classify(tag: str, text: str) -> str:
    for needle, verdict in RU.items():
        if needle in text:
            return verdict
    return {"PASS": "proven", "FAIL": "violated", "VACUOUS": "vacuous",
            "DIVERGED": "diverged", "SECURITY": "contract_removed"}.get(tag, "unknown")


def run_contracts(paths, extra_args=(), timeout=900):
    """Run tools/kern_contracts.py and return (returncode, raw_output)."""
    cmd = [sys.executable, str(CONTRACTS), *[str(p) for p in paths], *extra_args]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse(raw: str) -> dict:
    """Parse the checker output into a machine-readable verdict."""
    functions, current = [], None
    for line in raw.splitlines():
        m = VERDICT_LINE.match(line)
        if m:
            tag, name, text = m.group(1), m.group(2).strip(), m.group(3)
            current = {"name": name, "verdict": _classify(tag, text),
                       "detail": text.strip(), "counterexample": None,
                       "runtime_confirmed": False}
            functions.append(current)
            continue
        ce = COUNTEREXAMPLE.match(line)
        if ce and current is not None:
            current["counterexample"] = ce.group(1).strip()
            continue
        if RUNTIME_CONFIRMED in line and current is not None:
            current["runtime_confirmed"] = True
        if "SKIP" in line and current is None:
            functions.append({"name": line.strip().split(":")[0].strip() or line.strip(),
                              "verdict": "skipped", "detail": line.strip(),
                              "counterexample": None, "runtime_confirmed": False})

    counts = {}
    for f in functions:
        counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1
    ok = bool(functions) and all(f["verdict"] == "proven" for f in functions)
    return {"ok": ok, **counts, "functions": functions}


def verify_files(paths) -> dict:
    """Check contracts in the given files and return the structured verdict."""
    rc, raw = run_contracts(paths)
    verdict = parse(raw)
    verdict["returncode"] = rc
    verdict["raw"] = raw
    return verdict


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    verdict = verify_files(argv[1:])
    raw = verdict.pop("raw")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    if not verdict["ok"]:
        print("\n--- raw checker output ---", file=sys.stderr)
        print(raw, file=sys.stderr)
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
