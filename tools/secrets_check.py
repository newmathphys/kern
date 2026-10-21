#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: поиск секретов в отслеживаемых файлах (шаг 0K.4).

ЗАЧЕМ. В переписке с агентом дважды оказывались ключи (`nvapi-…`,
`sk-or-v1-…`) — класс «секрет попал в текст» реален. В репозитории такое
обязано ловиться машинно, а не «на глаз при ревью».

Что ищем: ключи провайдеров и приватные ключи в PEM. Совпадение печатается
в РЕДАКТИРОВАННОМ виде (префикс + длина), чтобы лог сам не стал утечкой.

Область: `git ls-files` (то, что реально уедет в репозиторий). Проверяющий
скрипт исключён — в нём шаблоны обязаны быть. История коммитов
сканируется только по флагу `--history N` и даёт ПРЕДУПРЕЖДЕНИЯ
(переписать историю нельзя, но знать надо).

Код возврата: 0 — чисто; 1 — найдены секреты; 2 — ошибка входа.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = "tools/secrets_check.py"

# (имя, шаблон). Шаблоны намеренно узкие: лучше пропустить экзотическое,
# чем завалить сборку ложными находками (проверка, которая «всегда красная»,
# бесполезна так же, как проверка, которая не умеет падать).
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("nvidia-nvapi", re.compile(r"nvapi-[A-Za-z0-9_\-]{20,}")),
    ("openrouter", re.compile(r"sk-or-v1-[0-9a-f]{32,}")),
    ("openai", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("github-pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
]

SKIP_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".wasm", ".o",
               ".pdf", ".zip", ".gz", ".lock")


def redact(s: str) -> str:
    """Префикс + длина: лог не должен становиться второй утечкой."""
    return f"{s[:10]}…({len(s)} симв.)"


def scan_text(rel: str, text: str) -> list[dict]:
    out: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:          # минифицированные бандлы не полезны
            continue
        for name, rx in PATTERNS:
            for m in rx.finditer(line):
                out.append({"file": rel, "line": lineno, "kind": name,
                            "match": redact(m.group(0))})
    return out

def tracked_files() -> list[Path]:
    r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [ROOT / p for p in r.stdout.splitlines() if p]


def scan_files(paths: list[Path]) -> list[dict]:
    found: list[dict] = []
    for p in paths:
        try:
            rel = p.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            rel = p.as_posix()
        if rel == SELF or p.suffix.lower() in SKIP_SUFFIX or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found.extend(scan_text(rel, text))
    return found


def scan_history(n: int) -> list[dict]:
    r = subprocess.run(["git", "log", f"-{n}", "--format=%H%x00%B%x00"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    out: list[dict] = []
    parts = r.stdout.split("\x00")
    for i in range(0, len(parts) - 1, 2):
        sha, body = parts[i].strip(), parts[i + 1]
        for name, rx in PATTERNS:
            for m in rx.finditer(body):
                out.append({"commit": sha[:12], "kind": name, "match": redact(m.group(0))})
    return out


def selftest() -> int:
    """7 подсадок обязаны ловиться, 4 чистых строки — НЕ ловиться."""
    bad_cases = [
        "nvapi-" + "A" * 30,
        "sk-or-v1-" + "0123456789abcdef" * 4,
        "ghp_" + "b" * 36,
        "AKIA" + "Q" * 16,
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "sk-ant-api03-" + "z" * 30,
        "AIza" + "k" * 35,
    ]
    clean = [
        "nvapi-… (ключ отозван)",                                  # многоточие
        "ключи вида sk-or-v1-<64 hex> не хранятся в репозитории",  # описание
        "-----BEGIN PUBLIC KEY-----",                              # публичный ключ
        "AKIA… (публичный пример AWS, значения нет)",              # многоточие
    ]
    fails = 0
    for s in bad_cases:
        if not scan_text("t", s):
            print(f"  [FAIL] подсадка НЕ поймана: {s[:16]}…")
            fails += 1
    for s in clean:
        if scan_text("t", s):
            print(f"  [FAIL] ложное срабатывание: {s[:40]}…")
            fails += 1
    print(f"  [{'OK' if not fails else 'FAIL'}] selftest: "
          f"{len(bad_cases)} подсадок / {len(clean)} чистых, ошибок {fails}")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Поиск секретов в отслеживаемых файлах")
    ap.add_argument("--path", action="append", default=[],
                    help="сканировать файл (можно много)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--history", type=int, default=0,
                    help="проверить N последних коммитов (только предупреждения)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    paths = [Path(p) for p in args.path] if args.path else tracked_files()
    if not paths:
        print("[FAIL] нет файлов для проверки (git ls-files пуст?)")
        return 2

    found = scan_files(paths)
    warn = scan_history(args.history) if args.history > 0 else []

    if args.json:
        print(json.dumps({"findings": found, "history_warnings": warn,
                          "scanned": len(paths)}, ensure_ascii=False, indent=2))
    else:
        for f in found:
            print(f"  [СЕКРЕТ] {f['file']}:{f['line']}  {f['kind']}: {f['match']}")
        for w in warn:
            print(f"  [WARN] история {w['commit']}: {w['kind']}: {w['match']}")
        tail = f", предупреждений истории: {len(warn)}" if warn else ""
        print(f"\n[{'FAIL' if found else 'OK'}] проверено файлов: {len(paths)}, "
              f"находок: {len(found)}{tail}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
