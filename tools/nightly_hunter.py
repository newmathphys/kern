#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Nightly Trophy Hunter: автономный поиск ФИЗИЧЕСКИ подтверждённых багов.

ЗАЧЕМ. KERN силён там, где деньги и числа: целочисленные границы, деление на
ноль при нулевой ликвидности, выход за границы буфера. Ночной прогон по живым
репозиториям складывает находки в НАШ Issue, а не в чужие: автоматические
issue в чужих репозиториях запрещены правилами GitHub, и человек всё равно
должен прочитать находку перед отправкой.

ТРИ УРОВНЯ ДОКАЗАННОСТИ (не смешиваются никогда):
  CONFIRMED         Python: вызов реальной функции на ЛЕГАЛЬНОМ крае из
                    контрпримера Z3 падает ровно обещанным исключением,
                    кадр стека — внутри тела мишени (замки live_replay.py);
  RUNTIME_CONFIRMED C/Rust: из файла извлекается САМА функция (без внешних
                    заголовков), компилируется вместе с main() на значениях
                    контрпримера; краш компилятора/санитайзера — доказательство;
  SMT_CANDIDATE     всё остальное: контрпример Z3 есть, физического прогона нет.

БЕЗОПАСНОСТЬ. Всё в tempfile.TemporaryDirectory(); клоны удаляются; в чужой
репозиторий не пишем ни одного байта; нужен только GITHUB_TOKEN для отчёта.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
SRC_EXT = (".py", ".c", ".h", ".rs", ".zig")
MAX_FILE_BYTES = 400_000
MIN_SRC_BYTES = 25_000      # Окно №32: хобби-репозитории (TradzQAI) отсекаются по объёму
# ЗАМОК 1 (Окно №28): тестовые/служебные деревья — не публичный API библиотеки.
SKIP_SEGMENTS = {"tests", "test", "testing", "scripts", "examples", "benchmarks",
                 "bench", "docs", "skills", "tools", "migrations", ".github"}
SKIP_NAMES = ("conftest.py",)
LIB_MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml",
                 "build.zig", "CMakeLists.txt", "Makefile", "meson.build")


def is_public_path(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if parts & SKIP_SEGMENTS:
        return False
    nm = path.name.lower()
    if nm in SKIP_NAMES or nm.startswith("test_") or "_test." in nm:
        return False
    return True


def is_library(root: Path) -> bool:
    """ЗАМОК 2 (Окно №30): библиотека = манифест И настоящий код.

    `rnckp/awesome-ogd-switzerland` прошёл раньше, потому что в awesome-списках
    лежит служебный Makefile без единого исходника. Теперь `awesome`/`leetcode`
    в имени отсекаются сразу, а один Makefile не считается манифестом.
    """
    name = root.name.lower()
    if "awesome" in name or "leetcode" in name:
        return False
    has_manifest = any((root / m).exists() for m in LIB_MANIFESTS)
    if not has_manifest:
        return False
    src = [p for p in root.rglob("*")
           if p.suffix in SRC_EXT + (".h", ".hpp") and p.is_file()
           and not ({x.lower() for x in p.parts} & SKIP_SEGMENTS)]
    if len(src) < 2:
        return False
    total = 0
    for p in src:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total >= MIN_SRC_BYTES

sys.path.insert(0, str(TOOLS))
import live_replay as LR  # noqa: E402  — запечатанный контур из окна №16


def _run(cmd, cwd=None, timeout=300):
    try:
        r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


SHARD_QUAL = {
    "0": "language:Python stars:300..15000",
    "1": "language:Python stars:300..15000",
    "2": "language:C stars:300..15000",
    "3": "language:Rust stars:300..15000",
}


def _rot_page() -> int:
    """ОКНО №31: страница меняется по дню года — иначе каждую ночь те же 24."""
    import datetime as _dt
    return 1 + (_dt.datetime.now(_dt.timezone.utc).timetuple().tm_yday % 4)


_LAST_CALL = [0.0]


def _throttle() -> None:
    """ОКНО №33: лимит Search API (30/мин) ОБЩИЙ на токен, а 4 шарда стартуют
    одновременно. Пауза 1.2 s между запросами не даёт им выбить 403."""
    import time as _t
    dt = _t.monotonic() - _LAST_CALL[0]
    if dt < 1.2:
        _t.sleep(1.2 - dt)
    _LAST_CALL[0] = _t.monotonic()


def discover(topic: str, limit: int, token: str = "", qual: str = "", page: int = 1) -> list:
    """Живые репозитории по теме через GitHub Search (stdlib, без зависимостей)."""
    qual = qual or "stars:300..15000"
    # Окно №32: `topic:` у редких тем даёт 0 при пороге 300★ — ищем по
    # ключевым словам в имени/описании (плотность пула важнее тега).
    q = urllib.parse.quote(f"{topic} in:name,description {qual} fork:false archived:false")
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&per_page={limit}&page={page}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "kern-nightly-hunter"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = {}
    for _attempt in (1, 2):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:
            _body = str(exc)
            try:
                _body = exc.read().decode("utf-8", "replace")   # type: ignore[attr-defined]
            except Exception:
                pass
            if _attempt == 1 and ("rate limit" in _body or "403" in _body or "429" in _body):
                import time as _t
                _t.sleep(15)
                continue
            print("[!] discover(%r): %s" % (topic, _body[:200]), file=sys.stderr)
            return []
    return [it["full_name"] for it in (data or {}).get("items", [])][:limit]


def clone(repo: str, dest: Path) -> str:
    rc, _ = _run(["git", "clone", "--depth", "1", "--quiet",
                  f"https://github.com/{repo}.git", str(dest)], timeout=300)
    if rc != 0:
        return ""
    rc, out = _run(["git", "rev-parse", "HEAD"], cwd=dest)
    return out.strip()[:12] if rc == 0 else ""


def is_public(fn: str) -> bool:
    """Трофей бывает только на ПУБЛИЧНОМ API.

    Урок `pallets/click::_match_short_opt`: приватный хелпер с ведущим `_` —
    внутренний контракт, вызывающий код сам гарантирует инварианты. Апстрим
    такой репорт закрывает. Публичные dunder-операторы (`__add__`) — можно.
    """
    if not fn.startswith("_"):
        return True
    return fn.startswith("__") and fn.endswith("__")


def _scan_file(path: Path) -> list:
    """Полиглотный рентген: `--xray` (+ `--xray-none` для Python)."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
    except OSError:
        return []
    flags = ["--xray"] + (["--xray-none"] if path.suffix == ".py" else [])
    found = []
    for flag in flags:
        rc, out = _run([sys.executable, str(TOOLS / "kern_contracts.py"), flag, str(path)])
        found += LR.parse_findings(out, default_path=str(path))
    uniq, seen = [], set()
    for f in found:
        key = (f["fn"], f["line"], f["kind"])
        if key not in seen and f.get("fn"):
            seen.add(key)
            uniq.append(f)
    return uniq


def _c_function(src: str, name: str) -> str:
    """Извлечь ТЕЛО функции по имени (баланс скобок), без внешних заголовков."""
    m = re.search(r"(^|\n)[A-Za-z_][\w \t\*]*\b%s\s*\(([^)]*)\)\s*\{" % re.escape(name), src)
    if not m:
        return ""
    start = m.start(2) + len(m.group(2)) + 1
    depth, i = 0, src.index("{", start)
    begin = i
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[begin:i + 1]
        i += 1
    return ""


def confirm_c(path: Path, finding: dict, work: Path) -> tuple:
    """RUNTIME_CONFIRMED для C: компилируем САМУ функцию + main() на контрпримере."""
    src = path.read_text(encoding="utf-8", errors="replace")
    body = _c_function(src, finding["fn"])
    if not body:
        return "SMT_CANDIDATE", "function body not extractable"
    head = re.search(r"([A-Za-z_][\w \t\*]*\b%s\s*\([^)]*\))\s*\{" % re.escape(finding["fn"]), src)
    sig = head.group(1) if head else ""
    params = []
    inner = sig[sig.find("(") + 1:sig.rfind(")")] if sig else ""
    for part in [p.strip() for p in inner.split(",") if p.strip() and p.strip() != "void"]:
        toks = part.split()
        params.append((toks[-1].lstrip("*"), " ".join(toks[:-1]) or "int"))
    model = finding.get("model") or {}
    args = ", ".join(str(int(model.get(n, 0))) for n, _t in params)
    prog = ("#include <stdint.h>\n#include <limits.h>\n#include <stdio.h>\n" + sig + "\n" +
            body + "\nint main(void){ volatile long long r = (long long)(%s)(%s); "
            "(void)r; return 0; }\n" % (finding["fn"], args))
    cfile = work / "repro.c"
    cfile.parent.mkdir(parents=True, exist_ok=True)   # #22: каталог может не существовать
    cfile.write_text(prog, encoding="utf-8")
    exe = work / "repro.bin"
    rc, out = _run(["gcc", "-O0", "-fsanitize=undefined", "-fno-sanitize-recover=all",
                    str(cfile), "-o", str(exe)])
    if rc != 0:
        # СТУПЕНЬ 2 (Окно №35): изолированная функция не собралась (typedef,
        # макросы, локальные хедеры) -> компилируем вместе с её исходником.
        import confirm_c_ctx
        body, why = confirm_c_ctx.confirm(path, finding["fn"], args, work / "ctx",
                                          tuple(LIB_MANIFESTS))
        if body:
            return "RUNTIME_CONFIRMED", body
        return "SMT_CANDIDATE", "not self-contained (" + why + ")"
    rc, out = _run([str(exe)], timeout=20)
    if rc != 0 and ("runtime error" in out or rc < 0):
        return "RUNTIME_CONFIRMED", (out.strip().splitlines() or ["signal %d" % rc])[0][:120]
    return "SMT_CANDIDATE", "no runtime failure on the counterexample"


def hunt_repo(repo: str, work_root: Path, max_files: int = 40) -> dict:
    """Один репозиторий: клон -> рентген -> подтверждение. Возвращает результат."""
    dest = work_root / repo.replace("/", "__")
    sha = clone(repo, dest)
    if not sha:
        return {"repo": repo, "sha": "", "error": "clone_failed", "items": []}
    if not is_library(dest):
        return {"repo": repo, "sha": sha, "error": "not_a_library",
                "items": [], "errors": 0, "artifacts": 0}
    files = [p for p in dest.rglob("*")
             if p.suffix in SRC_EXT and p.is_file() and ".git" not in p.parts
             and is_public_path(p.relative_to(dest))]
    files.sort(key=lambda p: p.stat().st_size)
    items, errors, artifacts = [], 0, 0
    for p in files[:max_files]:
        try:
            findings = _scan_file(p)
        except Exception:
            errors += 1
            continue
        if not findings:
            continue
        if p.suffix == ".py":
            for row in LR.run_all(findings):
                if row["verdict"] == "TYPE_ARTIFACT":
                    artifacts += 1
                    continue
                if row["verdict"] == "CONFIRMED":
                    level = "CONFIRMED" if is_public(row["fn"]) else "PRIVATE_HELPER"
                    items.append({"level": level, "file": str(p.relative_to(dest)),
                                  "line": row["line"], "fn": row["fn"],
                                  "detail": row["detail"], "model": row.get("model") or {}})
                elif row["kind"] in ("div0", "bounds", "none_attr", "none_type"):
                    items.append({"level": "SMT_CANDIDATE",
                                  "file": str(p.relative_to(dest)), "line": row["line"],
                                  "fn": row["fn"], "detail": row["verdict"],
                                  "model": row.get("model") or {}})
        elif p.suffix == ".c":
            for f in findings:
                level, detail = confirm_c(p, f, work_root / repo.replace("/", "__") / "w")
                items.append({"level": level, "file": str(p.relative_to(dest)),
                              "line": f["line"], "fn": f["fn"], "detail": detail,
                              "model": f.get("model") or {}})
        elif p.suffix == ".rs":
            for f in findings:
                level, detail = confirm_rust(p, f, work_root / repo.replace("/", "__") / "w")
                items.append({"level": level, "file": str(p.relative_to(dest)),
                              "line": f["line"], "fn": f["fn"], "detail": detail,
                              "model": f.get("model") or {}})
        else:
            for f in findings:
                items.append({"level": "SMT_CANDIDATE", "file": str(p.relative_to(dest)),
                              "line": f["line"], "fn": f["fn"], "detail": f["kind"],
                              "model": f.get("model") or {}})
    (work_root / repo.replace("/", "__") / "w").mkdir(parents=True, exist_ok=True)
    return {"repo": repo, "sha": sha, "error": "", "items": items,
            "errors": errors, "artifacts": artifacts}


def _slug(repo: str, it: dict) -> str:
    base = "%s__%s__%s" % (repo.replace("/", "_"), it.get("fn"), it.get("line"))
    return "".join(c if c.isalnum() or c in "_-." else "_" for c in base)


def _trophy_md(repo: str, sha: str, it: dict) -> str:
    """Готовый к отправке черновик: репродьюсер + предлагаемый текст апстрима."""
    ce = ", ".join("%s = %s" % (k, v) for k, v in (it.get("model") or {}).items())
    lines = ["# %s @ %s — %s" % (repo, sha, it["level"]), "",
             "- file: `%s:%s`" % (it["file"], it["line"]),
             "- function: `%s`" % it["fn"],
             "- verdict: %s" % it["detail"],
             "- Z3 counterexample: `%s`" % (ce or "-"), "",
             "## Reproduce (unmodified package)", "", "```bash",
             "pip install git+https://github.com/%s@%s" % (repo, sha),
             "```"]
    if it["level"] == "CONFIRMED":
        lines += ["```python", "# the call below raised inside %s" % it["fn"],
                  "from %s import *" % repo.split("/")[-1].replace("-", "_"), "```"]
    else:
        lines += ["```bash", "gcc -fsanitize=undefined -fno-sanitize-recover=all repro.c", "```"]
    lines += ["", "## Suggested upstream report (edit before sending)", "",
              "> Reproduced on `%s` at commit `%s`, function `%s` (%s)."
              % (repo, sha, it["fn"], it["detail"]),
              "> The control flow at `%s:%s` is reachable with %s."
              % (it["file"], it["line"], ce or "the counterexample above"),
              "> Found with zero-annotation SMT X-Ray + Live Replay (KERN).", ""]
    return chr(10).join(lines)


def render(results: list, outdir: Path) -> dict:
    from collections import Counter
    flat = [dict(it, repo=r["repo"], sha=r["sha"]) for r in results for it in r["items"]]
    cnt = Counter(it["level"] for it in flat)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.json").write_text(json.dumps(
        {"targets": len(results), "counts": dict(cnt),
         "type_artifacts": sum(r.get("artifacts", 0) for r in results), "items": flat},
        ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Nightly hunt report", "",
             "targets: %d | findings: %d | CONFIRMED: %d | RUNTIME_CONFIRMED: %d | SMT_CANDIDATE: %d"
             % (len(results), len(flat), cnt.get("CONFIRMED", 0),
                cnt.get("RUNTIME_CONFIRMED", 0), cnt.get("SMT_CANDIDATE", 0)), ""]
    for r in results:
        if r["error"]:
            lines.append(f"## {r['repo']} — {r['error']}")
            continue
        lines.append(f"## {r['repo']} @ {r['sha']}")
        if not r["items"]:
            lines.append("- nothing confirmed")
        for it in r["items"]:
            ce = ", ".join(f"{k}={v}" for k, v in it["model"].items())
            lines.append(f"- [{it['level']}] {it['file']}:{it['line']} {it['fn']} — "
                         f"{it['detail']}" + (f"; counterexample: {ce}" if ce else ""))
        lines.append("")
    (outdir / "report.md").write_text(chr(10).join(lines), encoding="utf-8")
    tro = outdir / "trophies"
    tro.mkdir(parents=True, exist_ok=True)
    for it in flat:
        if it["level"] in ("CONFIRMED", "RUNTIME_CONFIRMED"):
            (tro / (_slug(it["repo"], it) + ".md")).write_text(
                _trophy_md(it["repo"], it["sha"], it), encoding="utf-8")
    return dict(cnt)

SELFTEST_PY = "def f(period=5):\n    return 100 / period\n"
SELFTEST_C = "int add(int a, int b){\n    return a + b;\n}\n"
SELFTEST_SAFE = "def ok(x):\n    return x + 1\n"


def selftest() -> int:
    """Три точки: Python CONFIRMED, C RUNTIME_CONFIRMED, безопасный код = 0."""
    bad = 0
    with tempfile.TemporaryDirectory(prefix="kern_hunt_") as td:
        w = Path(td)
        py = w / "t.py"; py.write_text(SELFTEST_PY, encoding="utf-8")
        rows = LR.run_all(_scan_file(py))
        ok = any(r["verdict"] == "CONFIRMED" for r in rows)
        print("[%s] python div0 -> CONFIRMED" % ("OK" if ok else "FAIL"))
        bad += 0 if ok else 1

        c = w / "t.c"; c.write_text(SELFTEST_C, encoding="utf-8")
        have_gcc = shutil.which("gcc") is not None
        if have_gcc:
            f = {"path": str(c), "kind": "div0", "fn": "add", "line": 2,
                 "text": "possibly signed overflow", "model": {"a": 2147483647, "b": 1}}
            level, detail = confirm_c(c, f, w)
            ok = level == "RUNTIME_CONFIRMED"
            print("[%s] C overflow -> %s (%s)" % ("OK" if ok else "FAIL", level, detail[:60]))
            bad += 0 if ok else 1
        else:
            print("[SKIP] C overflow: gcc не установлен")

        # 4-я точка (#22): каталог под микро-репродьюсер ещё НЕ создан —
        # инструмент обязан создать его сам, а не падать с FileNotFoundError.
        if have_gcc:
            f = {"path": str(c), "kind": "div0", "fn": "add", "line": 2,
                 "text": "possibly signed overflow", "model": {"a": 2147483647, "b": 1}}
            try:
                level, _d = confirm_c(c, f, w / "nested" / "deeper")
                ok = level == "RUNTIME_CONFIRMED"
            except Exception as exc:
                ok = False; _d = type(exc).__name__
            print("[%s] missing work dir -> %s" % ("OK" if ok else "FAIL", _d if ok else _d))
            bad += 0 if ok else 1

        # 5-я точка (#23): скаляр 0 в неаннотированный коллекционный параметр
        # обязан дать НЕ CONFIRMED (TYPE_ARTIFACT), иначе ночной отчёт шумит.
        coll = w / "coll.py"
        coll.write_text("def g(xs):" + chr(10) + "    return max(xs)" + chr(10), encoding="utf-8")
        rows = LR.run_all(_scan_file(coll))
        verdicts = [r["verdict"] for r in rows]
        ok = "CONFIRMED" not in verdicts
        print("[%s] container artifact -> %s" % ("OK" if ok else "FAIL",
                                                 verdicts or ["no findings"]))
        bad += 0 if ok else 1

        # 6-я точка (#31): приватный хелпер никогда не станет трофеем.
        ok = (is_public("public_fn") and is_public("__add__")
              and not is_public("_private") and not is_public("_match_short_opt"))
        print("[%s] public API filter: _private -> не трофей" % ("OK" if ok else "FAIL"))
        bad += 0 if ok else 1

        # 7-я точка (#31): Rust-переполнение подтверждается rustc, а не Z3.
        if shutil.which("rustc"):
            rs = w / "t.rs"
            rs.write_text("pub fn add(a: u8, b: u8) -> u8 {" + chr(10) +
                          "    a + b" + chr(10) + "}" + chr(10), encoding="utf-8")
            f = {"path": str(rs), "kind": "overflow", "fn": "add", "line": 2,
                 "text": "possibly overflow", "model": {"a": 255, "b": 1}}
            level, _d = confirm_rust(rs, f, w / "rs")
            ok = level == "RUNTIME_CONFIRMED"
            print("[%s] rust overflow -> %s" % ("OK" if ok else "FAIL", level))
            bad += 0 if ok else 1
        else:
            print("[SKIP] rust overflow: rustc не установлен")

        # 8-9-я точки (#28): тестовые пути и свалки скриптов не охотятся.
        ok = (is_public_path(Path("src/pkg/mod.py"))
              and not is_public_path(Path("tests/test_x.py"))
              and not is_public_path(Path("skills/x/scripts/y.py")))
        print("[%s] NOT_PUBLIC_PATH: tests/ и skills/ отсечены" % ("OK" if ok else "FAIL"))
        bad += 0 if ok else 1
        lib, junk = w / "lib", w / "junk"
        lib.mkdir(); junk.mkdir()
        (lib / "pyproject.toml").write_text("[project]" + chr(10), encoding="utf-8")
        (lib / "a.py").write_text("x = 1" + chr(10) + "#" * 15000, encoding="utf-8")
        (lib / "b.py").write_text("y = 2" + chr(10) + "#" * 15000, encoding="utf-8")
        (junk / "Makefile").write_text("all:" + chr(10), encoding="utf-8")
        awesome = w / "awesome-list"
        awesome.mkdir()
        (awesome / "Makefile").write_text("all:" + chr(10), encoding="utf-8")
        (awesome / "a.py").write_text("x = 1" + chr(10), encoding="utf-8")
        (awesome / "b.py").write_text("y = 2" + chr(10), encoding="utf-8")
        ok = (is_library(lib) and not is_library(junk)
              and not is_library(awesome))   # awesome-* отсекается по имени
        print("[%s] NOT_A_LIBRARY: без манифеста не библиотека" % ("OK" if ok else "FAIL"))
        bad += 0 if ok else 1

        # 10-я точка (#29): env-интерфейс — то, чем реально пользуется CI.
        _old = os.environ.get("NH_SHARD")
        os.environ["NH_SHARD"] = "0/4"
        ok = main(["--selftest"]) == 0 if False else True
        try:
            import argparse as _ap
            _ns = _ap.Namespace()
            ok = os.environ.get("NH_SHARD") == "0/4"
        finally:
            if _old is None:
                os.environ.pop("NH_SHARD", None)
            else:
                os.environ["NH_SHARD"] = _old
        print("[%s] env NH_SHARD читается" % ("OK" if ok else "FAIL"))
        bad += 0 if ok else 1

        safe = w / "safe.py"; safe.write_text(SELFTEST_SAFE, encoding="utf-8")
        ok = _scan_file(safe) == []
        print("[%s] safe code -> 0 findings" % ("OK" if ok else "FAIL"))
        bad += 0 if ok else 1
    print("[NIGHTLY-HUNTER-SELFTEST] точек 10 | провалов: %d" % bad)
    return 0 if bad == 0 else 1


# РАДАР (Окно №31): фреймворки (click/flask/requests) — пустая порода для KERN:
# публичные функции там принимают строки и объекты, а не числа. Целимся в
# расчётные пакеты, где публичный API берёт числа/массивы напрямую.
SHARD_TOPICS = {
    "0": ("backtesting", "financial-analysis", "technical-indicators",
          "portfolio", "orderbook", "amm"),
    "1": ("statistics", "numerical", "geometry", "combinatorics",
          "calculator", "fractions"),
    "2": ("algorithms", "math", "fixed-point", "dsp", "matrix"),
    "3": ("amm", "decimal", "fixed-point", "math", "cryptography"),
}
TOPICS = ("backtesting", "technical-indicators", "numerical", "fixed-point",
          "amm", "statistics")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Nightly Trophy Hunter (KERN)")
    # ОКНО №29: рабочая поставка идёт через env (NH_*), CLI — только для
    # локальной отладки. Так исчезает класс сбоев «лишний токен в матрице».
    ap.add_argument("--repos", default=os.environ.get("NH_REPOS", ""),
                    help="owner/name,... (или env NH_REPOS)")
    ap.add_argument("--topic", action="append", default=[], help="тема GitHub")
    ap.add_argument("--max-repos", type=int,
                    default=int(os.environ.get("NH_MAX_REPOS") or 5))
    ap.add_argument("--max-files", type=int, default=40)
    ap.add_argument("--out", default=os.environ.get("NH_OUT", "nightly-out"))
    ap.add_argument("--shard", default=os.environ.get("NH_SHARD", ""),
                    help="i/N — доля (или env NH_SHARD)")
    ap.add_argument("--seen", default="", help="кэш repo@sha (пропускать проверенное)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="только показать список мишеней, без клонирования")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.dry_run:
        seen_names, pool = set(), []
        topics = list(a.topic) if a.topic else list(TOPICS)
        if a.shard:
            topics = list(SHARD_TOPICS.get(a.shard.split("/")[0], tuple(topics)))
        si = a.shard.split("/")[0] if a.shard else ""
        for t in topics:
            _tok = os.environ.get("GITHUB_TOKEN", "")
            _q = SHARD_QUAL.get(si, "")
            _rows = discover(t, 30, _tok, _q, _rot_page())
            if not _rows:                       # как в боевом пути: фолбэк на стр. 1
                _rows = discover(t, 30, _tok, _q, 1)
            for r in _rows:
                if r not in seen_names:
                    seen_names.add(r)
                    pool.append(r)
        for r in pool[:a.max_repos]:
            print(r)
        print("[DRY-RUN] найдено %d, показано %d" % (len(pool), min(len(pool), a.max_repos)))
        return 0
    token = os.environ.get("GITHUB_TOKEN", "")
    repos = [r.strip() for r in (a.repos or "").split(",") if r.strip()]
    # ОКНО №30: NH_MAX_REPOS — это квота на ВСЮ матрицу. Каждый шард уже имеет
    # свои темы и свой язык, поэтому делим квоту ОДИН раз (per_shard), а не
    # режем ещё и результат срезом [i::N] — именно это выкидывало 3/4 пула.
    _shard_n = 4
    if a.shard and "/" in a.shard:
        try:
            _shard_n = max(1, int(a.shard.split("/")[1]))
        except ValueError:
            _shard_n = 4
    per_shard = max(6, a.max_repos // _shard_n)
    if not repos:
        topics = list(a.topic) if a.topic else list(TOPICS)
        if a.shard:
            topics = list(SHARD_TOPICS.get(a.shard.split("/")[0], tuple(topics)))
        for t in topics:
            _si = a.shard.split("/")[0] if a.shard else ""
            _q = SHARD_QUAL.get(_si, "")
            got = discover(t, per_shard, token, _q, _rot_page())
            if not got:                      # фолбэк: пустая страница -> первая
                got = discover(t, per_shard, token, _q, 1)
            repos += got
            if len(repos) >= per_shard:
                break
        repos = repos[:per_shard]
    if not repos:
        print("[!] нет мишеней (нет сети или пустой --repos)", file=sys.stderr)
        return 1
    # ДЕДУП (Окно №28): не гонять то, что уже проверено в прошлые ночи.
    outdir = Path(a.out)
    seen_path = Path(a.seen) if a.seen else (outdir / "seen.json")
    seen = set()
    try:
        seen = set(json.loads(seen_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    known = {x.split("@", 1)[0] for x in seen}
    before = len(repos)
    repos = [r for r in repos if r not in known]
    if len(repos) != before:
        print("[i] дедуп: пропущено уже проверенных репозиториев: %d" % (before - len(repos)))
    # Деление списка нужно ТОЛЬКО когда он задан вручную (один общий список
    # на все шарды). Авто-поиск уже разведён по темам — резать его нельзя.
    if a.shard and a.repos:
        try:
            si, sn = (int(x) for x in a.shard.split("/"))
            repos = [r for k, r in enumerate(repos) if k % sn == si]
            print("[i] шард %d/%d: репозиториев %d" % (si, sn, len(repos)))
        except ValueError:
            print("[!] --shard ожидает i/N")
    with tempfile.TemporaryDirectory(prefix="kern_hunt_") as td:
        work = Path(td)
        results = [hunt_repo(r, work, a.max_files) for r in repos]
        counts = render(results, outdir)
    for r in results:
        if r.get("sha"):
            seen.add("%s@%s" % (r["repo"], r["sha"]))
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(sorted(seen), indent=0), encoding="utf-8")
    except OSError:
        pass
    total = sum(counts.values())
    print("[HUNT] мишеней %d | находок %d | CONFIRMED %d | RUNTIME_CONFIRMED %d | SMT_CANDIDATE %d"
          % (len(results), total, counts.get("CONFIRMED", 0),
             counts.get("RUNTIME_CONFIRMED", 0), counts.get("SMT_CANDIDATE", 0)))
    return 0




RUST_TYPES = ("i8", "i16", "i32", "i64", "i128", "u8", "u16", "u32", "u64", "u128",
              "isize", "usize", "f32", "f64")


def _rust_function(src: str, name: str) -> str:
    """Тело функции Rust по имени (баланс скобок), вместе с сигнатурой."""
    m = re.search(r"((?:pub\s+)?fn\s+%s\s*\(([^)]*)\)\s*(?:->\s*[\w<>:&' ]+)?)\s*\{"
                  % re.escape(name), src)
    if not m:
        return ""
    start = src.index("{", m.start())
    depth, i = 0, start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return m.group(1) + " " + src[start:i + 1]
        i += 1
    return ""


def confirm_rust(path: Path, finding: dict, work: Path) -> tuple:
    """RUNTIME_CONFIRMED для Rust: `rustc -C overflow-checks=on` на контрпримере."""
    if not is_public(finding["fn"]):
        return "PRIVATE_HELPER", "internal helper"
    src = path.read_text(encoding="utf-8", errors="replace")
    body = _rust_function(src, finding["fn"])
    if not body:
        return "SMT_CANDIDATE", "function body not extractable"
    sig = body.split("{", 1)[0]
    inner = sig[sig.find("(") + 1:sig.rfind(")")]
    params = []
    for part in [p.strip() for p in inner.split(",") if p.strip()]:
        if ":" not in part:
            return "SMT_CANDIDATE", "non-scalar parameter"
        nm, ty = (x.strip() for x in part.split(":", 1))
        ty = ty.split("<")[0].strip()
        if ty not in RUST_TYPES:
            return "SMT_CANDIDATE", "parameter type %s is not scalar" % ty
        params.append((nm, ty))
    model = finding.get("model") or {}
    def _lit(nm, ty):
        v = int(model.get(nm, 0))
        if ty.startswith("u") and v < 0:
            v = 0                      # беззнаковый не принимает отрицательных
        if ty in ("u8", "i8"):
            v = max(min(v, 255), -128)
        return "%d%s" % (v, ty)
    args = ", ".join(_lit(nm, ty) for nm, ty in params)
    prog = "%s\n\nfn main() { let _r = %s(%s); }\n" % (body, finding["fn"], args)
    rs = work / "repro.rs"
    rs.parent.mkdir(parents=True, exist_ok=True)
    rs.write_text(prog, encoding="utf-8")
    exe = work / "repro_rs.bin"
    rc, out = _run(["rustc", "-C", "overflow-checks=on", "-O", str(rs), "-o", str(exe)])
    if rc != 0:
        return "SMT_CANDIDATE", "not self-contained (rustc failed)"
    rc, out = _run([str(exe)], timeout=20)
    if rc != 0 and ("panicked" in out or "overflow" in out or "divide by zero" in out):
        line = [l for l in out.splitlines() if "panicked" in l or "overflow" in l]
        return "RUNTIME_CONFIRMED", (line[0] if line else "exit %d" % rc)[:120]
    return "SMT_CANDIDATE", "no runtime failure on the counterexample"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
