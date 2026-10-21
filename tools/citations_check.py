#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: библиография как данные (шаг 0J).

Проверяет не «файл существует», а согласованность утверждений:

  1. у каждой записи `docs/references.bib` есть идентификатор
     (doi / isbn / eprint / url) и статус verified|secondary|unverified;
  2. `references.lock.json` совпадает с bib по doi и pages
     (сдвиг страницы или последней цифры DOI — ошибка);
  3. каждый `§REF:key` в `docs/BELNAP_SOURCES.md` и `.en.md` существует;
  4. `unverified` встречается ТОЛЬКО в §7 (иначе это цитирование как основания);
  5. ссылки `src/путь:строка` и `formal/файл.lean:теорема` реальны;
  6. RU и EN содержат одинаковый набор ключей.

Запуск:
  python3 tools/citations_check.py [--json]
  python3 tools/citations_check.py --selftest      # 5 диверсий обязаны ловиться
  python3 tools/citations_check.py --docs-dir /tmp/x   # для canfail
Код возврата: 0 — всё сошлось; 1 — расхождения; 2 — нет входа.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF_RE = re.compile(r"§REF:([A-Za-z0-9_][A-Za-z0-9_.\-]*)")
SRC_RE = re.compile(r"`(src/[A-Za-z0-9_./\-]+\.zig):(\d+)`")
LEAN_RE = re.compile(r"`(formal/[A-Za-z0-9_./\-]+\.lean):([A-Za-z_][A-Za-z0-9_']*)`")
SECTION_RE = re.compile(r"^##\s*§(\d+)")


def parse_bib(text: str) -> dict[str, dict[str, str]]:
    """Минимальный BibTeX: @type{key, field = {value}, ...}."""
    entries: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"@(\w+)\{([^,]+),", text):
        key = m.group(2).strip()
        body_start = m.end()
        depth, i = 1, body_start
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[body_start:i - 1]
        fields: dict[str, str] = {"type": m.group(1).lower()}
        for fm in re.finditer(r"(\w+)\s*=\s*\{(.*?)\}\s*,?", body, re.S):
            fields[fm.group(1).lower()] = " ".join(fm.group(2).split())
        entries[key] = fields
    return entries


def sections(text: str) -> list[tuple[int, str]]:
    """Разбивает документ на (номер_§, текст)."""
    parts: list[tuple[int, str]] = []
    cur_no, cur = 0, []
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            parts.append((cur_no, "\n".join(cur)))
            cur_no, cur = int(m.group(1)), [line]
        else:
            cur.append(line)
    parts.append((cur_no, "\n".join(cur)))
    return parts


def validate(bib: dict[str, dict[str, str]], lock: dict, docs: dict[str, str]) -> list[str]:
    errs: list[str] = []
    for key, f in bib.items():
        status = f.get("status", "")
        if status not in ("verified", "secondary", "unverified"):
            errs.append(f"bib {key}: нет корректного status ({status!r})")
        has_id = any(f.get(k) for k in ("doi", "isbn", "eprint", "url"))
        if status == "unverified":
            # Для неподтверждённой записи идентификатора может не быть — но
            # тогда обязана быть пометка, ЧТО именно искали и не нашли.
            if not f.get("note"):
                errs.append(f"bib {key}: unverified без note (чем подтверждён поиск?)")
        elif not has_id:
            errs.append(f"bib {key}: нет идентификатора (doi/isbn/eprint/url)")

    for key, le in lock.items():
        if key not in bib:
            errs.append(f"lock {key}: записи нет в bib")
            continue
        f = bib[key]
        if le.get("status") == "verified" and f.get("status") != "verified":
            errs.append(f"lock {key}: status verified, а в bib {f.get('status')!r}")
        if le.get("doi") and f.get("doi") and le["doi"].lower() != f["doi"].lower():
            errs.append(f"lock {key}: doi {le['doi']} != bib {f['doi']}")
        if le.get("pages") and f.get("pages") and le["pages"] != f["pages"]:
            errs.append(f"lock {key}: pages {le['pages']} != bib {f['pages']}")

    keys_by_doc: dict[str, set[str]] = {}
    for name, text in docs.items():
        used: set[str] = set()
        for sec_no, body in sections(text):
            for m in REF_RE.finditer(body):
                key = m.group(1)
                used.add(key)
                if key not in bib:
                    errs.append(f"{name}: §REF:{key} — неизвестный ключ")
                elif bib[key].get("status") == "unverified" and sec_no != 7:
                    errs.append(f"{name}: §REF:{key} (unverified) вне §7 (в §{sec_no})")
            for m in SRC_RE.finditer(body):
                p, ln = ROOT / m.group(1), int(m.group(2))
                if not p.exists():
                    errs.append(f"{name}: {m.group(1)} не существует")
                elif ln < 1 or ln > len(p.read_text(encoding='utf-8', errors='replace').splitlines()):
                    errs.append(f"{name}: {m.group(1)}:{ln} — строка за пределами файла")
            for m in LEAN_RE.finditer(body):
                p, thm = ROOT / m.group(1), m.group(2)
                if not p.exists():
                    errs.append(f"{name}: {m.group(1)} не существует")
                elif not re.search(rf"^theorem\s+{re.escape(thm)}\b", p.read_text(
                        encoding="utf-8", errors="replace"), re.M):
                    errs.append(f"{name}: теоремы {thm} нет в {m.group(1)}")
        keys_by_doc[name] = used

    if len(keys_by_doc) == 2:
        (na, ka), (nb, kb) = list(keys_by_doc.items())
        if ka != kb:
            only_a, only_b = sorted(ka - kb), sorted(kb - ka)
            errs.append(f"RU/EN различаются ключами: только в {na}: {only_a}; только в {nb}: {only_b}")
    return errs

def selftest() -> int:
    """5 диверсий обязаны ловиться; чистая пара — НЕ ловиться."""
    bib_text = """
@article{good, title = {A}, doi = {10.1/x}, pages = {1-2}, status = {verified}, year = {2020}}
@misc{bad, title = {B}, status = {unverified}, year = {2021}, note = {not found}}
"""
    lock = {"good": {"doi": "10.1/x", "pages": "1-2", "status": "verified"}}
    good_doc = ("## §1 Primary\nsee §REF:good and `src/core/eq2.zig:18`\n"
                "## §7 Drafts\nbad but allowed: §REF:bad\n")

    fails = 0

    def expect(name: str, errs: list[str]) -> None:
        nonlocal fails
        if not errs:
            print(f"  [FAIL] диверсия НЕ поймана: {name}")
            fails += 1

    base = parse_bib(bib_text)
    if validate(base, lock, {"ru": good_doc, "en": good_doc}):
        print("  [FAIL] чистая пара дала ошибки:", validate(base, lock, {"ru": good_doc, "en": good_doc}))
        fails += 1

    expect("неизвестный ключ",
           validate(base, lock, {"ru": good_doc + "§REF:ghost\n", "en": good_doc + "§REF:ghost\n"}))
    expect("строка за EOF",
           validate(base, lock, {"ru": good_doc + "`src/core/eq2.zig:99999`\n",
                                 "en": good_doc + "`src/core/eq2.zig:99999`\n"}))
    no_id = parse_bib("@misc{noid, title = {C}, status = {verified}, year = {2020}}\n")
    expect("запись без идентификатора", validate(no_id, {}, {"ru": "## §1\n§REF:noid\n",
                                                              "en": "## §1\n§REF:noid\n"}))
    expect("сдвиг страниц", validate(base, {"good": {"doi": "10.1/x", "pages": "1-3"}},
                                     {"ru": good_doc, "en": good_doc}))
    expect("DOI на цифру", validate(base, {"good": {"doi": "10.1/y", "pages": "1-2"}},
                                    {"ru": good_doc, "en": good_doc}))
    print(f"  [{'OK' if not fails else 'FAIL'}] selftest: 5 диверсий, ошибок {fails}")
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверить библиографию KERN")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--docs-dir", type=Path, default=ROOT / "docs")
    ap.add_argument("--bib", type=Path, default=ROOT / "docs" / "references.bib")
    ap.add_argument("--lock", type=Path, default=ROOT / "docs" / "references.lock.json")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.bib.exists() or not args.lock.exists():
        print(f"[FAIL] нет {args.bib} или {args.lock}")
        return 2

    bib = parse_bib(args.bib.read_text(encoding="utf-8", errors="replace"))
    lock = json.loads(args.lock.read_text(encoding="utf-8")).get("entries", {})
    docs: dict[str, str] = {}
    for name in ("BELNAP_SOURCES.md", "BELNAP_SOURCES.en.md"):
        p = args.docs_dir / name
        if p.exists():
            docs[name] = p.read_text(encoding="utf-8", errors="replace")
    if not docs:
        print(f"[FAIL] в {args.docs_dir} нет BELNAP_SOURCES.md")
        return 2

    errs = validate(bib, lock, docs)
    if args.json:
        print(json.dumps({"entries": len(bib), "locked": len(lock),
                          "docs": sorted(docs), "errors": errs},
                         ensure_ascii=False, indent=2))
    else:
        for e in errs:
            print(f"  [FAIL] {e}")
        print(f"\n[{'OK' if not errs else 'FAIL'}] записей {len(bib)}, "
              f"в замке {len(lock)}, документов {len(docs)}, "
              f"расхождений {len(errs)}")
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
