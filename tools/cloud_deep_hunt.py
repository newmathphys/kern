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

WAVES = {1: WAVE_1_SHARDS, 2: WAVE_2_SHARDS}
SHARDS = WAVE_2_SHARDS          # дефолт: свежая волна

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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ночная облачная охота")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="report.md")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.of != 6 or a.shard not in SHARDS:
        print(f"неверный шард: {a.shard} из {a.of}", file=sys.stderr)
        return 2
    repos = SHARDS[a.shard][: a.limit or None]
    print(f"shard {a.shard}/{a.of}: {len(repos)} репозиториев -> {a.out}")
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
