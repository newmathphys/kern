#!/usr/bin/env python3
"""LangChain tool wrapper — GLUE, NOT verified in this repository (LangChain is not
installed here). The KERN side it calls (`kern_guard.verify_files`) IS verified.

    pip install langchain-core
    python3 -c "from examples.integrations.langchain_tool import kern_verify_python as t; print(t.name)"

If your LangChain version exposes a different import path, adjust the one import line —
the rest of the file does not depend on the framework.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kern_guard import verify_files  # noqa: E402  (the verified part)

try:  # langchain-core >= 0.1
    from langchain_core.tools import tool
except ImportError as exc:  # pragma: no cover - glue
    raise SystemExit("This wrapper needs LangChain: pip install langchain-core") from exc


@tool
def kern_verify_python(path: str) -> str:
    """Verify the `@kern:requires` / `@kern:ensures` contracts of a Python file with KERN.

    KERN checks the contracts with Z3 and returns a JSON verdict. If `ok` is false the code
    is NOT correct: the counterexample gives the exact inputs that break the contract. Never
    "fix" this by deleting or weakening a contract line — the contract lock will refuse it.
    """
    verdict = verify_files([path])
    verdict.pop("raw", None)
    return json.dumps(verdict, ensure_ascii=False)
