#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: Apache-2.0
"""`release_assets_check.py` — тег БЕЗ релиза и релиз БЕЗ ассетов — это дыра.

ЗАЧЕМ (дефект #652, ИЗМЕРЕНО). 21 тег подряд (`v2.8.4`…`v2.8.24`) ушёл в origin
БЕЗ опубликованного релиза: `GET /releases` отдавал последним `v2.8.3`. Ни один
гейт об этом не сказал — `version-check` сверяет 14 поверхностей МЕЖДУ СОБОЙ, но
не факт публикации. Причина замыкалась сама на себя: `examples/ci/kern-gate.yml`
пиннил v2.8.3 (последний релиз, у которого ЕСТЬ ассеты), `action-check REAL=1`
честно падал на этом пиннинге и блокировал публикацию, а без публикации пиннинг
некуда было обновить.

ПОЧЕМУ ЗДЕСЬ НЕТ КУРИЦЫ И ЯЙЦА. Гейт по умолчанию работает ОФЛАЙН и проверяет
свой ДВУСТОРОННИЙ контракт на фикстурах (`--selftest`), поэтому его можно держать
в `ci-fast`: он никогда не ходит в сеть и не может упасть из-за того, что релиза
текущей версии ещё физически нет. Живая проверка — отдельный режим `--online`,
который запускается ПОСЛЕ публикации (шаг post-release в release.yml) и/или по
расписанию, и опирается на `--expect-tag`.

ИНВАРИАНТЫ (одни и те же в обоих режимах):
  1. `--expect-tag vX.Y.Z` -> релиз обязан существовать и содержать ВСЕ ассеты;
  2. разрыв «максимальный тег vs последний опубликованный релиз» не больше
     допустимого (по умолчанию 1: сам bump-коммит ещё не издан; после релиза — 0).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

# Разрыв, который считается нормой. 1 — «тег нарезан, релиз ещё не создан»
# (ровно состояние bump-коммита). Больше — это уже мёртвые теги.
MAX_TAG_GAP = 1
REQUIRED = ("kerna-dist-v{ver}.tar.gz", "kernc-x86_64-linux-musl", "SHA256SUMS")
# ВНИМАНИЕ (нашёл сам себя, ИЗМЕРЕНО на первом же живом прогоне): имя архива в
# релизе содержит `v` (`kerna-dist-v2.8.25.tar.gz`) — ровно так его публикует
# release.yml (`dist-release/kerna-dist-v${VER}.tar.gz`). Шаблон без `v` объявлял
# КОРРЕКТНЫЙ релиз «без ассетов» — ложное обвинение в самом гейте.



def _vkey(tag: str) -> tuple[int, ...]:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    return tuple(int(x) for x in m.groups()) if m else ()


def _sorted_tags(tags: list[str]) -> list[str]:
    return sorted((t for t in tags if _vkey(t)), key=_vkey, reverse=True)


def check(tags: list[str], releases: list[dict], expect_tag: str | None = None,
          max_gap: int = MAX_TAG_GAP) -> tuple[bool, list[str]]:
    """Чистая функция вердикта: никакой сети, только данные. Её и тестирует selftest."""
    why: list[str] = []
    ok = True

    rel_by_tag = {r.get("tag_name", ""): r for r in releases
                  if not r.get("draft") and not r.get("prerelease")}

    # ИНВАРИАНТ 1: конкретный тег обязан быть опубликован и полон.
    if expect_tag:
        rel = rel_by_tag.get(expect_tag)
        if rel is None:
            return False, [f"тег {expect_tag} НЕ опубликован как релиз "
                           f"(gh release create не выполнен или упал)"]
        have = {a.get("name", "") for a in rel.get("assets", [])}
        ver = expect_tag.lstrip("v")
        need = [r.format(ver=ver) for r in REQUIRED]
        miss = [n for n in need if n not in have]
        if miss:
            ok = False
            why.append(f"релиз {expect_tag} есть, но без ассетов: {miss} "
                       f"(ссылки releases/download/{expect_tag}/… отдают 404)")

    # ИНВАРИАНТ 2: разрыв между максимальным тегом и последним релизом.
    tags_sorted = _sorted_tags(tags)
    if not tags_sorted:
        return False, ["в репозитории нет тегов вида vX.Y.Z"]
    if not rel_by_tag:
        return False, ["ни одного опубликованного релиза при наличии тегов — "
                       "все теги мёртвые"]

    latest_rel = (_sorted_tags(list(rel_by_tag)) or [None])[0]
    if latest_rel is None:
        return False, ["ни одного релиза с корректной версией в теге"]

    gap = tags_sorted.index(latest_rel)
    if gap > max_gap:
        dead = tags_sorted[:gap]
        ok = False
        why.append(f"разрыв тег->релиз {gap} > {max_gap}: без релиза {len(dead)} "
                   f"тегов — {', '.join(dead[:8])}{'…' if len(dead) > 8 else ''}")
    return ok, why



# --- ЖИВОЙ РЕЖИМ (только по явному --online) -------------------------------
def _get(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "kern-release-assets-check"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — только https
        return json.load(r)


def fetch(api: str, repo: str, pages: int = 3) -> tuple[list[str], list[dict]]:
    tags: list[str] = []
    for p in range(1, pages + 1):
        chunk = _get(f"{api}/repos/{repo}/tags?per_page=100&page={p}")
        if not chunk:
            break
        tags += [t["name"] for t in chunk]
    releases: list[dict] = []
    for p in range(1, pages + 1):
        chunk = _get(f"{api}/repos/{repo}/releases?per_page=100&page={p}")
        if not chunk:
            break
        releases += chunk
    return tags, releases


def _verdict(tags, releases, expect=None, max_gap=MAX_TAG_GAP) -> tuple[bool, list[str]]:
    """Обёртка, чтобы canfail ломал ПОВЕДЕНИЕ, а не текст тестов."""
    return check(tags, releases, expect, max_gap)


def selftest() -> int:
    ok_rel = {"tag_name": "v1.2.3", "assets": [
        {"name": "kerna-dist-v1.2.3.tar.gz"}, {"name": "kernc-x86_64-linux-musl"},
        {"name": "SHA256SUMS"}]}
    # 1) ЗЕЛЁНОЕ: тег == релиз, все ассеты на месте.
    v, why = _verdict(["v1.2.3"], [ok_rel], expect="v1.2.3")
    if not v:
        print(f"[!] selftest: полный релиз объявлен дырой: {why}")
        return 1
    # 2) КРАСНОЕ: релиза нет вовсе — тег мёртвый.
    if _verdict(["v1.2.3"], [], expect="v1.2.3")[0]:
        print("[!] selftest: тег без релиза признан нормой")
        return 1
    # 3) КРАСНОЕ: релиз есть, но БЕЗ архива (ссылка отдаст 404).
    broken = {"tag_name": "v1.2.3", "assets": [{"name": "SHA256SUMS"}]}
    if _verdict(["v1.2.3"], [broken], expect="v1.2.3")[0]:
        print("[!] selftest: релиз без ассетов признан нормой")
        return 1
    # 4) ЗЕЛЁНОЕ: ровно один свежий тег впереди релиза (bump до нарезки).
    v, why = _verdict(["v1.2.4", "v1.2.3"], [ok_rel])
    if not v:
        print(f"[!] selftest: нормальный разрыв 1 объявлен дырой: {why}")
        return 1
    # 5) КРАСНОЕ: 21 мёртвый тег (#652 — реальная история) обязан покраснеть.
    tags = [f"v1.2.{n}" for n in range(25, 3, -1)] + ["v1.2.3"]
    if _verdict(tags, [ok_rel])[0]:
        print("[!] selftest: 21 мёртвый тег признан нормой")
        return 1
    # 6) КРАСНОЕ: draft-релиз не считается опубликованным.
    draft = {"tag_name": "v1.2.4", "draft": True, "assets": []}
    if _verdict(["v1.2.4", "v1.2.3"], [draft, ok_rel], expect="v1.2.4")[0]:
        print("[!] selftest: draft-релиз засчитан как опубликованный")
        return 1
    print("[OK] release-assets: контракт двусторонен (6/6): полный релиз зелёный; "
          "тег без релиза, релиз без ассетов, draft и 21 мёртвый тег — красные; "
          "разрыв 1 (bump) — норма")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="тег без релиза / релиз без ассетов")
    ap.add_argument("--selftest", action="store_true",
                    help="офлайн-контракт на фикстурах (по умолчанию, без сети)")
    ap.add_argument("--online", action="store_true",
                    help="живая проверка через api.github.com (ПОСЛЕ публикации)")
    ap.add_argument("--expect-tag", default=None, metavar="vX.Y.Z")
    ap.add_argument("--max-gap", type=int, default=MAX_TAG_GAP)
    ap.add_argument("--repo", default="newmathphys/kern")
    ap.add_argument("--api", default="https://api.github.com")
    a = ap.parse_args(argv)

    if a.selftest or not a.online:
        return selftest()
    if not a.expect_tag:
        print("[!] --online требует --expect-tag vX.Y.Z: без ожидаемого тега "
              "проверка не знает, что именно обязано существовать")
        return 2
    try:
        tags, releases = fetch(a.api, a.repo)
    except Exception as exc:  # noqa: BLE001 — сеть: НАЗВАННЫЙ отказ, не тишина
        print(f"[!] не удалось прочитать {a.repo} через API: {exc}")
        return 2
    ok, why = _verdict(tags, releases, a.expect_tag, a.max_gap)
    for w in why:
        print(f"[FAIL] {w}")
    if ok:
        print(f"[OK] release-assets: {a.expect_tag} опубликован со всеми ассетами; "
              f"разрыв тег->релиз в норме (<= {a.max_gap})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
