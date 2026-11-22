#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""cloud_deep_hunt: ночная охота за трофеями НА РАННЕРАХ GitHub Actions.

Почему без `search/code`: у `secrets.GITHUB_TOKEN` в Actions нет прав на
глобальный поиск кода (403). Поэтому цель выбирается не поиском, а кураторским
списком живых проектов, публично клонируется (`git clone --depth 1
--filter=blob:none`, токен не нужен) и сканируется ЛОКАЛЬНО на диске раннера
законами `tools/law_hunter.py --rust`. Один шард = один список репозиториев.

ПРАВИЛА (после уроков abacus#3179 и swc#12815):
  * НИЧЕГО не публикуется в чужие репозитории — только отчёт в артефакт;
  * находки — КАНДИДАТЫ, вердикт даёт живой `cargo test` / `python3`;
  * клон удаляется сразу после скана (диск раннера не забивается).

Запуск:
    python3 tools/cloud_deep_hunt.py --selftest
    python3 tools/cloud_deep_hunt.py --shard 0 --of 6 --dry-run
    python3 tools/cloud_deep_hunt.py --shard 0 --of 6 --out report-0.md
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ВОЛНА 1 (историческая): по ней найдены surrealdb#7715, vector#27277,
# lance#11344 и databend#21155. Повторять её бессмысленно.
WAVE_1_SHARDS = {
    0: ["databendlabs/databend", "apache/datafusion", "apache/arrow-rs",
        "pola-rs/polars", "glaredb/glaredb", "lancedb/lance"],
    1: ["surrealdb/surrealdb", "meilisearch/meilisearch", "quickwit-oss/quickwit",
        "GreptimeTeam/greptimedb", "tikv/tikv", "ClickHouse/clickhouse-rs"],
    2: ["astral-sh/ruff", "astral-sh/uv", "biomejs/biome",
        "oxc-project/oxc", "rolldown/rolldown", "denoland/deno"],
    3: ["nushell/nushell", "vectordotdev/vector", "toml-rs/toml",
        "serde-rs/json", "winnow-rs/winnow", "pest-parser/pest"],
    4: ["pydantic/pydantic-core", "huggingface/candle", "sonos/tract",
        "tracel-ai/burn", "rust-num/num-rational", "paupino/rust-decimal"],
    5: ["pydantic/pydantic", "BerriAI/litellm", "encode/httpx",
        "Textualize/rich", "tiangolo/fastapi", "psf/requests"],
}

# ВОЛНА 2: свежие 36 проектов (0 пересечений с волной 1) — UI/GPU-кэши,
# WASM-рантаймы, редакторы, сетевые стеки и гео: там высока плотность f32/f64
# в ключах кэша и метриках.
WAVE_2_SHARDS = {
    0: ["paradigmxyz/reth", "risingwavelabs/risingwave", "cnosdb/cnosdb",
        "apache/opendal", "valkey-io/valkey", "dragonflydb/dragonfly"],
    1: ["emilk/egui", "iced-rs/iced", "slint-ui/slint",
        "linebender/xilem", "lapce/floem", "bevyengine/bevy"],
    2: ["bytecodealliance/wasmtime", "wasmerio/wasmer", "gleam-lang/gleam",
        "rust-lang/rust-analyzer", "ruffle-rs/ruffle", "tokio-rs/tokio"],
    3: ["helix-editor/helix", "zellij-org/zellij", "alacritty/alacritty",
        "wezterm/wezterm", "sxyazi/yazi", "BurntSushi/ripgrep"],
    4: ["georust/geo", "rerun-io/rerun", "pykeio/ort",
        "qdrant/qdrant", "huggingface/safetensors", "rustdesk/rustdesk"],
    5: ["Textualize/textual", "encode/starlette", "Delgan/loguru",
        "pydantic/pydantic-settings", "pallets/flask", "psf/black"],
}

# ВОЛНА 3: 36 проектов, ноль пересечений с волнами 1 и 2 и с нашими
# репортами. Половина — Rust/C с геометрией и бинарным поиском (ствол
# z3-arith: реальные BitVec-контрпримеры), половина — Python с кэшами
# (ствол lru-effects: @lru_cache поверх часов и рандома).
WAVE_3_SHARDS = {
    0: ["zed-industries/zed", "gfx-rs/wgpu", "dimforge/rapier",
        "nical/lyon", "image-rs/image", "raphamorim/rio"],
    1: ["servo/servo", "apache/iceberg-rust", "delta-io/delta-rs",
        "foundry-rs/foundry", "tauri-apps/tauri", "wasm-bindgen/wasm-bindgen"],
    2: ["starship/starship", "Wilfred/difftastic", "dandavison/delta",
        "sharkdp/bat", "sharkdp/fd", "eza-community/eza"],
    3: ["hyperium/hyper", "actix/actix-web", "diesel-rs/diesel",
        "rusqlite/rusqlite", "lapce/lapce", "rust-lang/cargo"],
    4: ["numpy/numpy", "scipy/scipy", "scikit-learn/scikit-learn",
        "pandas-dev/pandas", "sympy/sympy", "pallets/click"],
    5: ["django/django", "sqlalchemy/sqlalchemy", "pallets/jinja",
        "celery/celery", "tqdm/tqdm", "python-poetry/poetry"],
}

# ВОЛНА 4 (ночь): 36 крупных долгоживущих проектов, ноль пересечений с
# волнами 1-3 и с нашими репортами. Типст и верстальные координаты,
# серверный @lru_cache и C-системы — под все три откалиброванных ствола.
WAVE_4_SHARDS = {
    0: ["duckdb/duckdb-rs", "gluesql/gluesql", "tursodatabase/limbo",
        "MaterializeInc/materialize", "ArroyoSystems/arroyo", "cberner/redb"],
    1: ["FyroxEngine/Fyrox", "not-fl3/macroquad", "ggez/ggez",
        "plotters-rs/plotters", "dimforge/parry", "dimforge/nalgebra"],
    2: ["typst/typst", "hyperium/h2", "tokio-rs/axum",
        "tokio-rs/bytes", "poem-web/poem", "PyO3/pyo3"],
    3: ["PrefectHQ/prefect", "apache/airflow", "dagster-io/dagster",
        "streamlit/streamlit", "gradio-app/gradio", "aio-libs/aiohttp"],
    4: ["Lightning-AI/pytorch-lightning", "huggingface/transformers", "optuna/optuna",
        "ray-project/ray", "encode/uvicorn", "marshmallow-code/marshmallow"],
    5: ["redis/redis", "curl/curl", "DaveGamble/cJSON",
        "jemalloc/jemalloc", "lz4/lz4", "facebook/zstd"],
}

WAVES = {1: WAVE_1_SHARDS, 2: WAVE_2_SHARDS, 3: WAVE_3_SHARDS, 4: WAVE_4_SHARDS}
SHARDS = WAVE_4_SHARDS          # дефолт: свежая волна

ROOT = Path(__file__).resolve().parent.parent
CLONE_TIMEOUT = 900
SCAN_TIMEOUT = 600
MAX_CLONE_MB = 2048


def _run(cmd, cwd=None, timeout=600, env=None):
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                           capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except FileNotFoundError as exc:
        return 127, str(exc)


def scan_rust(clone: Path) -> list:
    """Прогон закона law_hunter --rust по клону (JSON)."""
    rc, out = _run([sys.executable, str(ROOT / "tools" / "law_hunter.py"),
                    "--rust", str(clone), "--json"], timeout=SCAN_TIMEOUT)
    if rc != 0 or "{" not in out:
        return [{"law": "scan-error", "detail": out[-300:]}]
    try:
        return json.loads(out[out.index("{"):]).get("findings", [])
    except ValueError:
        return [{"law": "scan-error", "detail": out[-300:]}]


def scan_python(clone: Path) -> list:
    """LAW py-eq-hash: `__eq__` и `__hash__` в ОДНОМ классе, где __eq__
    нормализует значение (casefold/lower), а __hash__ хеширует сырое поле.

    Урок ночи: файловый греп давал FP на pydantic / httpx / rich, потому что
    `__eq__`, `__hash__` и `.lower()` лежали в РАЗНЫХ классах одного файла.
    """
    import ast as _ast

    out = []
    for p in clone.rglob("*.py"):
        if "test" in p.parts or ".venv" in p.parts:
            continue
        try:
            tree = _ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError, ValueError):
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.ClassDef):
                continue
            methods = {n.name: n for n in node.body
                       if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}
            if "__eq__" not in methods or "__hash__" not in methods:
                continue
            eq_dump = _ast.dump(methods["__eq__"])
            hash_dump = _ast.dump(methods["__hash__"])
            eq_normalises = ("casefold" in eq_dump) or ("lower" in eq_dump)
            hash_raw = ("casefold" not in hash_dump) and ("lower" not in hash_dump)
            if not (eq_normalises and hash_raw):
                continue
            out.append({
                "law": "py-eq-hash", "symbol": f"{p.name}:{node.name}",
                "file": f"{p}:{node.lineno}",
                "detail": "__eq__ нормализует регистр, а __hash__ в том же классе "
                          "хеширует сырое поле — нужен живой прогон "
                          "`a == b and b not in {a}`",
            })
    return out


def databend_probe(clone: Path, log) -> list:
    """Шард 0: живой `cargo test` на databend (Трофей №13).

    Локально этот тест недостижим: репозиторий требует `clang` в
    `.cargo/config.toml`, а в облачном воркфлоу `clang` ставится через apt.
    Возвращает findings-подобные записи с живым выводом теста.
    """
    rel = Path("src/query/datavalues/src/data_value.rs")
    target = clone / rel
    if not target.is_file():
        return [{"law": "databend-probe", "detail": f"{rel} отсутствует"}]
    src = target.read_text(encoding="utf-8", errors="replace")
    if "kern_eq_hash_minus_zero" not in src:
        src += (
            "\n#[cfg(test)]\nmod kern_eq_hash_test {\n"
            "    use super::*;\n    use std::collections::HashSet;\n\n"
            "    #[test]\n    fn kern_eq_hash_minus_zero() {\n"
            "        let a = DataValue::Float64(0.0);\n"
            "        let b = DataValue::Float64(-0.0);\n"
            "        assert_eq!(a, b, \"derived PartialEq compares numerically\");\n"
            "        let mut set = HashSet::new();\n        set.insert(a);\n"
            "        assert!(set.contains(&b), \"Eq/Hash contract broken on -0.0\");\n"
            "    }\n}\n"
        )
        target.write_text(src, encoding="utf-8")
    log("[databend] rustup show active-toolchain")
    _run(["rustup", "show", "active-toolchain"], cwd=clone, timeout=600)
    log("[databend] cargo test -p databend-common-datavalues --lib kern_eq_hash_minus_zero")
    # 7 ГБ RAM на раннере GitHub: 2 потока и без debuginfo (линковка clang
    # иначе съедает память).
    env = dict(os.environ, CARGO_BUILD_JOBS="2",
               CARGO_PROFILE_TEST_DEBUG="0", CARGO_PROFILE_DEV_DEBUG="0")
    rc, out = _run(["cargo", "test", "-p", "databend-common-datavalues", "--lib",
                    "kern_eq_hash_minus_zero"], cwd=clone, timeout=3600, env=env)
    keep = [ln for ln in out.splitlines()
            if ("panicked" in ln or "test result" in ln
                or "contract broken" in ln or "error[" in ln)]
    tail = "\n".join(keep[:8] + out.strip().splitlines()[-6:])
    verdict = "FAILED" if "test result: FAILED" in out else (
        "PASSED" if "test result: ok" in out else "UNKNOWN")
    return [{
        "law": "databend-probe", "symbol": "DataValue::Float64",
        "detail": f"cargo test rc={rc}, verdict={verdict}\n\n{tail}",
    }]


def policy_excerpt(clone: Path) -> str:
    """Первые строки AGENTS.md / AI_POLICY.md / CONTRIBUTING.md."""
    for name in ("AGENTS.md", "AI_POLICY.md", "CONTRIBUTING.md"):
        p = clone / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            head = [ln.strip() for ln in text.splitlines() if ln.strip()][:4]
            return f"{name}: " + " / ".join(head)[:280]
    return "policy: (нет AGENTS.md / AI_POLICY.md / CONTRIBUTING.md)"


def scan_arms(clone: Path) -> list:
    """Стволы `z3-arith` и `lru-effects` по файлам клона.

    Логика живёт в `tools/api_hunt.py` (там же её самотесты), здесь только
    обход дерева, чтобы облако и локальный залп считали одинаково.
    """
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import api_hunt as arms

    out, budget = [], 6000
    for pat in ("*.py", "*.c", "*.h", "*.rs"):
        for p in clone.rglob(pat):
            if {".git", "vendor", "third_party", "node_modules", "target"} & set(p.parts):
                continue
            budget -= 1
            if budget <= 0:
                return out
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(p.relative_to(clone))
            for h in arms.analyse_lru(src, rel) + arms.analyse_z3_arith(src, rel):
                h["file"] = f"{p.relative_to(clone)}"
                out.append(h)
    return out


def hunt_repo(repo: str, workdir: Path, log) -> dict:
    dest = workdir / repo.replace("/", "__")
    entry = {"repo": repo, "status": "unknown", "findings": [], "policy": ""}
    log(f"[clone] {repo}")
    rc, out = _run(["git", "clone", "--depth", "1", "--filter=blob:none",
                    f"https://github.com/{repo}.git", str(dest)], timeout=CLONE_TIMEOUT)
    if rc != 0:
        entry["status"] = "clone-failed"
        entry["findings"] = [{"law": "clone-error", "detail": out[-200:]}]
        log(f"[clone] {repo}: FAILED rc={rc}")
        return entry
    try:
        entry["policy"] = policy_excerpt(dest)
        is_rust = (dest / "Cargo.toml").is_file()
        entry["status"] = "scanned"
        if (repo == "databendlabs/databend"
                and os.environ.get("KERN_DATABEND_PROBE") == "1"):
            entry["findings"] = databend_probe(dest, log)
        else:
            entry["findings"] = scan_rust(dest) if is_rust else scan_python(dest)
            entry["findings"] = entry["findings"] + scan_arms(dest)
        log(f"[scan] {repo}: {len(entry['findings'])} findings")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
    return entry


def write_report(results: list, out_path: Path, shard: int, of: int) -> None:
    total = sum(len(r["findings"]) for r in results)
    lines = [f"# Cloud deep hunt — shard {shard}/{of}", "",
             f"Репозиториев: {len(results)} · находок: {total}", "",
             "| Repo | Статус | Находок | Policy |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| `{r['repo']}` | {r['status']} | {len(r['findings'])} | "
                     f"{r.get('policy', '')[:90]} |")
    lines.append("")
    for r in results:
        if r["findings"]:
            lines.append(f"## {r['repo']} ({r['status']})")
            for f in r["findings"]:
                lines.append(f"- **{f.get('law')}** `{f.get('symbol')}` — "
                             f"{f.get('detail', '')}")
                if f.get("file"):
                    lines.append(f"  - file: `{f['file']}`")
            lines.append("")
    lines.append("Все находки — КАНДИДАТЫ. Вердикт даёт только живой "
                 "`cargo test` / `python3`.")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def selftest() -> int:
    bad = 0

    def ok(cond, label):
        nonlocal bad
        print(("[OK]   " if cond else "[FAIL] ") + label)
        if not cond:
            bad += 1

    flat = [r for v in SHARDS.values() for r in v]
    ok(len(SHARDS) == 6, "шесть шардов описаны")
    ok(all(len(v) >= 5 for v in SHARDS.values()), "в каждом шарде >= 5 репозиториев")
    ok(len(flat) == len(set(flat)), "репозитории не дублируются между шардами")
    w1 = {r for v in WAVE_1_SHARDS.values() for r in v}
    w2 = {r for v in WAVE_2_SHARDS.values() for r in v}
    ok(not (w1 & w2), f"волны не пересекаются (общих: {len(w1 & w2)})")
    ok(len(w2) == 36, f"в волне 2 ровно 36 целей (сейчас {len(w2)})")
    ok(all(len(v) == 6 for v in WAVE_2_SHARDS.values()), "в шарде волны 2 ровно 6 целей")
    w3 = {r for v in WAVE_3_SHARDS.values() for r in v}
    ok(len(w3) == 36, f"в волне 3 ровно 36 целей (сейчас {len(w3)})")
    ok(all(len(v) == 6 for v in WAVE_3_SHARDS.values()), "в шарде волны 3 ровно 6 целей")
    ok(not (w1 & w3) and not (w2 & w3),
       f"волна 3 чиста от волн 1-2 (общих: {len((w1 | w2) & w3)})")
    reported = {"dimforge/kiss3d", "bevyengine/bevy", "zellij-org/zellij",
                "gleam-lang/gleam", "surrealdb/surrealdb", "vectordotdev/vector",
                "lancedb/lance", "databendlabs/databend", "qdrant/qdrant",
                "swc-project/swc", "boa-dev/boa"}
    ok(not (w3 & reported), f"волна 3 не повторяет трофеи (общих: {len(w3 & reported)})")
    w4 = {r for v in WAVE_4_SHARDS.values() for r in v}
    ok(len(w4) == 36, f"в волне 4 ровно 36 целей (сейчас {len(w4)})")
    ok(all(len(v) == 6 for v in WAVE_4_SHARDS.values()), "в шарде волны 4 ровно 6 целей")
    ok(not (w4 & (w1 | w2 | w3)),
       f"волна 4 чиста от волн 1-3 (общих: {len(w4 & (w1 | w2 | w3))})")
    ok(not (w4 & reported), f"волна 4 не повторяет трофеи (общих: {len(w4 & reported)})")
    ok(len(TROPHY_REPOS) >= 14, f"трофеи перечислены ({len(TROPHY_REPOS)})")
    ok(WAVE_5_TARGET_COUNT == 144 and WAVE_5_SHARD_COUNT == 8,
       "волна 5: 8 шардов x 18 целей = 144")
    live = {"full_name": "acme/live", "archived": False, "fork": False,
            "has_issues": True, "pushed_at": "2026-11-01T00:00:00Z"}
    ok(accept_repo(dict(live), set(), []), "авто-подбор берёт живую цель")
    ok(not accept_repo({**live, "archived": True}, set(), []), "архив отсекается")
    ok(not accept_repo({**live, "fork": True}, set(), []), "форк отсекается")
    ok(not accept_repo({**live, "has_issues": False}, set(), []), "без issues отсекается")
    ok(not accept_repo({**live, "pushed_at": "2021-05-01T00:00:00Z"}, set(), []),
       "мёртвый pushed_at отсекается")
    ok(not accept_repo({**live, "size": 900000}, set(), []), "слишком большой репозиторий отсекается")
    ok(not accept_repo(dict(live), {"acme/live"}, []), "уже проверенная цель не берётся")
    ok(not accept_repo(dict(live), set(), ["acme/live"]), "дубль внутри волны не берётся")
    ok(all(r.count("/") == 1 for r in flat), "все цели в формате owner/repo")
    needle = "/" + "tmp" + "/"
    ok(needle not in Path(__file__).read_text(encoding="utf-8"),
       "в коде нет литералов пути: он задаётся флагом --out")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "a.py").write_text(
            "class X:\n    def __eq__(self, o):\n"
            "        return self.v.casefold() == o.v.casefold()\n"
            "    def __hash__(self):\n        return hash(self.v)\n", encoding="utf-8")
        ok(len(scan_python(t)) == 1, "эвристика Python ловит пару __eq__/__hash__")
        out = t / "r.md"
        write_report([{"repo": "a/b", "status": "scanned", "findings": [], "policy": "p"}],
                     out, 0, 6)
        ok(out.is_file() and "shard 0/6" in out.read_text(encoding="utf-8"),
           "отчёт пишется и содержит номер шарда")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "AGENTS.md").write_text("# Rules" + chr(10) + "Read this first." + chr(10),
                                    encoding="utf-8")
        ok(isinstance(policy_excerpt(t), str) and "AGENTS.md" in policy_excerpt(t),
           "policy_excerpt читает AGENTS.md (иначе NameError роняет все шарды)")
        ok("отсутствует" in databend_probe(t, lambda *_: None)[0]["detail"],
           "databend_probe без файла возвращает запись, а не падает")

    print(f"[CLOUD-DEEP-HUNT-SELFTEST] провалов: {bad}")
    return 0 if bad == 0 else 1


# Наши трофеи: их повторно не охотим, они уже отработаны вручную.
TROPHY_REPOS = {
    "dimforge/kiss3d", "dagster-io/dagster", "typst/typst", "bevyengine/bevy",
    "zellij-org/zellij", "gleam-lang/gleam", "surrealdb/surrealdb",
    "vectordotdev/vector", "lancedb/lance", "databendlabs/databend",
    "qdrant/qdrant", "swc-project/swc", "boa-dev/boa", "isamert/scheme.rs",
}

MAX_REPO_SIZE_KB = 250_000        # 250 МБ: клон обязан влезть на диск раннера
WAVE_5_SHARD_COUNT = 8
WAVE_5_TARGET_COUNT = 144
WAVE_5_POOL = 300              # пул подбора: окно скользит по нему


def _known_repos() -> set:
    known = set(TROPHY_REPOS)
    for wave in WAVES.values():
        known |= {r for shard in wave.values() for r in shard}
    return known


def accept_repo(item: dict, known: set, picked: list) -> bool:
    """Живая цель: не форк, не архив, есть issues, пушили недавно, не повтор."""
    full = item.get("full_name") or ""
    if not full or "/" not in full or full in known or full in picked:
        return False
    if item.get("archived") or item.get("fork"):
        return False
    if item.get("has_issues") is False:
        return False
    if item.get("size", 0) > MAX_REPO_SIZE_KB:
        return False                                   # диск раннера: 14 ГБ
    return (item.get("pushed_at") or "")[:4] >= "2025"


def discover_targets(limit: int = WAVE_5_TARGET_COUNT, log=print) -> list:
    """Авто-подбор целей из публичного реестра GitHub (нужен GITHUB_TOKEN).

    Любая ошибка сети возвращает то, что успели собрать: ночь не должна
    срываться из-за одного таймаута.
    """
    import json
    import os
    import urllib.parse
    import urllib.request

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        log("[discover] нет GITHUB_TOKEN — авто-подбор пропущен")
        return []
    known, picked = _known_repos(), []
    queries = ("language:Rust stars:>800", "language:Python stars:>1500",
               "language:C stars:>1200")
    for query in queries:
        url = ("https://api.github.com/search/repositories?q="
               + urllib.parse.quote(f"{query} archived:false fork:false")
               + "&sort=stars&order=desc&per_page=100")
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "kern-deep-hunt"})
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                items = json.load(resp).get("items", [])
        except Exception as exc:                       # noqa: BLE001
            log(f"[discover] {query}: {exc}")
            continue
        for item in items:
            if accept_repo(item, known, picked):
                picked.append(item["full_name"])
                if len(picked) >= limit:
                    return picked
        log(f"[discover] {query}: всего отобрано {len(picked)}")
    return picked


def build_wave5(shards: int = WAVE_5_SHARD_COUNT, log=print) -> dict:
    """Раскладывает авто-подбор по шардам; при нехватке откатывается на волну 4.

    Окно в 144 цели сдвигается на длину окна каждый день, поэтому соседние
    ночи не сканируют один и тот же верх реестра.
    """
    import datetime

    flat = discover_targets(WAVE_5_POOL, log)
    if len(flat) < shards * 2:
        log(f"[wave5] авто-подбор дал {len(flat)} целей — беру WAVE_4_SHARDS")
        return {i: list(v) for i, v in WAVE_4_SHARDS.items()}
    window = min(WAVE_5_TARGET_COUNT, len(flat))
    shift = (datetime.date.today().toordinal() * window) % len(flat)
    rotated = flat[shift:] + flat[:shift]
    picked = rotated[:window]
    per = len(picked) // shards
    out = {i: picked[i * per:(i + 1) * per] for i in range(shards)}
    log(f"[wave5] пул {len(flat)}, окно {len(picked)} со сдвигом {shift} на {shards} шардов")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ночная облачная охота")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=0)
    ap.add_argument("--wave", type=int, default=5,
                    help="1-4 — кураторские списки, 5 — авто-подбор с GitHub")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="report.md")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.wave == 5:
        shards, of = build_wave5(WAVE_5_SHARD_COUNT, print), (a.of or 8)
    elif a.wave in WAVES:
        shards, of = WAVES[a.wave], (a.of or 6)
    else:
        print(f"неизвестная волна: {a.wave}", file=sys.stderr)
        return 2
    if a.shard not in shards:
        print(f"неверный шард: {a.shard} из {of}", file=sys.stderr)
        return 2
    repos = shards[a.shard][: a.limit or None]
    print(f"shard {a.shard}/{of}: {len(repos)} репозиториев -> {a.out}")
    for r in repos:
        print(f"  - {r}")
    if a.dry_run:
        print("[dry-run] клонирование не выполняется")
        return 0
    workdir = Path(tempfile.mkdtemp(prefix="deep-hunt-"))
    results = []
    try:
        for repo in repos:
            results.append(hunt_repo(repo, workdir, print))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    write_report(results, Path(a.out), a.shard, a.of)
    print(f"ИТОГ: репозиториев {len(results)}, "
          f"находок {sum(len(r['findings']) for r in results)} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
