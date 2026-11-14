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

from run_gpt4o_hf_audit import run_diff, verify_physically, write_docs  # noqa: E402

API = ("https://datasets-server.huggingface.co/rows?dataset=bigcode%2Fhumanevalpack"
       "&config={lang}&split=test&offset={off}&length=100")
EVID = ROOT / "docs" / "evidence" / "polyglot_benchmarks.json"


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


def main() -> int:
    lang = sys.argv[1] if len(sys.argv) > 1 else "python"
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
