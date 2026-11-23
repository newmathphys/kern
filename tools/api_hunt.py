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

QUERIES_LRU = [
    '"@lru_cache" "time.time" language:Python',
    '"@lru_cache()" "datetime.now" language:Python',
    '"@cache" "random.random" language:Python',
]

QUERIES_ARITH = [
    '"lcm" "* gcd" language:C',
    '"(low + high) / 2" language:C',
    '"let mid = (left + right)" language:Rust',
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


_REPO_CACHE: dict = {}


def repo_meta(full_name: str):
    """Метаданные репозитория с кэшем: один запрос на репозиторий, а не на файл."""
    if full_name in _REPO_CACHE:
        return _REPO_CACHE[full_name]
    meta = _gh_json(["api", f"repos/{full_name}", "--jq",
                     "{stars: .stargazers_count, archived: .archived, fork: .fork, "
                     "issues: .has_issues, pushed_at: .pushed_at}"])
    _REPO_CACHE[full_name] = meta
    return meta


def repo_age_days(meta) -> float:
    """Сколько дней прошло с последнего пуша (inf, если дата неизвестна)."""
    import datetime
    stamp = (meta or {}).get("pushed_at")
    if not stamp:
        return float("inf")
    try:
        when = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except ValueError:
        return float("inf")
    return (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds() / 86400



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


NONDETERMINISTIC_CALLS = {
    "datetime.now", "datetime.datetime.now", "datetime.utcnow",
    "datetime.datetime.utcnow", "datetime.today", "datetime.datetime.today",
    "date.today", "datetime.date.today",
    "time.time", "time.monotonic", "time.perf_counter", "time.localtime",
    "time.ctime", "time.strftime",
    "random.random", "random.randint", "random.choice", "random.randrange",
    "random.uniform", "random.shuffle", "random.sample",
    "uuid.uuid4", "uuid.uuid1", "os.urandom",
}

MEMO_DECORATORS = {"lru_cache", "cache"}


def _dotted(node) -> str:
    """`time.time` -> "time.time"; `dt.datetime.now` -> "dt.datetime.now"."""
    import ast as _ast
    parts = []
    while isinstance(node, _ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, _ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


class _ImpureCallFinder:
    """Ищет ТОЛЬКО реальные вызовы часов/рандома внутри тела функции.

    Границы: вложенные `def` / `lambda` / `class` не обходятся — их тело
    исполняется не здесь (или не исполняется вовсе), а `ast.dump`-подстроки
    по докстрингам и именам аргументов давали FP на scipy.
    """

    def __init__(self):
        self.hits = []

    def scan(self, statements):
        for stmt in statements:
            self._walk(stmt)

    def _walk(self, node):
        import ast as _ast
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef,
                             _ast.Lambda, _ast.ClassDef)):
            return                      # граница области видимости
        if isinstance(node, _ast.Call):
            path = _dotted(node.func)
            if path in NONDETERMINISTIC_CALLS:
                self.hits.append(path)
        for child in _ast.iter_child_nodes(node):
            self._walk(child)


def analyse_lru(src: str, path: str) -> list:
    """Ствол lru-effects: мемоизация поверх недетерминированного тела.

    HIGH — только если функция ПРИНИМАЕТ аргументы (они и есть ключ кэша) и
    её собственное тело вызывает часы/рандом: тогда для одного и того же
    аргумента кэш навсегда фиксирует первое значение. Ноль-аргументные
    `@lru_cache`-синглтоны (например `get_settings()`) намеренны и молчат, а
    докстринги и вложенные `def` не считаются (Калибровка №6).
    """
    import ast as _ast

    if not path.endswith(".py"):
        return []
    lowered = path.lower()
    if "test_" in lowered or "_test.py" in lowered or "/tests/" in lowered:
        return []
    try:
        tree = _ast.parse(src)
    except (SyntaxError, ValueError):
        return []

    out = []
    for node in _ast.walk(tree):
        if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            continue
        memo = False
        for d in node.decorator_list:
            target = d.func if isinstance(d, _ast.Call) else d
            if _dotted(target).split(".")[-1] in MEMO_DECORATORS:
                memo = True
                break
        if not memo:
            continue
        args = [a.arg for a in node.args.posonlyargs + node.args.args
                if a.arg not in ("self", "cls")]
        args += [a.arg for a in node.args.kwonlyargs]
        if not args:
            continue      # намеренный синглтон — не наш случай
        finder = _ImpureCallFinder()
        finder.scan(node.body)
        if not finder.hits:
            continue
        out.append({
            "law": "lru-effects", "symbol": f"{node.name}({', '.join(args)})",
            "file": f"{path}:{node.lineno}",
            "detail": "мемоизация с аргументами, но тело читает "
                      + ", ".join(sorted(set(finder.hits)))
                      + ": кэш замораживает первое значение",
            "hot": True,
        })
    return out


def analyse_z3_arith(src: str, path: str) -> list:
    """Ствол z3-arith: настоящая модель BitVec(32) для двух классических бомб.

    1) `a * b / gcd(...)` — произведение до деления;
    2) `(low + high) / 2` на знаковых — переполнение суммы.
    Контрпример ищет Z3 (SAT), а не регулярка; без z3 модуль честно молчит.
    """
    try:
        import z3
    except ImportError:
        return []
    if not path.endswith((".c", ".h", ".rs")):
        return []
    lowered = path.lower()
    if "cfg(test)" in src or "/tests/" in f"/{lowered}" \
            or lowered.endswith(("tests.rs", "_test.rs")):
        return []
    if "/examples/" in lowered or "/testbed/" in lowered or "/stress_tests/" in lowered:
        return []

    out = []
    if re.search(r"\*\s*\w+\s*\)?\s*/\s*\(?\s*[\w:]*gcd", src):
        a, b, g = z3.BitVecs("a b g", 32)
        s = z3.Solver()
        s.add(g > 0, a % g == 0, b % g == 0)        # g — настоящий НОД
        # истинный НОК считаем в 64 битах: (a/g)*b помещается в int32
        lcm64 = (z3.ZeroExt(32, a) / z3.ZeroExt(32, g)) * z3.ZeroExt(32, b)
        s.add(lcm64 <= 2**31 - 1)
        # а машинное a*b (32 бита) уже переполнилось
        s.add(z3.SignExt(32, a) * z3.SignExt(32, b) > 2**31 - 1)
        if s.check() == z3.sat:
            m = s.model()
            out.append({
                "law": "z3-arith:lcm-mul", "symbol": f"{Path(path).name}:lcm",
                "file": path,
                "detail": "a*b переполняет int32 до деления: "
                          f"a={m[a]}, b={m[b]}, g={m[g]} — истинный НОК влезает",
                "hot": True,
            })
    # midpoint сообщаем только там, где это индекс в данных: нужен и контекст
    # поиска, и верхняя граница, выведенная из размера (len/size/count), а не
    # из литерала вроде `hi = 255` в пиксельном кодеке.
    search_ctx = re.search(
        r"binary_search|bsearch|lower_bound|upper_bound|partition_point"
        r"|\barr\[\s*mid\s*\]|\bmid\s*\]", src)
    data_bounds = re.search(
        r"\b(?:hi|high|right|end|last|top)\s*=\s*[^;\n]{0,60}"
        r"(?:\.len\s*\(|\.size\s*\(|\blen\b|\bsize\b|\bcount\b|\bn\b)", src)
    # ... и размер должен приходить извне (параметр функции) или из .len():
    # `hi = last - 1`, где last — константа таблицы, переполниться не может.
    size_param = re.search(r"\(\s*[^)]*\b(?:n|len|size|count|length|nmemb)\b[^)]*\)", src)
    runtime_len = re.search(r"\.len\s*\(\s*\)|strlen\s*\(|\.size\s*\(\s*\)", src)
    if search_ctx and data_bounds and (size_param or runtime_len) and \
            re.search(r"\(\s*\w+\s*\+\s*\w+\s*\)\s*(/\s*2|>>\s*1)", src):
        lo, hi = z3.BitVecs("lo hi", 32)
        s = z3.Solver()
        # легитимные границы: 0 <= lo, hi <= INT32_MAX
        s.add(lo >= 0, hi >= 0, lo <= 2**31 - 1, hi <= 2**31 - 1)
        # машинная сумма уходит в минус, хотя истинная середина влезает
        s.add(z3.SignExt(1, lo) + z3.SignExt(1, hi) > 2**31 - 1)
        if s.check() == z3.sat:
            m = s.model()
            out.append({
                "law": "z3-arith:midpoint", "symbol": f"{Path(path).name}:mid",
                "file": path,
                "detail": "low+high переполняет int32, хотя истинная середина влезает: "
                          f"lo={m[lo]}, hi={m[hi]}",
                "hot": True,
            })
    return out

def hunt(limit: int, min_stars: int, mode: str, max_age_days: int = 730, log=print) -> list:
    """Поиск -> фильтр -> скачивание файла -> анализ -> ранжирование."""
    seen, findings = set(), []
    queries = []
    if mode in ("laws", "all"):
        queries += [(q, "laws") for q in QUERIES_LAWS]
    if mode in ("effect-hints", "all"):
        queries += [(q, "effect-hints") for q in QUERIES_EFFECTS]
    if mode in ("lru-effects", "all"):
        queries += [(q, "lru") for q in QUERIES_LRU]
    if mode in ("z3-arith", "all"):
        queries += [(q, "z3arith") for q in QUERIES_ARITH]

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
            if repo_age_days(meta) > max_age_days:
                continue   # мёртвый архив: мейнтейнеров нет, время на сборку тратить нечего
            src = raw_file(repo, path)
            if not src:
                continue
            hits = {"laws": analyse_laws, "lru": analyse_lru,
                    "z3arith": analyse_z3_arith}.get(
                        stem, analyse_effects)(src, path)
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
    ok(len(QUERIES_LRU) >= 3 and len(QUERIES_ARITH) >= 3, "у новых стволов есть запросы")

    # --- ствол lru-effects: HIGH только при аргументах + часы/рандом ---
    bad_py = ("from functools import lru_cache\nimport random\n"
              "@lru_cache(maxsize=128)\n"
              "def pick(seed: int) -> float:\n"
              "    return random.random() + seed\n")
    h = analyse_lru(bad_py, "app/cache.py")
    ok(len(h) == 1 and h[0]["law"] == "lru-effects", "lru: аргументы + random -> находка")
    ok('pick(seed)' in h[0]["symbol"] if h else False, "lru: символ назван с аргументом")

    ok_allowed = ("from functools import lru_cache\nimport os\n"
                  "@lru_cache\ndef get_settings():\n    return os.environ.copy()\n")
    ok(analyse_lru(ok_allowed, "app/conf.py") == [], "lru: 0-аргументный синглтон молчит")

    pure = ("from functools import lru_cache\n"
            "@lru_cache(maxsize=None)\ndef fib(n: int) -> int:\n    return n if n < 2 else fib(n-1) + fib(n-2)\n")
    ok(analyse_lru(pure, "app/fib.py") == [], "lru: чистая мемоизация молчит")
    ok(analyse_lru(bad_py, "tests/test_cache.py") == [], "lru: тестовые файлы пропущены")

    # Калибровка №6: докстринг и вложенный def — не тело функции
    scipy_style = ('from functools import lru_cache\nimport time\n'
                   '@lru_cache(maxsize=8)\n'
                   'def _eps_for_method(x0_dtype, f0_dtype, method):\n'
                   '    """Docs used to say: never call time.time() in here."""\n'
                   '    def inner():\n'
                   '        return time.time()\n'
                   '    return _lookup(x0_dtype, f0_dtype, method)\n')
    ok(analyse_lru(scipy_style, "scipy/special/_basic.py") == [],
       "lru: докстринг + вложенный def дают 0 находок (шум ast.dump убран)")

    lam = ('from functools import lru_cache\nimport time\n'
           '@lru_cache()\ndef f(a):\n    g = lambda: time.time()\n    return a\n')
    ok(analyse_lru(lam, "app/l.py") == [], "lru: lambda-тело не считается")

    nested_call = ('from functools import lru_cache\nimport time\n'
                   '@lru_cache()\ndef f(a):\n    return (time.time(), a)\n')
    ok(len(analyse_lru(nested_call, "app/t.py")) == 1, "lru: реальный вызов в теле ловится")

    # Броня CI: сломанный YAML не должен тихо убивать workflow_dispatch
    try:
        import yaml as _yaml
    except ImportError:                       # в голом CI pyyaml может отсутствовать
        _yaml = None
    if _yaml is not None:
        wf_dir = Path(__file__).resolve().parent.parent / ".github" / "workflows"
        broken, checked = [], 0
        for wf in sorted(wf_dir.glob("*.yml")):
            checked += 1
            try:
                _yaml.safe_load(wf.read_text(encoding="utf-8"))
            except Exception as exc:          # noqa: BLE001 — нужен любой сбой
                broken.append(f"{wf.name}: {exc}")
        ok(checked >= 3 and not broken,
           f"все .github/workflows/*.yml парсятся ({checked} файлов)"
           + ("" if not broken else " — " + "; ".join(broken)))
    else:
        print("[SKIP] pyyaml нет — проверка воркфлоу пропущена")

    # --- ствол z3-arith: настоящий Solver, эталон lcm даёт контрпример ---
    lcm_c = ("int lcm(int a, int b) {\n    return a * b / gcd(a, b);\n}\n")
    h = analyse_z3_arith(lcm_c, "src/math.c")
    ok(len(h) == 1 and h[0]["law"] == "z3-arith:lcm-mul", "z3: a*b/gcd даёт SAT-контрпример")
    ok(bool(h) and "a=" in h[0]["detail"], "z3: контрпример содержит числа модели")

    safe_c = ("int lcm(int a, int b) {\n    return (a / gcd(a, b)) * b;\n}\n")
    ok(analyse_z3_arith(safe_c, "src/math.c") == [], "z3: (a/gcd)*b -> находок нет")

    mid_c = ("int binary_search(int *arr, int n) {\n"
             "    int low = 0, high = n - 1;\n"
             "    while (low <= high) { int mid = (low + high) / 2;"
             " if (arr[mid] == 0) return mid; }\n"
             "    return -1;\n}\n")
    h = analyse_z3_arith(mid_c, "src/bsearch.c")
    ok(len(h) == 1 and h[0]["law"] == "z3-arith:midpoint", "z3: (low+high)/2 даёт контрпример")
    ok(analyse_z3_arith(mid_c, "src/bsearch.c") != [], "z3: повторный вызов стабилен")

    # Калибровка №7: тестовые пути и «среднее двух литералов» — не находка
    ok(analyse_z3_arith(mid_c, "src/tests.rs") == [], "z3: tests.rs отсекается")
    ok(analyse_z3_arith(mid_c, "tests/test_search.c") == [], "z3: tests/ отсекается")
    codec = ("int lj92_predict(int a, int b) {\n"
             "    return (a + b) / 2;\n}\n")
    ok(analyse_z3_arith(codec, "src/lj92.rs") == [],
       "z3: среднее без контекста поиска молчит")

    # границы из литерала, а не из размера данных — тоже не наш случай
    fixed_buf = ("int bsearch_lin(int *arr, int key) {\n"
                 "    int lo = 0, hi = 255;\n"
                 "    int mid = (lo + hi) / 2;\n"
                 "    return arr[mid];\n}\n")
    ok(analyse_z3_arith(fixed_buf, "src/fixed.c") == [],
       "z3: hi из литерала (фиксированный буфер) молчит")

    # radare2-стиль: настоящий бинарный поиск, но по статической таблице
    table_search = ("int is_printable(unsigned int c) {\n"
                    "    const int last = nonprintable_ranges_count;\n"
                    "    int low = 0;\n    int hi = last - 1;\n"
                    "    do { int mid = (low + hi) >> 1;\n"
                    "        if (c < nonprintable_ranges[mid].from) hi = mid - 1;\n"
                    "    } while (low <= hi);\n    return 1;\n}\n")
    ok(analyse_z3_arith(table_search, "src/utf8.c") == [],
       "z3: границы от константы таблицы молчат (форма radare2)")

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

    _REPO_CACHE.clear()
    _REPO_CACHE["a/b"] = {"stars": 1, "pushed_at": "2020-01-01T00:00:00Z"}
    ok(repo_meta("a/b") is _REPO_CACHE["a/b"], "repo_cache отдаёт закэшированный ответ")
    ok(repo_age_days({"pushed_at": "2020-01-01T00:00:00Z"}) > 730,
       "старый pushed_at отсекается (noria-подобные архивы)")
    ok(repo_age_days({}) == float("inf"), "без pushed_at считаем мёртвым")
    _REPO_CACHE.clear()

    print(f"[API-HUNT-SELFTEST] провалов: {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="бесклоновая разведка через открытые API")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--min-stars", type=int, default=100)
    ap.add_argument("--mode", default="all",
                    choices=["laws", "effect-hints", "lru-effects", "z3-arith", "all"])
    ap.add_argument("--max-age-days", type=int, default=730)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    findings = hunt(a.limit, a.min_stars, a.mode, a.max_age_days)
    print(render(findings) if not a.json
          else json.dumps(findings, ensure_ascii=False, indent=1))
    print(f"\nитого: {len(findings)} находок (mode={a.mode}, min-stars={a.min_stars})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


