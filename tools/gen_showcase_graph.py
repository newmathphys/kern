#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Собрать docs/showcase-graph.json из РЕАЛЬНЫХ данных `src/*.zig`.

ЗАЧЕМ. На витрине есть «Эго-Линза» (радиус 1-2 шага по графу импортов) и
матрица фильтров [+][~][-][=]. Если бы граф и метки рисовались вручную, через
месяц они разошлись бы с кодом — ровно тот класс дефекта, из-за которого
появился `make sync` (число — данные, а не проза).

ЧТО ДЕЛАЕТ. Парсит `@import("...")` в `src/**/*.zig`, считает по каждому
модулю РЕАЛЬНЫЕ метрики (строки, `pub fn`, `test "`, `@kern:`-аннотации,
исходящие импорты) и выводит метки (claims), по которым работает фильтр.
Ни одной метки, которая не проверяется повторным разбором.

Запуск:  python3 tools/gen_showcase_graph.py [--check]
Код возврата: 0 — файл актуален, 1 — расходится с кодом (--check).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OUT = ROOT / "docs" / "showcase-graph.json"
NAMED = {"compat": "compat.zig", "owner": "owner.zig", "atomic": "atomic_write.zig"}

IMPORT_RE = re.compile(r'@import\("([^"]+)"\)')
TEST_RE = re.compile(r'\n\s*test\s+"')
PUBFN_RE = re.compile(r'\npub fn ')
KERN_RE = re.compile(r'@kern:')


def claims_for(rel: str, loc: int, pub_fn: int, tests: int, kern: int,
               out_edges: int) -> list[str]:
    """Метки модуля. Каждая выводится из измерения, не из названия."""
    tags = ["#lang/zig"]
    for area in ("core", "verifier", "next", "runtime"):
        if rel.startswith(area + "/"):
            tags.append(f"#area/{area}")
    if kern:
        tags.append("#has-contract")
    else:
        tags.append("#no-contract")
    if tests:
        tags.append("#tested")
    else:
        tags.append("#untested")
    if out_edges == 0:
        tags.append("#leaf")
    elif out_edges >= 5:
        tags.append("#hub")
    if loc >= 500:
        tags.append("#large")
    else:
        tags.append("#small")
    if pub_fn == 0:
        tags.append("#internal-only")
    else:
        tags.append("#public-api")
    return tags


def build() -> dict:
    files = sorted(SRC.rglob("*.zig"))
    rel_of = lambda p: p.relative_to(SRC).as_posix()
    ids = {rel_of(p) for p in files}
    raw_edges: set[tuple[str, str]] = set()
    for p in files:
        src = rel_of(p)
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in IMPORT_RE.finditer(txt):
            imp = m.group(1)
            target = None
            if imp.startswith("."):
                try:
                    target = (p.parent / imp).resolve().relative_to(
                        SRC.resolve()).as_posix()
                except ValueError:
                    target = None
            elif imp in NAMED:
                cand = NAMED[imp]
                if cand in ids:
                    target = cand
                else:
                    for i in ids:
                        if i.endswith("/" + cand):
                            target = i
                            break
            if target in ids and target != src:
                raw_edges.add((src, target))

    out_count = {i: 0 for i in ids}
    for a, _b in raw_edges:
        out_count[a] += 1

    nodes = []
    for p in files:
        rel = rel_of(p)
        txt = p.read_text(encoding="utf-8", errors="replace")
        loc = txt.count("\n") + (0 if txt.endswith("\n") else 1)
        pub_fn = len(PUBFN_RE.findall(txt))
        tests = len(TEST_RE.findall(txt))
        kern = len(KERN_RE.findall(txt))
        nodes.append({
            "id": rel,
            "loc": loc,
            "pub_fn": pub_fn,
            "tests": tests,
            "kern_annotations": kern,
            "imports_out": out_count[rel],
            "claims": claims_for(rel, loc, pub_fn, tests, kern, out_count[rel]),
        })

    roots = [r for r in (
        "main.zig", "next/main.zig", "verifier/proof_check.zig",
        "verifier/z3_bridge.zig", "core/kimg_reader.zig", "next/truth.zig",
        "verifier/chc.zig", "verifier/cegis.zig", "core/kernfs_router.zig",
        "verifier/admission_gate.zig", "proof_cache.zig",
    ) if r in ids]

    vocab: dict[str, int] = {}
    for n in nodes:
        for c in n["claims"]:
            vocab[c] = vocab.get(c, 0) + 1

    return {
        "schema": 1,
        "source": "src/**/*.zig parsed for @import / test / pub fn / @kern:",
        "note": ("Реальные рёбра импортов и метрики. Эго-Линза показывает "
                 "радиус 1-2; фильтр [+][~][-] работает по полю claims."),
        "roots": roots,
        "claims_vocabulary": dict(sorted(vocab.items())),
        "nodes": nodes,
        "edges": [{"source": a, "target": b, "kind": "import"}
                  for a, b in sorted(raw_edges)],
    }


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str]) -> int:
    data = build()
    text = render(data)
    if "--check" in argv:
        if not OUT.exists():
            print(f"[!] нет {OUT.relative_to(ROOT)} — запустите make showcase")
            return 1
        if OUT.read_text(encoding="utf-8") != text:
            print(f"[!] {OUT.relative_to(ROOT)} расходится с src/ — "
                  f"запустите make showcase")
            return 1
        print(f"[OK] {OUT.relative_to(ROOT)}: {len(data['nodes'])} модулей, "
              f"{len(data['edges'])} рёбер, {len(data['claims_vocabulary'])} меток")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"[OK] {OUT.relative_to(ROOT)}: {len(data['nodes'])} модулей, "
          f"{len(data['edges'])} рёбер, {len(data['claims_vocabulary'])} меток")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
