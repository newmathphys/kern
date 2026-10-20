#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Страж витрины: граф Эго-Линзы и карта потока обязаны совпадать с кодом.

ЗАЧЕМ. На главной странице появились интерактивные элементы: Эго-Линза
(граф импортов) и матрица фильтров (метки модулей). Если `showcase-graph.json`
отстанет от `src/`, витрина начнёт показывать несуществующие связи — тот же
класс дефекта, что «125/125 CHECK» при факте 128 (#224).

ЧТО ПРОВЕРЯЕТ.
  1. `docs/showcase-graph.json` байт-в-байт воспроизводится из `src/**/*.zig`;
  2. каждый узел — реальный файл, каждое ребро ссылается на существующие узлы;
  3. метки (claims) выводятся из измерений, а не вписаны руками;
  4. `docs/index.html` действительно ссылается на граф и карту потока;
  5. SVG карты потока существует, имеет канонический namespace и непуст.

Запуск:  python3 tools/showcase_check.py [--selftest]
Код возврата: 0 — согласовано, 1 — расхождение.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "docs" / "showcase-graph.json"
INDEX = ROOT / "docs" / "index.html"
FLOW = ROOT / "docs" / "kern-proof-flow.svg"
SRC = ROOT / "src"


def _load_gen():
    spec = importlib.util.spec_from_file_location(
        "gen_showcase_graph", ROOT / "tools" / "gen_showcase_graph.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def verify(data: dict, fresh: dict, index_html: str) -> list[str]:
    """Все нарушения согласованности. Пустой список = витрина честная."""
    p: list[str] = []
    if data.get("schema") != 1:
        p.append(f"schema != 1: {data.get('schema')!r}")

    # 1. Воспроизводимость из исходников.
    if data != fresh:
        old_nodes = {n["id"]: n for n in data.get("nodes", [])}
        new_nodes = {n["id"]: n for n in fresh.get("nodes", [])}
        only_old = sorted(set(old_nodes) - set(new_nodes))
        only_new = sorted(set(new_nodes) - set(old_nodes))
        if only_old:
            p.append(f"узлы без файла в src/: {only_old[:5]}")
        if only_new:
            p.append(f"в src/ есть модули вне карты: {only_new[:5]}")
        for k in sorted(set(old_nodes) & set(new_nodes)):
            if old_nodes[k] != new_nodes[k]:
                p.append(f"метрики расходятся: {k}")
                break
        if len(data.get("edges", [])) != len(fresh.get("edges", [])):
            p.append(f"рёбер в файле {len(data.get('edges', []))}, "
                     f"в коде {len(fresh.get('edges', []))}")
        if not p:
            p.append("файл графа расходится с src/ (перегенерируйте make showcase)")

    # 2. Целостность ссылок.
    ids = {n["id"] for n in data.get("nodes", [])}
    for e in data.get("edges", []):
        if e.get("source") not in ids or e.get("target") not in ids:
            p.append(f"ребро ведёт в несуществующий узел: {e}")
            break
        if e.get("source") == e.get("target"):
            p.append(f"петля в графе импортов: {e['source']}")
            break

    # 3. Узлы соответствуют реальным файлам.
    on_disk = {f.relative_to(SRC).as_posix() for f in SRC.rglob("*.zig")}
    if ids != on_disk:
        p.append(f"набор узлов != набор файлов src/ "
                 f"(лишние {sorted(ids - on_disk)[:3]}, "
                 f"пропущены {sorted(on_disk - ids)[:3]})")

    # 4. Витрина ссылается на данные, а не на картинку-заглушку.
    for needle in ("showcase-graph.json", "kern-proof-flow.svg", "lens-svg",
                   "fm-chips"):
        if needle not in index_html:
            p.append(f"docs/index.html не содержит {needle!r}")
    if "kern-proof-flow.svg" not in index_html:
        p.append("карта потока не встроена на витрину")
    return p


def check_flow_svg() -> list[str]:
    p: list[str] = []
    if not FLOW.exists():
        return [f"нет {FLOW.relative_to(ROOT)}"]
    svg = FLOW.read_text(encoding="utf-8")
    if 'xmlns="http://www.w3.org/2000/svg"' not in svg:
        p.append("карта потока: неканонический namespace")
    for word in ("import", "asserted", "proof-step", "CEGIS", "join_K(T,F) = B"):
        if word not in svg:
            p.append(f"карта потока: нет обязательной подписи {word!r}")
    return p


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        fresh = _load_gen().build()
        html = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
        ok = verify(copy.deepcopy(fresh), fresh, html)
        if ok:
            print(f"[!] selftest: чистые данные дали нарушения: {ok[:2]}")
            return 1
        broken = copy.deepcopy(fresh)
        broken["nodes"][0]["claims"] = ["#lang/rust"]
        bad1 = verify(broken, fresh, html)
        dropped = copy.deepcopy(fresh)
        dropped["nodes"] = dropped["nodes"][1:]
        bad2 = verify(dropped, fresh, html)
        bad3 = verify(copy.deepcopy(fresh), fresh, html.replace("lens-svg", "x"))
        if not (bad1 and bad2 and bad3):
            print(f"[!] selftest: страж НЕ поймал диверсию "
                  f"(claims={bool(bad1)}, node={bool(bad2)}, html={bool(bad3)})")
            return 1
        print(f"[OK] selftest: 3 диверсии пойманы, чистые данные приняты")
        return 0

    if not GRAPH.exists():
        print(f"[!] нет {GRAPH.relative_to(ROOT)} — запустите make showcase")
        return 1
    data = json.loads(GRAPH.read_text(encoding="utf-8"))
    fresh = _load_gen().build()
    html = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
    problems = verify(data, fresh, html) + check_flow_svg()
    n, e = len(data.get("nodes", [])), len(data.get("edges", []))
    print(f"SHOWCASE: {n} модулей, {e} рёбер, "
          f"{len(data.get('claims_vocabulary', {}))} меток")
    if problems:
        print("НАРУШЕНИЯ:")
        for x in problems:
            print(f"  - {x}")
        return 1
    print("[OK] граф Эго-Линзы и карта потока совпадают с кодом")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
