#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""EN/RU parity of numeric facts.

Every public document has an EN/RU pair. Prose is NOT compared (condensed
mirrors are allowed), but the same `<!-- fact:key -->N` anchors must exist in
both files and carry the same value. This is what keeps the English and
Russian showcases from drifting apart.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "docs" / "facts.json"
PAIRS = (
    ("README.md", "README.ru.md"),
    ("docs/ATTESTATION_PASSPORT.md", "docs/ATTESTATION_PASSPORT.en.md"),
    ("docs/ALL_CAPABILITIES_LIVE_GUIDE.ru.md", "docs/ALL_CAPABILITIES_LIVE_GUIDE.md"),
    ("docs/CAPABILITIES.md", "docs/CAPABILITIES.en.md"),
    ("docs/CAPABILITY_STATUS.md", "docs/CAPABILITY_STATUS.en.md"),
    ("docs/STATUS.ru.md", "docs/STATUS.md"),
    ("docs/SELF_VERIFICATION.ru.md", "docs/SELF_VERIFICATION.md"),
    ("docs/CHARTER.ru.md", "docs/CHARTER.md"),
    ("docs/CYBERNETIC_VISION.md", "docs/CYBERNETIC_VISION.en.md"),
    ("docs/METRICS.md", "docs/METRICS.en.md"),
    ("docs/ROADMAP.md", "docs/ROADMAP.en.md"),
    ("docs/TESTING_AND_SPEED_GUIDE.md", "docs/TESTING_AND_SPEED_GUIDE.en.md"),
)
REQUIRED = ("core_tests", "next_tests", "catalog", "check_targets",
            "canfail_cases", "anchors", "registry_targets", "meta_targets",
            "lean_theorems", "quixbugs.smt", "quixbugs.differential")
ANCHOR = re.compile(r"<!--\s*fact:([a-z0-9_.]+)\s*-->\s*(\d+)")


def anchors(path: Path) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    if not path.exists():
        return out
    for key, val in ANCHOR.findall(path.read_text(encoding="utf-8", errors="replace")):
        out.setdefault(key, set()).add(int(val))
    return out


def compare(ru: Path, en: Path, required=REQUIRED) -> list[str]:
    a, b = anchors(ru), anchors(en)
    errs: list[str] = []
    for key in required:
        if key not in a:
            errs.append(f"{ru}: нет якоря fact:{key}")
        if key not in b:
            errs.append(f"{en}: нет якоря fact:{key}")
        if key in a and key in b and a[key] != b[key]:
            errs.append(f"fact:{key}: {ru}={sorted(a[key])} != {en}={sorted(b[key])}")
    for key in (set(a) & set(b)) - set(required):
        if a[key] != b[key]:
            errs.append(f"fact:{key}: {ru}={sorted(a[key])} != {en}={sorted(b[key])}")
    return errs


def selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ru, en = Path(d) / "ru.md", Path(d) / "en.md"
        ru.write_text("<!-- fact:core_tests -->402 <!-- fact:check_targets -->128", encoding="utf-8")
        en.write_text("<!-- fact:core_tests -->402 <!-- fact:check_targets -->128", encoding="utf-8")
        ok = compare(ru, en, ("core_tests", "check_targets"))
        en.write_text("<!-- fact:core_tests -->401 <!-- fact:check_targets -->128", encoding="utf-8")
        bad = compare(ru, en, ("core_tests", "check_targets"))
    if ok:
        print(f"[FAIL] parity selftest: чистые пары дали {ok}")
        return 1
    if not bad:
        print("[FAIL] parity selftest: расхождение 402/401 НЕ поймано")
        return 1
    print("[OK] docs-parity selftest: расхождение ловится, чистые пары проходят")
    return 0


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    if not FACTS.exists():
        print(f"[FAIL] нет {FACTS} — запустите make sync")
        return 1
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    bad = 0
    for ru_rel, en_rel in PAIRS:
        errs = compare(ROOT / ru_rel, ROOT / en_rel)
        for e in errs:
            print(f"[FAIL] {e}")
            bad += 1
    if bad:
        print(f"\n[FAIL] EN/RU расхождений: {bad}")
        return 1
    print(f"[OK] EN/RU parity: {len(PAIRS)} пар, факты совпадают")
    print(f"     core {facts['core_tests']} · CHECK {facts['check_targets']} · "
          f"cases {facts['canfail_cases']} · targets {facts['registry_targets']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
