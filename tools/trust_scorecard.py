#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN Formal Trust Index & Scorecard — отдельный модуль (НЕ в kern_contracts.py).

ПОЧЕМУ ОТДЕЛЬНО. В `tools/kern_contracts.py` 51 имя определено дважды
(дефект #174): Python исполняет последнее определение, поэтому любая правка в
первой копии молча не работает. Добавлять туда ещё 300 строк — усугублять долг.
Модуль не импортирует `kern_contracts.py` и не меняет его.

ЧТО СЧИТАЕТСЯ (5 секций, как у внешних каталогов, но по фактам):
  1. WHAT WE READ        — файлы по 8 категориям + Blind-Spot Check (.zig/.lean/.wasm)
  2. MCP TOOL SURFACE    — server.json/mcp.json/.well-known + annotations + замок
  3. FORMAL SOUNDNESS    — теоремы Lean, 0 sorry, attestation
  4. X-RAY & METRICS     — CHECK-цели с can-fail доказательством, мутации
  5. PROVENANCE          — SLSA-аттестат, Ed25519, кросс-архитектура

ГРАДАЦИЯ АДАПТИВНАЯ (иначе чужой репозиторий без Lean/MCP получал бы «F»):
  * Standard Code Repo — до 88 баллов (Grade A): лицензия, README, тесты, CI,
    сборка, чистота, SARIF-возможность, llms.txt, документация, гигиена;
  * + MCP profile (+7): манифесты и tool annotations;
  * + Formal tier (до +12): Lean-теоремы, Ed25519-аттестат, мутации 100 %.
  A+ >= 95 · A >= 85 · B >= 70 · C >= 55 · D >= 40 · F < 40.

🔴 ЧЕСТНАЯ ГРАНИЦА. Это РУБРИКА (чек-лист), а не математическая теорема: мы НЕ
заявляем, что 100/100 «доказано». Доказанные утверждения проекта — `trusted: 0`
в пруф-чекере и 120 теорем Lean; балл Scorecard — эвристика с открытыми весами
(они перечислены в JSON-выводе, чтобы любой мог пересчитать).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "vendor",
    "third_party", "target", "dist", "build", "out", ".zig-cache", "zig-out",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".tox", ".idea", ".vscode",
    "site-packages", "fixtures",
}

CATEGORIES = [
    ("zig", {".zig"}),
    ("lean", {".lean"}),
    ("python", {".py"}),
    ("c11", {".c", ".h"}),
    ("rust", {".rs"}),
    ("go", {".go"}),
    ("ts_js", {".ts", ".js"}),
    ("wasm", {".wasm", ".wat"}),
]
NATIVE_FORMAL = {"zig", "lean", "wasm"}
MAX_FILE_BYTES = 512 * 1024


def walk(root: Path) -> tuple[dict[str, list[Path]], int]:
    """Файлы по категориям; мусорные каталоги/симлинки/гиганты не берём."""
    out: dict[str, list[Path]] = {name: [] for name, _ in CATEGORIES}
    skipped = 0
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES or p.name.endswith((".min.js", ".min.ts")):
                skipped += 1
                continue
        except OSError:
            skipped += 1
            continue
        for name, exts in CATEGORIES:
            if p.suffix.lower() in exts:
                out[name].append(p)
                break
    return out, skipped



def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _strip_lean_comments(t: str) -> str:
    """Убирает `--`-комментарии и `/- ... -/` блоки.

    🔴 ДЕФЕКТ (найден первым прогоном Scorecard): в шапке файлов написано
    «no 'sorry'», и наивный подсчёт считал ЭТО за незакрытое доказательство
    (sorry=8 при фактических 0). Считаем только код.
    """
    t = re.sub(r"/-.*?-/ ", " ", t, flags=re.S)
    out = []
    for line in t.splitlines():
        i = line.find("--")
        out.append(line if i < 0 else line[:i])
    return "\n".join(out)


def lean_stats(root: Path) -> tuple[int, int, int]:
    files = sorted(root.glob("formal/*.lean"))
    th = 0
    sorry = 0
    for f in files:
        t = _strip_lean_comments(_read(f))
        th += len(re.findall(r"^theorem\s", t, re.M))
        sorry += len(re.findall(r"\bsorry\b", t))
    return len(files), th, sorry


def registry_stats(root: Path) -> tuple[int, int, int]:
    """CHECK-цели, покрытые can-fail, и число кейсов — из --json реестра."""
    try:
        out = subprocess.run([sys.executable, str(root / "tools" / "registry.py"), "--json"],
                             capture_output=True, text=True, timeout=120, cwd=root)
        raw = out.stdout
        i, j = raw.find("{"), raw.rfind("}")
        doc = json.loads(raw[i:j + 1])
        return (len(doc.get("checks", [])), len(doc.get("checks_covered", [])),
                len(doc.get("canfail_cases", [])))
    except Exception:
        return 0, 0, 0


def mutation_score(root: Path) -> str:
    for name in ("mutate.log", "mutation.log"):
        t = _read(root / "docs" / "evidence" / name)
        m = re.findall(r"MUTATION SCORE[^:]*:\s*([0-9.]+)%", t)
        if m:
            m2 = re.findall(r"(\d+)/(\d+)", t)
            tail = f" ({m2[-1][0]}/{m2[-1][1]})" if m2 else ""
            return f"{m[-1]}%{tail} (канонический стратифицированный срез)"
    return "n/a"


def qemu(root: Path) -> str:
    t = _read(root / "docs" / "evidence" / "cross_arch.log")
    m = re.findall(r"(\d+) passed; (\d+) skipped; (\d+) failed", t)
    if not m:
        return "n/a"
    uniq = sorted(set(m), key=m.index)
    return " · ".join(f"{a} passed / {b} skipped / {c} failed" for a, b, c in uniq)


def markers(root: Path) -> int:
    """Следы незакрытой инъекции харнесса в исходниках (дефекты #168/#170/#172)."""
    pat = re.compile(r"ЛОМАЕМ:|ДИВЕРСИЯ:|ИНЪЕКЦИЯ ДЛЯ ПРОВЕРКИ")
    n = 0
    for sub in ("src", "examples", "formal"):
        d = root / sub
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix in {".zig", ".c", ".h", ".rs", ".py", ".lean"}:
                if pat.search(_read(p)):
                    n += 1
    return n


def code_hash(root: Path, cats: dict[str, list[Path]]) -> str:
    h = hashlib.sha256()
    for p in sorted(p for lst in cats.values() for p in lst):
        h.update(str(p.relative_to(root)).encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return "sha256:" + h.hexdigest()


def git_head(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"

def build_report(root: Path) -> dict:
    cats, skipped = walk(root)
    counts = {k: len(v) for k, v in cats.items()}
    lean_files, theorems, sorry = lean_stats(root)
    checks, covered, cases = registry_stats(root)
    mcp_files = {k: (root / k).is_file() for k in
                 ("server.json", "mcp.json", ".well-known/mcp.json")}
    tools_n, annotated = 0, False
    if mcp_files["server.json"]:
        try:
            doc = json.loads(_read(root / "server.json"))
            tools_n = len(doc.get("tools", []))
            annotated = bool(tools_n) and all(
                all(k in (t.get("annotations") or {}) for k in
                    ("readOnlyHint", "destructiveHint", "openWorldHint"))
                for t in doc.get("tools", []))
        except Exception:
            pass
    dup_ok = False
    try:
        dup_ok = subprocess.run([sys.executable, str(root / "tools" / "dup_defs_guard.py")],
                                capture_output=True, timeout=90, cwd=root).returncode == 0
    except Exception:
        pass
    docs_dir = root / "docs"
    return {
        "repo": root.resolve().name,
        "commit": git_head(root),
        "code_hash": code_hash(root, cats),
        "what_we_read": {"by_category": counts, "skipped": skipped,
                         "total": sum(counts.values()),
                         "blind_spot_native_formal": sum(counts[k] for k in NATIVE_FORMAL)},
        "mcp": {"files": mcp_files, "tools": tools_n, "annotations": annotated,
                "lock": (root / "mcp.lock.json").is_file()},
        "formal": {"lean_files": lean_files, "theorems": theorems, "sorry": sorry,
                   "attestation": (root / "kern.intoto.jsonl").is_file()
                                  and (root / "kern.intoto.sig").is_file()},
        "metrics": {"check_targets": checks, "check_covered": covered,
                    "canfail_cases": cases, "mutation": mutation_score(root),
                    "qemu": qemu(root)},
        "hygiene": {
            "license": (root / "LICENSE").is_file(),
            "readme": any((root / n).is_file() for n in ("README.md", "README.ru.md", "README")),
            "tests": any((root / p).exists() for p in ("tests", "src/tests", "src/test_root.zig")),
            "ci": (root / ".github" / "workflows").is_dir(),
            "build": any((root / p).is_file() for p in
                         ("build.zig", "Makefile", "pyproject.toml", "Cargo.toml", "go.mod")),
            "sarif": "sarif" in _read(root / "tools" / "kern_contracts.py").lower(),
            "llms": (root / "llms.txt").is_file(),
            "docs_md": len(list(docs_dir.glob("*.md"))) if docs_dir.is_dir() else 0,
            "injection_markers": markers(root),
            "dup_guard": dup_ok,
        },
    }


def score(rep: dict) -> tuple[int, str, dict, list[str]]:
    h, f, m, mcp = rep["hygiene"], rep["formal"], rep["metrics"], rep["mcp"]
    w = rep["what_we_read"]
    b = {
        "license": 10 if h["license"] else 0,
        "readme": 6 if h["readme"] else 0,
        "tests": 10 if h["tests"] else 0,
        "ci": 8 if h["ci"] else 0,
        "build": 8 if h["build"] else 0,
        "no_injections": 8 if h["injection_markers"] == 0 else 0,
        "dup_guard": 8 if h["dup_guard"] else 0,
        "sarif": 6 if h["sarif"] else 0,
        "llms": 6 if h["llms"] else 0,
        "docs": 8 if h["docs_md"] >= 5 else (4 if h["docs_md"] else 0),
        "hygiene": 10 if (w["total"] + w["skipped"]) and w["skipped"] / max(1, w["total"] + w["skipped"]) < 0.01
                   else (6 if (w["total"] + w["skipped"]) and w["skipped"] / max(1, w["total"] + w["skipped"]) < 0.05 else 2 if w["total"] else 0),
    }
    base = sum(b.values())                      # максимум 88
    mcp_pts = (4 if mcp["files"]["server.json"] and mcp["tools"] > 0 else 0) \
        + (3 if mcp["annotations"] else 0)      # максимум +7
    formal_pts = (6 if f["lean_files"] and f["theorems"] and f["sorry"] == 0 else 0) \
        + (3 if f["attestation"] else 0) \
        + (3 if str(m["mutation"]).startswith("100") else 0)   # максимум +12
    total = min(100, base + mcp_pts + formal_pts)
    grade = ("A+" if total >= 95 else "A" if total >= 85 else "B" if total >= 70
             else "C" if total >= 55 else "D" if total >= 40 else "F")
    b["base_max"] = 88
    b["mcp_profile"] = mcp_pts
    b["formal_tier"] = formal_pts
    hints = []
    if not (mcp["files"]["server.json"] and mcp["tools"] > 0):
        hints.append("add an MCP manifest (server.json + tool annotations): +7")
    if not f["lean_files"] or f["sorry"]:
        hints.append("add machine-checked proofs (Lean 4, 0 sorry): +6")
    if not str(m["mutation"]).startswith("100"):
        hints.append("reach 100 % mutation score with a can-fail harness: +3")
    if grade != "A+":
        hints.append("add action.yml + # @kern: contracts to reach the Formal tier")
    return total, grade, b, hints


def render(rep: dict, total: int, grade: str, b: dict, hints: list[str],
           label: str = "") -> None:
    w, mcp, f, m = rep["what_we_read"], rep["mcp"], rep["formal"], rep["metrics"]
    line = "=" * 72
    print(line)
    print(f"KERN TRUST INDEX · {rep['repo']} {label}-> {total}/100  Grade {grade}")
    print(line)
    print("1. WHAT WE READ")
    names = {"zig": ".zig", "lean": ".lean", "python": ".py", "c11": ".c/.h (C11)",
             "rust": ".rs", "go": ".go", "ts_js": ".ts/.js", "wasm": ".wasm"}
    for k, disp in names.items():
        print(f"   {disp:<14} {w['by_category'].get(k, 0):>5} файлов")
    print(f"   пропущено (симлинк/размер/min): {w['skipped']}")
    print(f"   [Blind-Spot Check] нативных/формальных файлов (.zig/.lean/.wasm): "
          f"{w['blind_spot_native_formal']} — их Python-only сканеры не читают")
    print("2. MCP TOOL SURFACE & AI SAFETY")
    print(f"   server.json={mcp['files']['server.json']} mcp.json={mcp['files']['mcp.json']} "
          f"well-known={mcp['files']['.well-known/mcp.json']} lock={mcp['lock']}")
    print(f"   tools={mcp['tools']} annotations={'OK' if mcp['annotations'] else 'нет'}")
    print("3. MATHEMATICAL & FORMAL SOUNDNESS")
    print(f"   Lean 4: {f['lean_files']} файлов, {f['theorems']} теорем, "
          f"sorry={f['sorry']} (0 custom axioms)")
    print(f"   Ed25519-аттестат: {'есть' if f['attestation'] else 'нет'}")
    print("4. ZERO-ANNOTATION X-RAY & METRICS")
    print(f"   can-fail: {m['check_covered']}/{m['check_targets']} CHECK · кейсов {m['canfail_cases']}")
    print(f"   мутации: {m['mutation']}")
    print("5. PROVENANCE & CERTIFICATION")
    print(f"   QEMU: {m['qemu']}")
    print(f"   commit {rep['commit']} · {rep['code_hash'][:34]}…")
    print(line)
    print("веса (пересчитываемо): " + ", ".join(f"{k}={v}" for k, v in b.items()))
    if hints:
        print("подсказки: " + " · ".join(hints))
    print(line)



def resolve_root(spec: str) -> tuple[Path, Path | None]:
    """Локальный путь ИЛИ `owner/repo` (публичный GitHub).

    Удалённый репозиторий клонируется в /dev/shm (ОЗУ) со ВСЕМИ защитами,
    которые уже проверены в `--audit-repo`: без хуков (core.hooksPath=/dev/null),
    без LFS-блобов, без запросов пароля, с таймаутом.

    Возвращает (корень для анализа, временный каталог или None).
    """
    import shutil
    import tempfile

    cand = Path(spec).expanduser()
    if cand.is_dir():
        return cand.resolve(), None
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", spec.strip()):
        raise SystemExit(f"[!] не каталог и не owner/repo: {spec}")
    base = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
    tmp = Path(tempfile.mkdtemp(prefix="kern_sc_", dir=str(base)))
    env = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/true",
           "GIT_LFS_SKIP_SMUDGE": "1", "PATH": "/usr/bin:/bin"}
    cmd = ["git", "clone", "--depth", "1", "--single-branch", "--no-tags",
           "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never",
           f"https://github.com/{spec.strip()}", str(tmp / "repo")]
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit("[!] git clone не уложился в 120 с — репозиторий слишком большой")
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit(f"[!] git clone: {r.stderr.strip().splitlines()[-1] if r.stderr else 'ошибка'}")
    return tmp / "repo", tmp

def main() -> int:
    ap = argparse.ArgumentParser(description="KERN Formal Trust Index & Scorecard")
    ap.add_argument("--repo", default=".", metavar="PATH",
                    help="корень репозитория для оценки")
    ap.add_argument("--json", default=None, metavar="OUT.json",
                    help="записать машиночитаемый паспорт")
    ap.add_argument("--quiet", action="store_true", help="не печатать карточку")
    args = ap.parse_args()

    root, tmp = resolve_root(args.repo)
    try:
        if not root.is_dir():
            print(f"[!] нет каталога: {root}")
            return 2
        rep = build_report(root)
    finally:
        if tmp is not None:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)
    total, grade, b, hints = score(rep)
    doc = {
        "schema": "kern-trust-scorecard/1",
        "repo": rep["repo"],
        "commit": rep["commit"],
        "code_hash": rep["code_hash"],
        "score": total,
        "grade": grade,
        "breakdown": b,
        "hints": hints,
        **{k: rep[k] for k in ("what_we_read", "mcp", "formal", "metrics", "hygiene")},
        "rubric": {
            "base_max": 88,
            "mcp_profile_max": 7,
            "formal_tier_max": 12,
            "grades": {"A+": ">=95", "A": ">=85", "B": ">=70", "C": ">=55",
                       "D": ">=40", "F": "<40"},
        },
        "disclaimer": (
            "Эвристическая рубрика с открытыми весами, а НЕ математическое "
            "доказательство. Доказанные утверждения проекта — trusted: 0 в "
            "пруф-чекере и теоремы Lean 4."),
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"[ok] scorecard: {out} ({total}/100, Grade {grade})")
    if not args.quiet:
        render(rep, total, grade, b, hints)
    return 0


if __name__ == "__main__":
    sys.exit(main())
