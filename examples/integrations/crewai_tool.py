#!/usr/bin/env python3
"""CrewAI tool wrapper — GLUE, NOT verified in this repository (CrewAI is not installed
here). The KERN side it calls (`kern_guard.verify_files`) IS verified.

    pip install crewai

The import path for the decorator differs between CrewAI releases
(`crewai.tools` in recent versions, `crewai_tools` in older ones) — adjust the single
import below; nothing else in this file depends on the framework.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kern_guard import verify_files  # noqa: E402  (the verified part)

try:
    from crewai.tools import tool
except ImportError as exc:  # pragma: no cover - glue
    raise SystemExit("This wrapper needs CrewAI: pip install crewai") from exc


@tool("KERN contract verifier")
def kern_verify_python(path: str) -> str:
    """Verify `@kern:requires` / `@kern:ensures` contracts of a Python file with KERN (Z3).

    Returns JSON: {"ok": bool, "violated": n, "vacuous": n, "functions": [...]}.
    If `ok` is false the implementation must not be used as-is — the counterexample shows
    the exact input that breaks it. A refuted contract must never be "fixed" by weakening
    or deleting the contract line (the sealed lock in docs/contracts.lock.json returns rc=2).
    """
    verdict = verify_files([path])
    verdict.pop("raw", None)
    return json.dumps(verdict, ensure_ascii=False)
