#!/usr/bin/env python3
"""Удар 2: полиглотный аудит BigCode HumanEvalPack (Python / C++ / Rust).

Источник: `bigcode/humanevalpack` на Hugging Face. Файлы лежат в parquet, а
`pyarrow` в окружении нет, поэтому берём строки через публичный Datasets Server
(JSON, без авторизации и без зависимостей):
  /rows?dataset=bigcode/humanevalpack&config=<lang>&split=test

В каждой записи авторы уже дали пару: `canonical_solution` (эталон) и
`buggy_solution` (внесённый баг) + `bug_type`. Код написан НЕ нами.

Python: судим пару через `kern_contracts.py --diff-equiv` (альфа-нормализация,
QF_NIA, неявный None) и подтверждаем каждое расхождение физическим вызовом.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from run_gpt4o_hf_audit import (  # noqa: E402
    is_scalar, norm, run_diff, verify_physically)

API = ("https://datasets-server.huggingface.co/rows?dataset=bigcode%2Fhumanevalpack"
       "&config={lang}&split=test&offset={off}&length=100")
EVID = ROOT / "docs" / "evidence" / "polyglot_benchmarks.json"
EVID_DB = ROOT / "docs" / "evidence" / "debugbench.json"


def fetch(lang: str) -> list[dict]:
    rows: list[dict] = []
    off = 0
    while True:
        try:
            with urllib.request.urlopen(API.format(lang=lang, off=off), timeout=120) as r:
                d = json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            print(f"[!] {lang}: {type(e).__name__} на offset={off}")
            break
        chunk = [x["row"] for x in d.get("rows", [])]
        rows.extend(chunk)
        total = d.get("num_rows_total") or 0
        off += len(chunk)
        if not chunk or off >= total:
            break
    return rows


def full(decl: str, body: str) -> str:
    """`declaration` — шапка (def/сигнатура), тело идёт с отступом."""
    return (decl or "").rstrip() + "\n" + (body or "")


def strip_solution_class(code: str) -> tuple[str, str] | None:
    """`class Solution: def solve(self, x): ...` -> чистая функция `solve(x)`.

    ДЕФЕКТ/нужда (DebugBench): все задачи LeetCode обёрнуты в `class Solution`,
    и без снятия обёртки `--diff-equiv` уходит в «вне домена из-за class».
    Берём ПЕРВЫЙ метод, убираем `self` и аннотации, возвращаем (имя, исходник).
    """
    import ast as _ast
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return None
    cls = next((n for n in tree.body if isinstance(n, _ast.ClassDef)), None)
    if cls is None:
        fn = next((n for n in tree.body if isinstance(n, _ast.FunctionDef)), None)
        return (fn.name, code) if fn else None
    fn = next((n for n in cls.body if isinstance(n, _ast.FunctionDef)), None)
    if fn is None:
        return None
    fn.args.args = [a for a in fn.args.args if a.arg != "self"]
    for a in fn.args.args:
        a.annotation = None
    fn.returns = None
    fn.decorator_list = []
    mod = _ast.Module(body=[fn], type_ignores=[])
    _ast.fix_missing_locations(mod)
    try:
        return fn.name, _ast.unparse(mod) + "\n"
    except Exception:  # noqa: BLE001
        return None


def run_debugbench(path: Path, limit: int = 0) -> dict:
    """DebugBench: пары (solution, buggy_code) от GPT-4 на задачах LeetCode."""
    import collections
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = [r for r in data if str(r.get("language", "")).startswith("python")]
    if limit:
        rows = rows[:limit]
    res = []
    for r in rows:
        a = strip_solution_class(r.get("solution") or "")
        b = strip_solution_class(r.get("buggy_code") or "")
        if not a or not b or a[0] != b[0]:
            res.append({"slug": r.get("slug"), "category": r.get("category"),
                        "status": "OUT_OF_DOMAIN", "detail": "нет пары методов"})
            continue
        ref, cand = a[1], b[1]
        if not (is_scalar(ref) and is_scalar(cand)):
            res.append({"slug": r.get("slug"), "category": r.get("category"),
                        "status": "OUT_OF_DOMAIN", "detail": "списки/строки/циклы"})
            continue
        st, det = run_diff(ref, cand)
        conf, phys = False, ""
        if st == "DIVERGED":
            conf, phys = verify_physically(ref, cand, det)
            if not conf:
                st = "DIVERGED_UNCONFIRMED"
        res.append({"slug": r.get("slug"), "category": r.get("category"),
                    "status": st, "detail": det, "confirmed": conf, "physical": phys})
        if st == "DIVERGED":
            print(f"  {r.get('slug')}: {r.get('category')} -> DIVERGED", flush=True)
    cnt = collections.Counter(x["status"] for x in res)
    by_cat = collections.Counter(x["category"] for x in res if x["status"] == "DIVERGED")
    EVID.parent.mkdir(parents=True, exist_ok=True)
    EVID_DB.write_text(json.dumps({"source": "Rtian/DebugBench", "lang": "python3",
                                "checked": len(res), "counts": dict(cnt),
                                "by_category": dict(by_cat), "rows": res},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ИТОГ DebugBench: задач {len(res)} | DIVERGED (физподтверждено) {cnt.get('DIVERGED', 0)} | "
          f"неподтверждено {cnt.get('DIVERGED_UNCONFIRMED', 0)} | SKIP {cnt.get('SKIP', 0)} | "
          f"вне домена {cnt.get('OUT_OF_DOMAIN', 0)}")
    print("по категориям:", dict(by_cat))
    return {"counts": dict(cnt), "by_category": dict(by_cat)}


def main() -> int:
    lang = sys.argv[1] if len(sys.argv) > 1 else "python"
    if lang == "debugbench":
        run_debugbench(Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/kern_poly/db/eval.json"))
        return 0
    rows = fetch(lang)
    print(f"[i] {lang}: строк {len(rows)}")
    res = []
    for r in rows:
        ref = full(r.get("declaration", ""), r.get("canonical_solution", ""))
        cand = full(r.get("declaration", ""), r.get("buggy_solution", ""))
        st, det = run_diff(ref, cand)
        conf, phys = (False, "")
        if st == "DIVERGED":
            conf, phys = verify_physically(ref, cand, det)
            if not conf:
                st = "DIVERGED_UNCONFIRMED"
        res.append({"task_id": r.get("task_id"), "bug_type": r.get("bug_type"),
                    "status": st, "detail": det, "confirmed": conf, "physical": phys})
        if st.startswith("DIVERGED"):
            print(f"  {r.get('task_id')}: {r.get('bug_type')} -> {st}", flush=True)
    cnt = Counter(x["status"] for x in res)
    by_type = Counter(x["bug_type"] for x in res if x["status"] == "DIVERGED")
    EVID.parent.mkdir(parents=True, exist_ok=True)
    EVID.write_text(json.dumps({"source": "bigcode/humanevalpack", "lang": lang,
                                "checked": len(res), "counts": dict(cnt),
                                "by_bug_type": dict(by_type), "rows": res},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ИТОГ {lang}: задач {len(res)} | DIVERGED (физподтверждено) {cnt.get('DIVERGED', 0)} | "
          f"неподтверждено {cnt.get('DIVERGED_UNCONFIRMED', 0)} | SKIP {cnt.get('SKIP', 0)} | "
          f"вне домена {cnt.get('OUT_OF_DOMAIN', 0)}")
    print("по типам бага:", dict(by_type))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
