#!/usr/bin/env python3
"""ГЕЙТ ABI `--xray-json` (#483): СХЕМА СТАБИЛЬНА, ВЫВОД ЧИСТ, ВОРОНКА СХОДИТСЯ.

ЗАЧЕМ. Как только у аудита появляется машинный интерфейс, ломать его становится
ДОРОЖЕ, чем текст: любой потребитель (CI-плагин, MCP-сервер, обвязка на Go/Rust)
падает ЦЕЛИКОМ, а не «печатает некрасиво». Поэтому контракт проверяется
машинно, а не «на глаз»:

  1. в stdout РОВНО ОДИН объект JSON (человеческий лог не протекает — иначе
     `json.loads` падает у потребителя);
  2. есть `schema_version` и он равен ожидаемому (ломающее изменение = поднять);
  3. есть все обязательные ключи `summary`/`findings`/`skipped`/`notes`;
  4. `summary.findings == len(findings)` — иначе счётчик врёт;
  5. каждое `findings[i]` имеет `file`/`type`/`details`, `type` непустой;
  6. ТОЖДЕСТВО ВОРОНКИ: `checked + trivial + skipped == total`.

Невакуумность: валидатор обязан ОТКАЗАТЬ на каждом из шести нарушений —
проверяется здесь же (`--selftest`), на синтетических документах.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"
FIXTURE = ROOT / "tests" / "fixtures" / "precision_buggy"
EXPECTED_SCHEMA = "1.0"
REQUIRED_SUMMARY = ("files", "total", "checked", "trivial", "skipped",
                    "findings", "unreadable")


def validate(doc: dict) -> list[str]:
    """Проверить один документ ABI. Возвращает список нарушений."""
    bad: list[str] = []
    if not isinstance(doc, dict):
        return ["корень не объект JSON"]
    if doc.get("schema_version") != EXPECTED_SCHEMA:
        bad.append(f"schema_version {doc.get('schema_version')!r} != {EXPECTED_SCHEMA!r}")
    for key in ("summary", "findings", "skipped", "notes"):
        if key not in doc:
            bad.append(f"нет обязательного ключа `{key}`")
    sm = doc.get("summary")
    if not isinstance(sm, dict):
        return bad + ["`summary` не объект"]
    for key in REQUIRED_SUMMARY:
        if not isinstance(sm.get(key), int):
            bad.append(f"`summary.{key}` отсутствует или не целое")
    ff = doc.get("findings")
    if not isinstance(ff, list):
        return bad + ["`findings` не список"]
    if isinstance(sm.get("findings"), int) and sm["findings"] != len(ff):
        bad.append(f"summary.findings {sm['findings']} != len(findings) {len(ff)}")
    for i, f in enumerate(ff):
        if not isinstance(f, dict):
            bad.append(f"findings[{i}] не объект")
            continue
        for key in ("file", "type", "details"):
            if key not in f:
                bad.append(f"findings[{i}] без `{key}`")
        if not str(f.get("type", "")).strip():
            bad.append(f"findings[{i}].type пуст")
    if all(isinstance(sm.get(k), int) for k in ("total", "checked", "trivial", "skipped")):
        s = sm["checked"] + sm["trivial"] + sm["skipped"]
        if s != sm["total"]:
            bad.append(f"воронка не сходится: {sm['checked']}+{sm['trivial']}+"
                       f"{sm['skipped']}={s} != total {sm['total']}")
    return bad


def run_abi() -> tuple[int, str]:
    p = subprocess.run([PY, str(EXTRACTOR), "--xray", str(FIXTURE), "--xray-json"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout or ""


def _selftest() -> int:
    good = {"schema_version": EXPECTED_SCHEMA, "audit_target": "x",
            "summary": {"files": 1, "total": 2, "checked": 2, "trivial": 0,
                        "skipped": 0, "findings": 1, "unreadable": 0},
            "findings": [{"file": "a.py", "type": "CRASH PATH", "details": "d"}],
            "skipped": [], "notes": []}
    fails = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}{(': ' + detail) if detail else ''}")

    check("правильный документ принимается", not validate(good))
    import copy
    for name, mutate in (
            ("схема подменена", lambda d: d.update(schema_version="0.9")),
            ("пропал ключ notes", lambda d: d.pop("notes")),
            ("счётчик находок врёт", lambda d: d["summary"].update(findings=5)),
            ("воронка не сходится", lambda d: d["summary"].update(total=99)),
            ("находка без type", lambda d: d["findings"].append({"file": "a", "details": "d"})),
            ("summary не объект", lambda d: d.update(summary=[])),
    ):
        d = copy.deepcopy(good)
        mutate(d)
        check(f"поломка «{name}» ловится", bool(validate(d)))
    print(f"[{'FAIL' if fails else 'OK'}] abi-check selftest: провалов {fails}")
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    rc, out = run_abi()
    if rc != 0:
        print(f"[FAIL] #483: `--xray-json` завершился с rc={rc}")
        print((out or "")[:400])
        return 1
    try:
        doc = json.loads(out)
    except json.JSONDecodeError as e:
        # Первая причина — «человеческий лог протёк в stdout».
        print(f"[FAIL] #483: stdout не является ОДНИМ объектом JSON: {e}")
        print(f"       первые 200 символов: {out[:200]!r}")
        return 1
    bad = validate(doc)
    for b in bad:
        print(f"[!] {b}")
    if bad:
        print(f"[FAIL] #483: нарушений ABI {len(bad)}")
        return 1
    sm = doc["summary"]
    print(f"[OK] #483: ABI {doc['schema_version']} — чистый JSON, воронка сходится "
          f"({sm['checked']}+{sm['trivial']}+{sm['skipped']}={sm['total']}), "
          f"находок {sm['findings']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
