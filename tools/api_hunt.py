#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""api_hunt: бесклоновая разведка через открытые API -> ядро KERN.

Зачем отдельный инструмент. `cloud_deep_hunt.py` работает в GitHub Actions и
клонирует кураторские репозитории (в Actions у штатного `GITHUB_TOKEN` нет прав
на `search/code`). `api_hunt.py` — наоборот: ЛОКАЛЬНЫЙ снайпер, который
пользуется уже авторизованным `gh`, ищет по глобальному индексу кода и
скачивает ТОЛЬКО найденные файлы (5–20 КБ) прямо в память. `git clone`
запускается позже и только для финального приговора компилятора.

Два ствола:
  * `--mode laws`    — блочный анализатор законов `law_hunter` (derive-ord /
                       eq-hash), плюс пометка HOT, если у типа есть `impl Eq`;
  * `--mode effects` — поиск арифметических краёв (деление на ноль,
                       `(lo + hi) / 2`, `a * b / gcd`, `count * stride`)
                       с пометкой «нужен компилятор»;
  * `--mode all`     — оба.

Лимит Code Search — 10 запросов/мин: между запросами выдерживается пауза.

Запуск:
    python3 tools/api_hunt.py --selftest
    python3 tools/api_hunt.py --limit 15 --min-stars 500
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Наши уже опубликованные трофеи и проверенные волны — повторно не ищем.
EXCLUDED_REPOS = {
    "newmathphys/kern", "mahmoud/boltons", "kiesraad/abacus", "isamert/scheme.rs",
    "ad-si/Woxi", "boa-dev/boa", "swc-project/swc", "surrealdb/surrealdb",
    "vectordotdev/vector", "lancedb/lance", "lance-format/lance",
    "databendlabs/databend", "gleam-lang/gleam", "zellij-org/zellij",
    "bevyengine/bevy", "TheAlgorithms/C", "TheAlgorithms/Rust",
    "databendlabs", "apache/datafusion", "pola-rs/polars", "qdrant/qdrant",
}

QUERIES_LAWS = [
    '"impl Eq for" "to_bits().hash" language:Rust',
    '"derive_hash_xor_eq" language:Rust',
    '"derived_hash_with_manual_eq" language:Rust',
]

QUERIES_EFFECTS = [
    '"def lcm" "// gcd" language:Python',
    '"(low + high) / 2" language:C',
    '"count * stride" language:C',
]

EFFECT_PATTERNS = [
    ("midpoint", re.compile(r"\(\s*(?:lo|low|left|start)\s*\+\s*(?:hi|high|right|end)\s*\)\s*/\s*2"),
     "переполнение середины отрезка"),
    ("lcm", re.compile(r"lcm\s*\(|\*\s*\w+\s*/\s*gcd"),
     "НОК/НОД через произведение до деления"),
    ("stride", re.compile(r"count\s*\*\s*stride|stride\s*\*\s*count|len\s*\*\s*size"),
     "размер буфера из произведения"),
]

GH_PAUSE_S = 7.0
PER_QUERY = 6        # иначе на каждый файл уходит 2 API-вызова и залп буксует


def _gh_json(args: list, timeout: int = 40):
    import subprocess
    try:
        p = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            return None
        return json.loads(p.stdout or "null")
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None


def search_code(query: str, per_page: int = 20) -> list:
    """gh api search/code -> [(repo, path)]."""
    data = _gh_json(["api", f"search/code?q={urllib.parse.quote(query)}&per_page={per_page}"])
    if not data:
        return []
    return [(it["repository"]["full_name"], it["path"]) for it in data.get("items", [])]


def repo_meta(full_name: str):
    return _gh_json(["api", f"repos/{full_name}", "--jq",
                     "{stars: .stargazers_count, archived: .archived, fork: .fork, issues: .has_issues}"])


def raw_file(full_name: str, path: str):
    import base64
    data = _gh_json(["api", f"repos/{full_name}/contents/{path}"])
    if not data or "content" not in data:
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return None


def crates_top(limit: int = 20):
    """Топ крейтов crates.io -> список GitHub-репозиториев (owner/repo)."""
    import urllib.parse as up
    req = urllib.request.Request(
        f"https://crates.io/api/v1/crates?per_page={limit}&sort=downloads",
        headers={"User-Agent": "kern-api-hunt/1.0 (https://github.com/newmathphys/kern)"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, ValueError, OSError):
        return []
    repos = []
    for c in data.get("crates", []):
        repo = (c.get("repository") or "").rstrip("/")
        m = re.search(r"github\.com/([^/]+)/([^/#?]+)", repo)
        if m:
            repos.append(f"{m.group(1)}/{m.group(2).removesuffix('.git')}")
    return repos


def analyse_laws(src: str, path: str) -> list:
    """Ствол 1: блочный анализатор законов + пометка HOT при явном impl Eq."""
    import sys
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import law_hunter as LH

    out = []
    if path.endswith(".rs"):
        for f in LH.check_rust_eq_hash(src) + LH.check_rust_derive_ord(src):
            tname = f.get("symbol", "").split("::")[0]
            hot = bool(tname) and re.search(
                r"impl\s+Eq\s+for\s+" + re.escape(tname) + r"\b", src) is not None
            out.append({"law": f.get("law"), "symbol": f.get("symbol"),
                        "detail": f.get("detail", ""), "hot": hot})
    elif path.endswith(".py"):
        import tempfile
        import cloud_deep_hunt as CD
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / Path(path).name
            p.write_text(src, encoding="utf-8")
            for f in CD.scan_python(Path(tmp)):
                out.append({"law": f.get("law"), "symbol": f.get("symbol"),
                            "detail": f.get("detail", ""), "hot": False})
    return out


def analyse_effects(src: str, path: str) -> list:
    """Ствол 2: арифметические края (кандидаты под компилятор/решатель)."""
    if not path.endswith((".py", ".c", ".h", ".rs")):
        return []
    out = []
    for line_no, line in enumerate(src.splitlines(), 1):
        if line.lstrip().startswith(("//", "#", "*")):
            continue
        for name, pat, why in EFFECT_PATTERNS:
            if pat.search(line):
                out.append({"law": "effects:" + name,
                            "symbol": f"{Path(path).name}:{line_no}",
                            "detail": why + " — нужен компилятор/решатель", "hot": False})
                break
    return out


def hunt(limit: int, min_stars: int, mode: str, log=print) -> list:
    """Поиск -> фильтр -> скачивание файла -> анализ -> ранжирование."""
    seen, findings = set(), []
    queries = []
    if mode in ("laws", "all"):
        queries += [(q, "laws") for q in QUERIES_LAWS]
    if mode in ("effects", "all"):
        queries += [(q, "effects") for q in QUERIES_EFFECTS]

    for query, stem in queries:
        log(f"[search] {query}")
        for repo, path in search_code(query, per_page=PER_QUERY):
            if repo in EXCLUDED_REPOS or (repo, path) in seen:
                continue
            seen.add((repo, path))
            if len(findings) >= limit:
                return findings
            meta = repo_meta(repo) or {}
            if meta.get("archived") or meta.get("fork") or meta.get("issues") is False:
                continue
            if (meta.get("stars") or 0) < min_stars:
                continue
            src = raw_file(repo, path)
            if not src:
                continue
            hits = analyse_laws(src, path) if stem == "laws" else analyse_effects(src, path)
            for h in hits:
                h.update({"repo": repo, "path": path, "stars": meta.get("stars", 0)})
                findings.append(h)
        time.sleep(GH_PAUSE_S)

    findings.sort(key=lambda x: (-x.get("stars", 0), not x.get("hot")))
    return findings


def render(findings: list) -> str:
    if not findings:
        return "находок нет"
    lines = ["| ★ | Репозиторий | Файл | Закон | Символ | HOT |",
             "|---|---|---|---|---|---|"]
    for f in findings:
        lines.append(f"| {f['stars']} | `{f['repo']}` | `{Path(f['path']).name}` | "
                     f"{f['law']} | `{f['symbol']}` | {'да' if f['hot'] else ''} |")
    return "\n".join(lines)


def selftest() -> int:
    bad = 0

    def ok(cond, label):
        nonlocal bad
        print(("[OK]   " if cond else "[FAIL] ") + label)
        if not cond:
            bad += 1

    ok("isamert/scheme.rs" in EXCLUDED_REPOS, "трофеи исключены из повторного поиска")
    ok(len(QUERIES_LAWS) >= 3 and len(QUERIES_EFFECTS) >= 3, "у обоих стволов есть запросы")

    rust = ('#[derive(Clone, Copy, PartialEq)]\npub struct Money { pub cents: f64 }\n'
            'impl Eq for Money {}\n'
            'impl std::hash::Hash for Money {\n'
            '    fn hash<H: std::hash::Hasher>(&self, s: &mut H) { self.cents.to_bits().hash(s); }\n}\n')
    hits = analyse_laws(rust, "money.rs")
    ok(len(hits) == 1 and hits[0]["law"] == "eq-hash-mismatch", "ствол законов ловит to_bits-хеш")
    ok(bool(hits) and hits[0]["hot"], "явный impl Eq помечает находку HOT")

    py = ("class Tag:\n    def __eq__(self, o):\n        return self.v.casefold() == o.v.casefold()\n"
          "    def __hash__(self):\n        return hash(self.v)\n")
    ok(len(analyse_laws(py, "tag.py")) == 1, "ствол законов ловит Python __eq__/__hash__")

    c = "int n = (low + high) / 2;\nint bytes = count * stride;\n"
    kinds = {e["law"] for e in analyse_effects(c, "parser.c")}
    ok("effects:midpoint" in kinds, "ствол эффектов видит переполнение середины")
    ok("effects:stride" in kinds, "ствол эффектов видит count*stride")
    ok(analyse_effects("// (low + high) / 2\n", "x.c") == [], "комментарии не находка")
    ok(analyse_effects("int x = 1;\n", "x.c") == [], "чистый код молчит")

    ok(render([]) == "находок нет", "пустой отчёт рендерится")
    row = render([{"stars": 5, "repo": "a/b", "path": "x.rs", "law": "L", "symbol": "S", "hot": True}])
    ok("| 5 |" in row and "| да |" in row, "строка таблицы собирается")
    ok(GH_PAUSE_S >= 5, "пауза под лимит Code Search задана")

    print(f"[API-HUNT-SELFTEST] провалов: {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="бесклоновая разведка через открытые API")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--min-stars", type=int, default=100)
    ap.add_argument("--mode", choices=["laws", "effects", "all"], default="all")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    findings = hunt(a.limit, a.min_stars, a.mode)
    print(render(findings) if not a.json
          else json.dumps(findings, ensure_ascii=False, indent=1))
    print(f"\nитого: {len(findings)} находок (mode={a.mode}, min-stars={a.min_stars})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


