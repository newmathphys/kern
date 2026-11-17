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
SRC_EXT = (".py", ".c", ".rs", ".zig")
MAX_FILE_BYTES = 400_000

sys.path.insert(0, str(TOOLS))
import live_replay as LR  # noqa: E402  — запечатанный контур из окна №16


def _run(cmd, cwd=None, timeout=300):
    try:
        r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def discover(topic: str, limit: int, token: str = "") -> list:
    """Живые репозитории по теме через GitHub Search (stdlib, без зависимостей)."""
    q = urllib.parse.quote(f"topic:{topic} stars:50..25000 archived:false")
    url = f"https://api.github.com/search/repositories?q={q}&sort=updated&per_page={limit}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "kern-nightly-hunter"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    return [it["full_name"] for it in data.get("items", [])][:limit]


def clone(repo: str, dest: Path) -> str:
    rc, _ = _run(["git", "clone", "--depth", "1", "--quiet",
                  f"https://github.com/{repo}.git", str(dest)], timeout=300)
    if rc != 0:
        return ""
    rc, out = _run(["git", "rev-parse", "HEAD"], cwd=dest)
    return out.strip()[:12] if rc == 0 else ""


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
        return "SMT_CANDIDATE", "not self-contained (compile failed)"
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
    files = [p for p in dest.rglob("*") if p.suffix in SRC_EXT and p.is_file()
             and "test" not in p.name.lower() and ".git" not in p.parts]
    files.sort(key=lambda p: p.stat().st_size)
    items, errors = [], 0
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
                if row["verdict"] == "CONFIRMED":
                    items.append({"level": "CONFIRMED", "file": str(p.relative_to(dest)),
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
        else:
            for f in findings:
                items.append({"level": "SMT_CANDIDATE", "file": str(p.relative_to(dest)),
                              "line": f["line"], "fn": f["fn"], "detail": f["kind"],
                              "model": f.get("model") or {}})
    (work_root / repo.replace("/", "__") / "w").mkdir(parents=True, exist_ok=True)
    return {"repo": repo, "sha": sha, "error": "", "items": items, "errors": errors}


def render(results: list, outdir: Path) -> dict:
    from collections import Counter
    flat = [dict(it, repo=r["repo"], sha=r["sha"]) for r in results for it in r["items"]]
    cnt = Counter(it["level"] for it in flat)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.json").write_text(json.dumps(
        {"targets": len(results), "counts": dict(cnt), "items": flat},
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

        safe = w / "safe.py"; safe.write_text(SELFTEST_SAFE, encoding="utf-8")
        ok = _scan_file(safe) == []
        print("[%s] safe code -> 0 findings" % ("OK" if ok else "FAIL"))
        bad += 0 if ok else 1
    print("[NIGHTLY-HUNTER-SELFTEST] точек 4 | провалов: %d" % bad)
    return 0 if bad == 0 else 1


TOPICS = ("trading", "decimal", "orderbook", "quant", "fixed-point",
          "amm", "numerical", "math")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Nightly Trophy Hunter (KERN)")
    ap.add_argument("--repos", help="owner/name,owner/name — ручной список")
    ap.add_argument("--topic", action="append", default=[], help="тема GitHub")
    ap.add_argument("--max-repos", type=int, default=5)
    ap.add_argument("--max-files", type=int, default=40)
    ap.add_argument("--out", default="nightly-out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    token = os.environ.get("GITHUB_TOKEN", "")
    repos = [r.strip() for r in (a.repos or "").split(",") if r.strip()]
    if not repos:
        for t in (a.topic or list(TOPICS)):
            repos += discover(t, a.max_repos, token)
            if len(repos) >= a.max_repos:
                break
        repos = repos[:a.max_repos]
    if not repos:
        print("[!] нет мишеней (нет сети или пустой --repos)", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="kern_hunt_") as td:
        work = Path(td)
        results = [hunt_repo(r, work, a.max_files) for r in repos]
        counts = render(results, Path(a.out))
    total = sum(counts.values())
    print("[HUNT] мишеней %d | находок %d | CONFIRMED %d | RUNTIME_CONFIRMED %d | SMT_CANDIDATE %d"
          % (len(results), total, counts.get("CONFIRMED", 0),
             counts.get("RUNTIME_CONFIRMED", 0), counts.get("SMT_CANDIDATE", 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
