#!/usr/bin/env python3
"""KERN: проверка СТРУКТУРЫ SARIF-отчёта (цель `make sarif-check`).

ЗАЧЕМ. Цель, которая просто печатает файл, ничего не проверяет: она не может
упасть. Здесь проверяется, что отчёт — ВАЛИДНЫЙ SARIF 2.1.0 и что в нём ЕСТЬ
находки с точными координатами (`region.startLine`). Если находок нет, цель
падает: значит `--sarif` перестал замечать нарушения.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_RULES = {"KERN001", "KERN002", "KERN003", "KERN004"}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/kern.sarif")
    if not path.is_file():
        print(f"[!] нет файла SARIF: {path}")
        return 1
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"[!] SARIF не разбирается как JSON: {e}")
        return 1
    problems = []
    if doc.get("version") != "2.1.0":
        problems.append(f"version != 2.1.0 ({doc.get('version')!r})")
    if "$schema" not in doc:
        problems.append("нет $schema")
    runs = doc.get("runs") or []
    if len(runs) != 1:
        problems.append(f"runs: ожидался 1, получено {len(runs)}")
        print("[!] " + "; ".join(problems))
        return 1
    drv = runs[0].get("tool", {}).get("driver", {})
    if drv.get("name") != "KERN":
        problems.append(f"tool.driver.name != KERN ({drv.get('name')!r})")
    ids = {r.get("id") for r in drv.get("rules", [])}
    missing = REQUIRED_RULES - ids
    if missing:
        problems.append(f"нет правил: {sorted(missing)}")
    results = runs[0].get("results") or []
    if not results:
        problems.append("нет ни одной находки — `--sarif` перестал замечать нарушения")
    for i, r in enumerate(results):
        if r.get("ruleId") not in REQUIRED_RULES:
            problems.append(f"результат #{i}: неизвестный ruleId {r.get('ruleId')!r}")
        if r.get("level") != "error":
            problems.append(f"результат #{i}: level != error")
        if not (r.get("message") or {}).get("text"):
            problems.append(f"результат #{i}: пустое message.text")
        locs = r.get("locations") or []
        if not locs:
            problems.append(f"результат #{i}: нет locations")
            continue
        phys = locs[0].get("physicalLocation", {})
        if not (phys.get("artifactLocation") or {}).get("uri"):
            problems.append(f"результат #{i}: нет artifactLocation.uri")
        line = (phys.get("region") or {}).get("startLine")
        if not isinstance(line, int) or line < 1:
            problems.append(f"результат #{i}: нет корректного region.startLine")
    if problems:
        print("[!] SARIF НЕВАЛИДЕН:")
        for p in problems:
            print(f"      - {p}")
        return 1
    print(f"[OK] SARIF 2.1.0 валиден: {len(results)} находок, "
          f"{len(ids)} правил, координаты (uri + startLine) на месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())
