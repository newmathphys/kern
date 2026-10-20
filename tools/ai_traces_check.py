#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""No agent/LLM boilerplate in tracked files or commit messages.

This does NOT ban legitimate mentions of AI tools as MCP clients (Claude Code,
Cursor) or the project's own AI-safety examples. It bans *signatures* that an
assistant left in the text: "as an AI", "Generated with Claude",
"Co-Authored-By: Claude", etc.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = (
    r"\bas an AI\b",
    r"\bAs a language model\b",
    r"\bI cannot assist\b",
    r"\bI'm sorry, but I can't\b",
    r"Generated (with|by) (Claude|ChatGPT|Copilot|Cursor|Cline)",
    r"Co-Authored-By:.*(Claude|ChatGPT|Copilot|Cursor|Cline)",
    r"🤖 Generated with",
)
SKIP = (".git/", ".venv", "node_modules/", ".zig-cache/", "zig-out/",
        "docs/evidence/", "__pycache__/")


def hits(text: str) -> list[str]:
    out = []
    for pat in PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            out.append(m.group(0))
    return out


def tracked_files() -> list[Path]:
    raw = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    out = []
    for rel in raw.split(b"\0"):
        if not rel:
            continue
        rel_s = rel.decode("utf-8", "replace")
        if any(s in rel_s for s in SKIP):
            continue
        out.append(ROOT / rel_s)
    return out


def commit_bodies() -> list[str]:
    raw = subprocess.run(["git", "log", "-200", "--format=%B"], cwd=ROOT,
                         capture_output=True, text=True, check=False).stdout
    return raw.split("\n\n")


def selftest() -> int:
    bad = 0
    if hits("Claude Code and Cursor are MCP clients"):
        print("[FAIL] ai-traces selftest: легитимное упоминание Claude Code поймано")
        bad += 1
    if not hits("Generated with Claude"):
        print("[FAIL] ai-traces selftest: 'Generated with Claude' НЕ поймано")
        bad += 1
    if not hits("Co-Authored-By: Claude <noreply@anthropic.com>"):
        print("[FAIL] ai-traces selftest: Co-Authored-By Claude НЕ поймано")
        bad += 1
    print(f"[{'OK' if bad == 0 else 'FAIL'}] ai-traces selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    bad = 0
    checked = 0
    self_path = Path(__file__).resolve()
    for p in tracked_files():
        if p.resolve() == self_path:
            continue  # в selftest этого файла есть строки-подсадки
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "\0" in text[:1024]:
            continue
        checked += 1
        for h in hits(text):
            print(f"[FAIL] {p.relative_to(ROOT)}: {h!r}")
            bad += 1
    for body in commit_bodies():
        for h in hits(body):
            print(f"[FAIL] commit message: {h!r}")
            bad += 1
    if bad:
        print(f"\n[FAIL] следов ИИ-шаблонов: {bad}")
        return 1
    print(f"[OK] ИИ-шаблонов нет: проверено {checked} tracked-файлов и 200 коммитов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
