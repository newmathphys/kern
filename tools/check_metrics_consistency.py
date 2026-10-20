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
    # Дефект #229: страж покрывал 8 файлов из ~20 публичных — и 7 расхождений
    # (#228) прожили несколько коммитов незамеченными. Ниже — остальные
    # документы, где читатель (и внешний сканер) видит те же числа.
    "docs/RELEASE_NOTES_v2.5.0.md",
    "docs/ROADMAP.md",
    "docs/ROADMAP.en.md",
    "docs/CAPABILITIES.md",
    "docs/CAPABILITIES.en.md",
    "docs/TESTING_AND_SPEED_GUIDE.md",
    "docs/TESTING_AND_SPEED_GUIDE.en.md",
    "docs/FIELD_AUDIT_REPORT.md",
    "docs/RULE_THEOREM_MATRIX.md",
    # Дефект #230: эти четыре файла страж НЕ читал, поэтому в них выжили
    # «1225 / 1225 сайтов» и «всех 20 файлов» (пул стал 1345 / 21).
    "docs/CAPABILITY_STATUS.md",
    "docs/CAPABILITY_STATUS.en.md",
    "docs/CYBERNETIC_VISION.md",
    "docs/CYBERNETIC_VISION.en.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
)

# CHANGELOG.md намеренно НЕ проверяется: это хронология выпусков, числа в ней
# относятся к моменту выпуска версии (запись про v2.4.0 и говорит «78/78 CHECK»
# — так и было), а не к текущему HEAD. Проверять там текущие значения значило бы
# требовать переписывания истории.


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


def _mutator():
    """Загружает `tools/mutate_zig.py` один раз (для пула сайтов и списка файлов)."""
    spec = importlib.util.spec_from_file_location("mz", ROOT / "tools" / "mutate_zig.py")
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except (ImportError, OSError, AttributeError):
        return None
    return mod


def fact_mutation_sites() -> int | None:
    """Пул сайтов мутации считает сам мутатор (`collect()` — 0.27 с, без сборки).

    Пул РАСТЁТ с каждой правкой ядра (было 1225, стало 1345), поэтому обещание
    «N/N sites» на витрине обязано сверяться с ним, а не застывать.
    """
    mod = _mutator()
    if mod is None:
        return None
    try:
        return len(mod.collect(str(ROOT)))
    except (OSError, AttributeError, TypeError):
        return None


def fact_mutation_files() -> int | None:
    """Число целевых файлов мутатора (`TARGETS`) — тоже растёт (было 20, стало 21)."""
    mod = _mutator()
    return len(mod.TARGETS) if mod is not None else None


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



def fact_max_defect() -> int | None:
    """Наибольший номер записи в журнале дефектов (для диапазона «#1–#N»).

    Дефект #231: витрина обещала `#1–#226`, а факт был #231 — класс повторился
    трижды (#178, #221, #231), потому что диапазон никто не сверял с журналом.
    """
    p = ROOT / "docs" / "CAPABILITY_STATUS.md"
    if not p.exists():
        return None
    nums = [int(m.group(1)) for m in re.finditer(
        r"^\| \*\*(\d+)\*\* \|", p.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)]
    return max(nums) if nums else None


def _rules(core: int, nxt: int, cat: int, checks: int, cases: int, sites: int, targets: int):
    """(регулярка, ожидаемое значение, метка). Все числовые группы обязаны совпасть."""
    return (
        (r"(\d+)\s+core tests", core, "тесты ядра"),
        (r"(\d+)\s*/\s*(\d+)\s+core tests", core, "тесты ядра"),
        (r"#\s*(\d+)\s+core tests", core, "тесты ядра"),
        (r"(\d+)\s+тест(?:ов|а)?\s+ядра", core, "тесты ядра"),
        # Дефект #229: табличный формат «| Тесты ядра | **299** |» ставит число
        # ПОСЛЕ метки, поэтому правило выше его не видело (README.ru.md:22).
        (r"тесты\s+ядра\s*\|[^\d\n]{0,24}(\d+)", core, "тесты ядра"),
        (r"core\s+tests\s*\|[^\d\n]{0,24}(\d+)", core, "тесты ядра"),
        (r"Тесты\s+KERN-Next\s*\|[^\d\n]{0,24}(\d+)", nxt, "KERN-Next"),
        (r"KERN-Next\s+tests\s*\|[^\d\n]{0,24}(\d+)", nxt, "KERN-Next"),
        (r"(\d+)\s/\s*(\d+)\s+тест(?:ов|а)?\s+ядра", core, "тесты ядра"),
        (r"(\d+)\s*/\s*(\d+)\s+tests passed", nxt, "KERN-Next"),
        (r"(\d+)\s+объявлени[йя]", cat, "каталог тестов"),
        # Дефект #230: «Всего объявлений тестов:** 425» — здесь число стоит ПОСЛЕ
        # метки. Правило «N объявлений» такие строки не видело вовсе, поэтому
        # подсадка «424» проходила незамеченной (страж был фиктивным).
        (r"объявлени[йя][^0-9\n]{0,24}(\d+)", cat, "каталог тестов"),
        (r"(\d+)\s+CHECK targets", checks, "CHECK-цели"),
        (r"(\d+)\s*/\s*(\d+)\s+CHECK-цел", checks, "CHECK-цели"),
        (r"(\d+)\s+fault-injection cases", cases, "кейсы can-fail"),
        (r"(\d+)\s+не-вакуумн", cases, "кейсы can-fail"),
        # «125 proven non-vacuous» = CHECK-цели; «141 non-vacuous» = кейсы.
        (r"(\d+)\s+proven\s+non-vacuous", checks, "CHECK-цели"),
        (r"(\d+)\s+non-vacuous(?:\s+cases)?", cases, "кейсы can-fail"),
        (r"(\d+)\s*/\s*(\d+)\s+can-fail", checks, "CHECK-цели"),
        (r"(\d+)\s+can-fail\s+targets", checks, "CHECK-цели"),
        # Контекстные правила: «82/82 CHECK», «95 cases», «142 кейса» ловятся
        # только там, где речь действительно о харнессе (иначе — ложные тревоги).
        (r"(\d+)\s*/\s*(\d+)\s+CHECK\b", checks, "CHECK-цели",
         ("can-fail", "check", "вакуум", "харнесс")),
        (r"(\d+)\s+cases\b", cases, "кейсы can-fail", ("canfail", "can-fail", "vacuous")),
        (r"(\d+)\s+кейс(?:ов|а)?\b", cases, "кейсы can-fail", ("вакуум", "canfail")),
        (r"(\d+)\s+sites\b", sites, "сайты мутации", ("mutation", "mutant", "mutate")),
        # Контекст обязателен: «51 сайт — фикция» в описании дефекта #131 — это
        # история конкретного бага, а не обещание текущего пула сайтов.
        (r"(\d+)\s+сайт(?:ов|а)?\b", sites, "сайты мутации",
         ("мутац", "mutation", "mutant", "mutate")),
        (r"(\d+)\s+(?:files|файл(?:ов|а)?)\b", targets, "файлы мутации", ("mutation", "mutant", "сайт")),
    )


# Это история, а не текущее обещание: «снимок 2026-10-14», «snapshot», «было 279».
HISTORY_MARKERS = ("снимок", "snapshot", "истори", "history", "было", "был ",
                   "ранее", "previous", "formerly", "раньше", "earlier",
                   "symptom", "before:")


def main() -> int:
    core = fact_core_tests()
    nxt = fact_next_tests()
    cat = fact_catalog()
    reg = fact_registry()
    arch = fact_cross_arch()
    sites = fact_mutation_sites()
    tgt = fact_mutation_files()

    if core is None or nxt is None or cat is None or reg is None \
            or sites is None or tgt is None:
        _fail("не удалось получить факты (свидетельства/реестр/каталог) — проверка невозможна")
        return 1

    checks = reg.get("checks") or []
    cases = reg.get("canfail_cases") or []
    n_checks = len(checks) if isinstance(checks, list) else int(checks)
    n_cases = len(cases) if isinstance(cases, list) else int(cases)
    tail = f" · QEMU {arch[0]}+{arch[1]}" if arch else ""
    print(f"ФАКТЫ: ядро {core} · next {nxt} · каталог {cat} · "
          f"CHECK {n_checks} · кейсов {n_cases} · сайтов {sites} в {tgt} файлах{tail}")

    bad = 0

    # Кросс-архитектура обязана покрывать ВЕСЬ набор ядра (passed + skipped).
    if arch and arch[0] + arch[1] != core:
        _fail(f"cross_arch.log: {arch[0]}+{arch[1]}={arch[0] + arch[1]}, "
              f"а тестов ядра {core} — лог устарел")
        bad += 1

    rules = _rules(core, nxt, cat, n_checks, n_cases, sites, tgt if tgt else 0)
    for rel in SURFACES:
        p = ROOT / rel
        if not p.exists():
            continue
        for lineno, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            low = line.lower()
            # `canfail --only <target>` печатает счётчик ОДНОЙ цели («1 non-vacuous»):
            # это не агрегатное обещание, а результат точечного прогона.
            if "--only" in low:
                continue
            # Строки РЕЕСТРА дефектов (`| **N** | ...` или `| N | ...`) — датированная
            # запись: число в ней описывает состояние НА МОМЕНТ фикса, а не текущее
            # обещание. Переписывать такую историю нельзя (тот же принцип, что и
            # «не перенумеровываем»), иначе журнал перестанет быть доказательством.
            if re.match(r"^\| (?:\*\*)?\d+(?:\*\*)? \|", line):
                continue
            # Docs/RELEASE_NOTES_v2.5.0.md — таблица «было | стало». Вторая
            # колонка это ИСТОРИЧЕСКИЙ baseline (v2.4.0), а не текущее обещание:
            # сверяем только ПОСЛЕДНЮЮ ячейку строки (дефект #230, ложная тревога).
            scanned = line
            if rel.startswith("docs/RELEASE_NOTES") and line.startswith("|") \
                    and line.count("|") >= 4:
                scanned = line.rstrip().rstrip("|").rsplit("|", 1)[-1]
            if any(mk in low for mk in HISTORY_MARKERS):
                continue
            for rule in rules:
                pattern, expect, label = rule[0], rule[1], rule[2]
                need = rule[3] if len(rule) > 3 else ()
                if need and not any(x in low for x in need):
                    continue  # контекст не тот — это не обещание счётчика
                for m in re.finditer(pattern, scanned, re.IGNORECASE):
                    # «Lean 4 **8 files** / 137 theorems» — это файлы Lean, не мутатора:
                    # в той же строке есть слово mutation, но обещание не о нём.
                    if label == "файлы мутации" and "lean" in low[max(0, m.start() - 60):m.start()]:
                        continue
                    for g in (g for g in m.groups() if g is not None):
                        if int(g) != expect:
                            _fail(f"{rel}:{lineno}  {label}: «{m.group(0).strip()}» "
                                  f"→ обещано {g}, факт {expect}")
                            bad += 1

    # Диапазон реестра на витрине обязан совпадать с фактическим максимумом.
    mx = fact_max_defect()
    if mx is not None:
        for rel in ("README.md", "README.ru.md", "docs/index.html", "docs/README.md"):
            p = ROOT / rel
            if not p.exists():
                continue
            for lineno, line in enumerate(
                    p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                low = line.lower()
                if any(mk in low for mk in HISTORY_MARKERS):
                    continue
                for m in re.finditer(r"#1[–-]#(\d{2,3})", line):
                    if int(m.group(1)) != mx:
                        _fail(f"{rel}:{lineno}  диапазон реестра: «{m.group(0)}» "
                              f"→ обещано {m.group(1)}, факт #{mx}")
                        bad += 1

    if bad:
        print(f"\n[FAIL] расхождений: {bad}")
        return 1
    print("[OK] числа тестов / каталога / CHECK / кейсов согласованы с фактами")
    return 0


if __name__ == "__main__":
    sys.exit(main())
