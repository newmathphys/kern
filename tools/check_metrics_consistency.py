#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Страж согласованности счётчиков (класс дефектов #220 / #223).

ЗАЧЕМ: витрина и паспорт обещают конкретные числа (тесты ядра, тесты KERN-Next,
каталог, CHECK-цели, кейсы can-fail, кросс-архитектура). Числа РАСТУТ при каждой
правке кода, а тексты обновляются руками — и отстают. Так уже случилось дважды:
#220 (в витрине 308/424 вместо 401/425) и #223 (на сайте «120 Lean 4 theorems»
при фактических 137).

ПРИНЦИП: источник истины — НЕ документ, а измеримое свидетельство:
  • тесты ядра        — `docs/evidence/core_tests.log` («All N tests passed»);
  • тесты KERN-Next   — `docs/evidence/kern_next_tests.log` («N/N tests passed»);
  • кросс-архитектура — `docs/evidence/cross_arch.log` («N passed; K skipped»),
                        причём N + K обязано равняться числу тестов ядра;
  • каталог тестов    — пересчёт генератора (`gen_test_catalog.collect()`);
  • CHECK-цели/кейсы  — `tools/registry.py --json`.

Проверяются только «плотные» утверждения (число рядом с единицей измерения),
а не любое число в тексте: иначе страж стал бы генератором ложных тревог.
Строки с пометкой «снимок» / «snapshot» / «история» пропускаются — это история.

Выход: 0 — согласовано; 1 — расхождение (печатается файл:строка).
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "docs" / "evidence"

# Публичные поверхности, где числа читает человек (и внешние сканеры).
SURFACES = (
    "README.md",
    "README.ru.md",
    "docs/index.html",
    "docs/ATTESTATION_PASSPORT.md",
    "docs/ATTESTATION_PASSPORT.en.md",
    "docs/PROJECT.md",
    "docs/PROJECT_SPECIFICATION.md",
    "docs/TEST_CATALOG.md",
)


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def fact_core_tests() -> int | None:
    p = EV / "core_tests.log"
    if not p.exists():
        return None
    m = re.search(r"All (\d+) tests passed", p.read_text(encoding="utf-8", errors="replace"))
    return int(m.group(1)) if m else None


def fact_next_tests() -> int | None:
    p = EV / "kern_next_tests.log"
    if not p.exists():
        return None
    m = re.search(r"(\d+)/(\d+) tests passed", p.read_text(encoding="utf-8", errors="replace"))
    if m and m.group(1) == m.group(2):
        return int(m.group(1))
    return None


def fact_cross_arch() -> tuple[int, int] | None:
    """(passed, skipped) из первого блока кросс-архитектуры."""
    p = EV / "cross_arch.log"
    if not p.exists():
        return None
    m = re.search(r"(\d+) passed; (\d+) skipped",
                  p.read_text(encoding="utf-8", errors="replace"))
    return (int(m.group(1)), int(m.group(2))) if m else None


def fact_catalog() -> int | None:
    """Число тестов считает сам генератор каталога (без записи файла)."""
    spec = importlib.util.spec_from_file_location("gtc", ROOT / "tools" / "gen_test_catalog.py")
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        buckets = mod.collect()  # {group: {relpath: [names]}}
        return sum(len(names) for group in buckets.values() for names in group.values())
    except (ImportError, OSError, AttributeError):
        return None


def fact_registry() -> dict | None:
    try:
        out = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "registry.py"), "--json"],
            cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
        )
        d = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return d if isinstance(d, dict) else None



def _rules(core: int, nxt: int, cat: int, checks: int, cases: int):
    """(регулярка, ожидаемое значение, метка). Все числовые группы обязаны совпасть."""
    return (
        (r"(\d+)\s+core tests", core, "тесты ядра"),
        (r"(\d+)\s*/\s*(\d+)\s+core tests", core, "тесты ядра"),
        (r"#\s*(\d+)\s+core tests", core, "тесты ядра"),
        (r"(\d+)\s+тест(?:ов|а)?\s+ядра", core, "тесты ядра"),
        (r"(\d+)\s/\s*(\d+)\s+тест(?:ов|а)?\s+ядра", core, "тесты ядра"),
        (r"(\d+)\s*/\s*(\d+)\s+tests passed", nxt, "KERN-Next"),
        (r"(\d+)\s+объявлени[йя]", cat, "каталог тестов"),
        (r"(\d+)\s+CHECK targets", checks, "CHECK-цели"),
        (r"(\d+)\s*/\s*(\d+)\s+CHECK-цел", checks, "CHECK-цели"),
        (r"(\d+)\s+fault-injection cases", cases, "кейсы can-fail"),
        (r"(\d+)\s+не-вакуумн", cases, "кейсы can-fail"),
        # «125 proven non-vacuous» = CHECK-цели; «141 non-vacuous» = кейсы.
        (r"(\d+)\s+proven\s+non-vacuous", checks, "CHECK-цели"),
        (r"(\d+)\s+non-vacuous(?:\s+cases)?", cases, "кейсы can-fail"),
        (r"(\d+)\s*/\s*(\d+)\s+can-fail", checks, "CHECK-цели"),
        (r"(\d+)\s+can-fail\s+targets", checks, "CHECK-цели"),
    )


# Это история, а не текущее обещание: «снимок 2026-10-14», «snapshot», «было 279».
HISTORY_MARKERS = ("снимок", "snapshot", "истори", "history", "было", "был ",
                   "ранее", "previous", "formerly")


def main() -> int:
    core = fact_core_tests()
    nxt = fact_next_tests()
    cat = fact_catalog()
    reg = fact_registry()
    arch = fact_cross_arch()

    if core is None or nxt is None or cat is None or reg is None:
        _fail("не удалось получить факты (свидетельства/реестр/каталог) — проверка невозможна")
        return 1

    checks = reg.get("checks") or []
    cases = reg.get("canfail_cases") or []
    n_checks = len(checks) if isinstance(checks, list) else int(checks)
    n_cases = len(cases) if isinstance(cases, list) else int(cases)
    tail = f" · QEMU {arch[0]}+{arch[1]}" if arch else ""
    print(f"ФАКТЫ: ядро {core} · next {nxt} · каталог {cat} · "
          f"CHECK {n_checks} · кейсов {n_cases}{tail}")

    bad = 0

    # Кросс-архитектура обязана покрывать ВЕСЬ набор ядра (passed + skipped).
    if arch and arch[0] + arch[1] != core:
        _fail(f"cross_arch.log: {arch[0]}+{arch[1]}={arch[0] + arch[1]}, "
              f"а тестов ядра {core} — лог устарел")
        bad += 1

    rules = _rules(core, nxt, cat, n_checks, n_cases)
    for rel in SURFACES:
        p = ROOT / rel
        if not p.exists():
            continue
        for lineno, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            low = line.lower()
            if any(mk in low for mk in HISTORY_MARKERS):
                continue
            for pattern, expect, label in rules:
                for m in re.finditer(pattern, line, re.IGNORECASE):
                    for g in (g for g in m.groups() if g is not None):
                        if int(g) != expect:
                            _fail(f"{rel}:{lineno}  {label}: «{m.group(0).strip()}» "
                                  f"→ обещано {g}, факт {expect}")
                            bad += 1

    if bad:
        print(f"\n[FAIL] расхождений: {bad}")
        return 1
    print("[OK] числа тестов / каталога / CHECK / кейсов согласованы с фактами")
    return 0


if __name__ == "__main__":
    sys.exit(main())
