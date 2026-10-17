#!/usr/bin/env python3
"""Framework-agnostic agent gate — VERIFIED (stdlib only).

The pattern this file demonstrates is the one that actually matters: an agent proposes
code, KERN either admits it (`ok: true`) or refuses it with a counterexample, and the
agent must not proceed on a refusal.

    python3 examples/integrations/agent_loop.py

The "agent" below is deliberately dumb (it returns a broken implementation first) — the
point is the gate, not the model.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kern_guard import verify_files  # noqa: E402  (verified part)

CONTRACT = """# @kern:requires balance >= 0
# @kern:ensures  result <= balance and result >= 0
def withdraw(balance: int, amount: int) -> int:
    if amount > balance:
        return -1
    return balance - amount
"""

# Attempt 1: the missing `amount < 0` guard was added — but the early exit still returns
# `-1`, which violates the postcondition `result >= 0`. KERN refutes this too.
FIX_1 = CONTRACT.replace("    if amount > balance:", "    if amount < 0 or amount > balance:")

# Attempt 2: the early exit returns the balance itself, which satisfies both halves of
# `result <= balance and result >= 0`.
FIX_2 = FIX_1.replace("        return -1", "        return balance")


def propose_code(attempt: int) -> str:
    """Stand-in for the model: two wrong proposals, then a correct one."""
    return (CONTRACT, FIX_1, FIX_2)[min(attempt, 2)]


def gate(source: str) -> dict:
    """Write the proposal to a temp file and let KERN judge it."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "proposal.py"
        p.write_text(source, encoding="utf-8")
        verdict = verify_files([p])
    verdict.pop("raw", None)
    return verdict


def main() -> int:
    for attempt in range(3):
        source = propose_code(attempt)
        verdict = gate(source)
        print(f"--- attempt {attempt}: ok={verdict['ok']} "
              f"({', '.join(f'{k}={v}' for k, v in verdict.items() if k not in ('ok', 'functions'))})")
        for fn in verdict["functions"]:
            if fn["verdict"] != "proven":
                print(f"    REFUSED  {fn['name']}: {fn['verdict']}"
                      f"{' | counterexample: ' + fn['counterexample'] if fn['counterexample'] else ''}")
        if verdict["ok"]:
            print("    ADMITTED — every claim is proven by the solver; the gate opens (e=1).")
            return 0
        print("    the agent must fix the code (deleting the contract is a hard error)")
    print(json.dumps({"result": "the agent never satisfied the contract"}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
