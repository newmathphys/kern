#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Синхронизация чисел в документах из docs/facts.json.

ПРИНЦИП: число — данные, а не проза. В Markdown число остаётся видимым,
но рядом стоит невидимый якорь:

    <!-- fact:check_targets -->128

`make sync` пересчитывает факты и обновляет ТОЛЬКО число после якоря.
История, журнал дефектов и таблицы «было → стало» якорей не содержат,
поэтому физически не могут быть переписаны.

Использование:
    python3 tools/sync_state.py --write   # facts.json + якоря
    python3 tools/sync_state.py --check   # RC=1, если устарело
    python3 tools/sync_state.py --selftest
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "docs" / "facts.json"
SURFACES = (
    "README.md",
    "README.ru.md",
    "docs/index.html",
    "docs/ATTESTATION_PASSPORT.md",
    "docs/METRICS.md",
    "docs/METRICS.en.md",
    "docs/ROADMAP.md",
)
ANCHOR = re.compile(r"<!--\s*fact:([a-z0-9_.]+)\s*-->\s*(\d+)")
ANCHOR_ANY = re.compile(r"<!--\s*fact:([a-z0-9_.]+)\s*-->")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT,
                          capture_output=True, text=True, check=False)


def _fact_lean() -> int:
    out = _run([str(ROOT / "tools" / "check_lean_counter.py")])
    m = re.search(r"теорем Lean 4:\s*(\d+)", out.stdout)
    return int(m.group(1)) if m else 0


def _fact_quixbugs() -> dict:
    smt = 0
    p = ROOT / "docs" / "evidence" / "quixbugs_stage1.log"
    if p.exists():
        m = re.search(r"Ступень 1 .*?DIVERGED\s+(\d+)",
                      p.read_text(encoding="utf-8", errors="replace"))
        smt = int(m.group(1)) if m else 0
    full = (ROOT / "docs" / "evidence" / "quixbugs_full.log").read_text(
        encoding="utf-8", errors="replace")
    m = re.search(r"^  EXPLORED\s+(\d+)\s*$", full, re.M)
    explored = int(m.group(1)) if m else 0
    # Итоговая таблица лога: одна задача — одна строка (в отличие от [s2]-блоков,
    # которые переносятся и рвут regex на «buggy=RuntimeError: Set / correct=ok»).
    rows = [l for l in full.splitlines()
            if "DIVERGED" in l and "buggy=" in l and not l.startswith("  [s2]")]
    crash = hang = value = 0
    for l in rows:
        m = re.search(r"buggy=(.*?)\s+correct=", l)
        bug = m.group(1) if m else ""
        if "TIMEOUT" in bug:
            hang += 1
        elif re.search(r"(Error|Exception)", bug) or "broken-iter" in bug:
            crash += 1
        else:
            value += 1
    return {"smt": smt, "differential": len(rows), "crash": crash,
            "hang": hang, "value": value, "explored": explored}


def collect() -> dict:
    out = _run([str(ROOT / "tools" / "check_metrics_consistency.py"), "--json"])
    try:
        d = json.loads(out.stdout)
    except ValueError:
        raise SystemExit(f"[!] не удалось получить факты: {out.stdout[:200]}{out.stderr[:200]}")
    m = re.search(r'KERN_VERSION = "(v[0-9.]+)"',
                  (ROOT / "src" / "main.zig").read_text(encoding="utf-8"))
    return {
        "version": m.group(1) if m else "?",
        "core_tests": d["core_tests"],
        "next_tests": d["next_tests"],
        "catalog": d["catalog"],
        "check_targets": d["check_targets"],
        "canfail_cases": d["canfail_cases"],
        "mutation_sites": d["mutation_sites"],
        "mutation_files": d["mutation_files"],
        "registry_targets": d["registry_targets"],
        "meta_targets": d.get("meta_targets", 0),
        "anchors": d["canfail_anchors"],
        "lean_theorems": _fact_lean(),
        "quixbugs": _fact_quixbugs(),
    }


def lookup(facts, key: str):
    cur = facts
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(key)
        cur = cur[part]
    return cur


def render(text: str, facts) -> str:
    def sub(m: re.Match) -> str:
        return f"<!-- fact:{m.group(1)} -->{lookup(facts, m.group(1))}"
    return ANCHOR.sub(sub, text)


def check() -> int:
    if not FACTS.exists():
        print(f"[FAIL] нет {FACTS} — запустите make sync")
        return 1
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    live = collect()
    bad = 0
    if facts != live:
        print("[FAIL] docs/facts.json устарел — запустите make sync")
        for k in sorted(set(facts) | set(live)):
            if facts.get(k) != live.get(k):
                print(f"  {k}: facts={facts.get(k)!r} live={live.get(k)!r}")
        bad += 1
    for rel in SURFACES:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for key in ANCHOR_ANY.findall(text):
            try:
                lookup(facts, key)
            except KeyError:
                print(f"[FAIL] {rel}: неизвестный якорь fact:{key}")
                bad += 1
        for m in ANCHOR.finditer(text):
            key, got = m.group(1), int(m.group(2))
            exp = lookup(facts, key)
            if got != exp:
                print(f"[FAIL] {rel}: fact:{key} = {got}, факт {exp}")
                bad += 1
    if bad:
        print(f"\n[FAIL] расхождений: {bad}")
        return 1
    print("[OK] facts.json и все якоря совпадают с фактами")
    return 0


def write() -> int:
    facts = collect()
    FACTS.write_text(json.dumps(facts, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    changed = 0
    for rel in SURFACES:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        new = render(text, facts)
        if new != text:
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(new, encoding="utf-8")
            tmp.replace(p)
            changed += 1
            print(f"  updated {rel}")
    print(f"[OK] facts.json обновлён; файлов изменено: {changed}")
    return 0


def selftest() -> int:
    facts = {"check_targets": 128, "quixbugs": {"explored": 7}}
    clean = "x <!-- fact:check_targets -->128 y"
    stale = "x <!-- fact:check_targets -->125 y"
    hist = "| **125** | дефект: историческая запись |"
    bad = 0
    if render(clean, facts) != clean:
        print("[FAIL] selftest: чистый якорь изменён")
        bad += 1
    if render(clean, facts) != render(render(clean, facts), facts):
        print("[FAIL] selftest: рендер не идемпотентен")
        bad += 1
    if render(stale, facts) == stale:
        print("[FAIL] selftest: устаревший якорь не обновлён")
        bad += 1
    if render(hist, facts) != hist:
        print("[FAIL] selftest: история задета")
        bad += 1
    try:
        lookup(facts, "missing.key")
    except KeyError:
        pass
    else:
        print("[FAIL] selftest: неизвестный ключ не отвергнут")
        bad += 1
    print(f"[{'OK' if bad == 0 else 'FAIL'}] sync_state selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    if "--check" in args:
        return check()
    if "--write" in args:
        return write()
    print("usage: tools/sync_state.py [--write|--check|--selftest]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
