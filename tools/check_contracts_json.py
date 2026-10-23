#!/usr/bin/env python3
"""KERN: проверка СТРУКТУРЫ JSON-отчёта контрактов (цель `make contracts-json`).

ЗАЧЕМ. Цель, которая просто печатает файл, ничего не проверяет: она не может
упасть. Здесь проверяется, что отчёт `--json` валиден, содержит функции с
ожидаемыми вердиктами (`PROVEN`, `CONTRACT_VIOLATED`, `VACUOUS`, `SKIP`),
контрпримером Z3 и подтверждением рантайма (`runtime_confirmed: true`), а
сводка `summary` сходится с набором функций.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VALID_VERDICTS = {"PROVEN", "CONTRACT_VIOLATED", "VACUOUS", "SKIP"}
SUMMARY_KEYS = {"proven", "violated", "vacuous", "skipped"}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "build/kern_contracts.json")
    if not path.is_file():
        print(f"[!] нет файла JSON: {path}")
        return 1
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"[!] JSON не разбирается: {e}")
        return 1
    problems = []
    if doc.get("tool") != "KERN":
        problems.append(f"tool != KERN ({doc.get('tool')!r})")
    if not isinstance(doc.get("version"), str) or not doc.get("version"):
        problems.append(f"некорректное поле version ({doc.get('version')!r})")
    files = doc.get("files")
    if not isinstance(files, list) or not files:
        problems.append("files пуст или не список — `--json` перестал собирать функции")
        print("[!] " + "; ".join(problems))
        return 1
    counts = {"PROVEN": 0, "CONTRACT_VIOLATED": 0, "VACUOUS": 0, "SKIP": 0}
    has_ce = False
    has_runtime_confirmed = False
    total_fn = 0
    for fi, fobj in enumerate(files):
        if not isinstance(fobj, dict) or not fobj.get("path"):
            problems.append(f"файл #{fi}: нет корректного поля path")
            continue
        funcs = fobj.get("functions")
        if not isinstance(funcs, list):
            problems.append(f"файл #{fi}: functions не список")
            continue
        for j, fn in enumerate(funcs):
            total_fn += 1
            if not isinstance(fn, dict):
                problems.append(f"файл #{fi}, функция #{j}: не объект")
                continue
            if not fn.get("name"):
                problems.append(f"файл #{fi}, функция #{j}: пустое name")
            line = fn.get("line")
            if not isinstance(line, int) or line < 1:
                problems.append(f"файл #{fi}, функция #{j}: некорректное line={line!r}")
            v = fn.get("verdict")
            if v not in VALID_VERDICTS:
                problems.append(f"файл #{fi}, функция #{j}: неизвестный verdict {v!r}")
            else:
                counts[v] += 1
            if v == "CONTRACT_VIOLATED":
                ce = fn.get("counterexample")
                if isinstance(ce, dict) and ce:
                    has_ce = True
                if fn.get("runtime_confirmed") is True:
                    has_runtime_confirmed = True
    if total_fn == 0:
        problems.append("нет ни одной функции в files[].functions")
    if counts["PROVEN"] == 0:
        problems.append("нет ни одного вердикта PROVEN")
    if counts["CONTRACT_VIOLATED"] == 0:
        problems.append("нет ни одного вердикта CONTRACT_VIOLATED — нарушения потеряны")
    if not has_ce:
        problems.append("у CONTRACT_VIOLATED отсутствует непустой counterexample")
    if not has_runtime_confirmed:
        problems.append("нет подтверждения рантаймом (runtime_confirmed: true)")
    summary = doc.get("summary")
    if not isinstance(summary, dict):
        problems.append("нет объекта summary")
    else:
        missing_k = SUMMARY_KEYS - set(summary.keys())
        if missing_k:
            problems.append(f"в summary нет ключей: {sorted(missing_k)}")
        expected_summary = {
            "proven": counts["PROVEN"],
            "violated": counts["CONTRACT_VIOLATED"],
            "vacuous": counts["VACUOUS"],
            "skipped": counts["SKIP"],
        }
        for k, want in expected_summary.items():
            if summary.get(k) != want:
                problems.append(f"summary.{k} = {summary.get(k)!r}, а по функциям {want}")
    if problems:
        print("[!] JSON-ОТЧЁТ КОНТРАКТОВ НЕВАЛИДЕН:")
        for p in problems:
            print(f"      - {p}")
        return 1
    print(f"[OK] JSON-отчёт контрактов валиден: файлов {len(files)}, "
          f"функций {total_fn} (proven={counts['PROVEN']}, "
          f"violated={counts['CONTRACT_VIOLATED']}, "
          f"vacuous={counts['VACUOUS']}, skipped={counts['SKIP']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
