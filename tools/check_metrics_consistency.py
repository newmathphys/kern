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
    # ШАГ C: `docs/README.md` — карта документации — не входил в SURFACES, и в
    # нём выжили «174 кейса» / «реестр 191 цель» (факт 175 / 194). Класс #230:
    # страж не читает файл — значит устаревшее число там невидимо. Заметил это
    # `claims-audit`, который сканирует ВСЕ отслеживаемые файлы, а `--fix` у
    # стража починить не мог, потому что файла в списке не было.
    "docs/README.md",
    "docs/STATUS.md",
    "docs/STATUS.ru.md",
    # ШАГ F3 (#333): эти два файла тоже обещали «402 теста» и НЕ входили в
    # SURFACES — их нашёл `claims-audit` (он сканирует все отслеживаемые файлы),
    # а `--fix` у стража починить не мог. Класс #230.
    ".github/copilot-instructions.md",
    "formal/certification/SECURITY_TARGET.md",
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


def fact_quixbugs_explored() -> int | None:
    """Число задач QuixBugs в статусе EXPLORED (из лога Ступени 2).

    Дефект #239: на сайте жило «12 tasks: no divergence found», хотя финальный
    лог говорит EXPLORED 7. Число берётся из лога, а не из текста.
    """
    p = EV / "quixbugs_full.log"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^  EXPLORED\s+(\d+)\s*$", text, re.M)   # итоговая строка, не «EXPLORED 5 lines=…»
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s+tasks?:\s*no divergence", text)
    if m:
        return int(m.group(1))
    # ДЕФЕКТ #284: когда EXPLORED = 0, итоговой строки «EXPLORED  0» в логе
    # НЕТ (её печатают только при > 0), функция возвращала None — и правила
    # «N tasks: no divergence» вместе с ними ПОЛНОСТЬЮ ОТКЛЮЧАЛИСЬ. То есть
    # ровно та устаревшая фраза, ради которой правило писалось, перестала
    # проверяться. Выводим число из итога: total - diverged.
    total_m = re.search(r"DIVERGED[^\n]*?:\s*(\d+)\s*/\s*(\d+)", text)
    div_m = re.search(r"^  DIVERGED\s+(\d+)\s*$", text, re.M)
    if total_m and div_m:
        return max(0, int(total_m.group(2)) - int(div_m.group(1)))
    return None


def fact_quixbugs_differential() -> int | None:
    """Число задач QuixBugs, где расхождение подтверждено живым вызовом.

    Дефект #311: сводная таблица `docs/CAPABILITIES.md` обещала 33/40 при
    фактических 40/40 — форма `N/40` не покрывалась ни одним правилом.
    """
    p = EV / "quixbugs_full.log"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^\s*DIVERGED\s+(\d+)\s*$", text, re.M)
    return int(m.group(1)) if m else None


def fact_canfail_anchors() -> int | None:
    """Число литеральных якорей can-fail (источник — сам харнесс, не текст)."""
    try:
        out = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "canfail.py"), "--check-anchors"],
            cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or "") + (out.stderr or "")
    m = re.search(r"(\d+)\s+литеральн", text)
    if not m:
        m = re.search(r"all\s+(\d+)\s+literal anchors", text)
    return int(m.group(1)) if m else None


def _rules(core: int, nxt: int, cat: int, checks: int, cases: int, sites: int,
           targets: int, reg_targets: int, explored: int | None, anchors: int | None,
           qb_diff: int | None = None):
    """(регулярка, ожидаемое значение, метка[, контекст]). Все числовые группы обязаны совпасть."""
    rules = [
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
        (r"(\d+)\s+sites\b", sites, "сайты мутации", ("mutation", "mutant", "mutate", "mutator")),
        # Контекст обязателен: «51 сайт — фикция» в описании дефекта #131 — это
        # история конкретного бага, а не обещание текущего пула сайтов.
        (r"(\d+)\s+сайт(?:ов|а)?\b", sites, "сайты мутации",
         ("мутац", "mutation", "mutant", "mutate", "мутатор")),
        (r"(\d+)\s+(?:files|файл(?:ов|а)?)\b", targets, "файлы мутации", ("mutation", "mutant", "сайт")),
        # --- Дефект #239: ТАБЛИЧНЫЕ ФОРМЫ. Число стоит ПОСЛЕ метки в ячейке,
        # поэтому правила «N CHECK» и «N кейсов» их не видели. Именно так
        # прожили 125/125, 141 и 151 в README.ru.md при фактах 128/144/153.
        # Только UPPERCASE `CHECK` и только в контексте харнесса: иначе
        # `check.py`, `check Z3 ↔ cvc5 | 9/9` и `33/40` дают ложные тревоги.
        (r"(?-i:CHECK)[^|\n]{0,90}\|\s*\**\s*(\d+)\s*/\s*(\d+)", checks,
         "CHECK-цели", ("доказательств", "can-fail", "вакуум", "харнесс", "targets")),
        (r"can-fail\s+кейс(?:ов|а)?\s*\|\s*(\d+)", cases, "кейсы can-fail",
         ("can-fail",)),
        (r"кейс(?:ов|а)?\s*\|\s*(\d+)\s*\(не-вакуумных\s*(\d+)", cases,
         "кейсы can-fail", ("не-вакуумных",)),
        (r"целей\s+всего\s*\|\s*(\d+)", reg_targets, "цели реестра", ("целей",)),
        (r"\(CHECK\s+(\d+)", checks, "CHECK-цели", ("доказательств", "вакуум", "цел")),
        (r"can-fail\s*\((\d+)\s+goals?\)", checks, "CHECK-цели"),
        (r"(\d+)\s+can-fail\s+goals?", checks, "CHECK-цели"),
        (r"реестр[^|\n]{0,20}?(\d+)\s+цел", reg_targets, "цели реестра", ("реестр",)),
        # --- Дефект #311: «N / N killed» и «N / N убито» — форма записи
        # мутационного счёта на витрине. Правила «N sites» её не видели, поэтому
        # рядом с уже синхронизированным якорем 1361 жило старое 1345.
        (r"(\d+)\s*/\s*(\d+)\s+killed", sites, "сайты мутации",
         ("mutation", "mutant", "mutate")),
        (r"(\d+)\s*/\s*(\d+)\s+убито", sites, "сайты мутации", ("мутац", "мутант")),
        # «128 CHECK-целей can-fail» — форма без «/», правило «N/N CHECK-цел» её
        # не ловило.
        (r"(\d+)\s+CHECK-цел", checks, "CHECK-цели"),
    ]
    if qb_diff is not None:
        rules += [
            # `N/40` — форма записи Ступени 2 (живой differential). Ступень 1
            # (`6/40 SMT`) — ДРУГАЯ метрика, поэтому исключается отдельной
            # проверкой ниже (lookahead не годится: между числом и словом
            # «SMT» стоит ещё и «formal»).
            (r"(\d+)\s*/\s*40\b", qb_diff, "QuixBugs differential",
             ("quixbugs", "quix", "багов", "исполнением")),
        ]
    if explored is not None:
        rules += [
            (r"(\d+)\s+tasks?:\s*no divergence", explored, "QuixBugs EXPLORED"),
            (r"(\d+)\s+задач[а-я]*\s+без\s+найденного", explored, "QuixBugs EXPLORED"),
        ]
    if anchors is not None:
        rules += [
            (r"(\d+)\s+literal anchors", anchors, "якоря can-fail", ("anchor",)),
            (r"(\d+)\s+якор(?:ей|я)?\b", anchors, "якоря can-fail", ("якор",)),
        ]
    return tuple(rules)


# Это история, а не текущее обещание: «снимок 2026-10-14», «snapshot», «было 279».
HISTORY_MARKERS = ("снимок", "snapshot", "истори", "history", "было", "был ",
                   "ранее", "previous", "formerly", "раньше", "earlier",
                   "symptom", "before:", "used to", "раньше ")


# Окно, в котором ищутся исторические маркеры вокруг КОНКРЕТНОГО числа.
# ДЕФЕКТ #311: раньше история определялась по всей строке. Одно слово
# («earlier») в 4000-символьной строке README отключало проверку ВСЕХ чисел
# на ней — включая живое «1345 sites» рядом с уже синхронизированным
# «1361 / 1361». Так устаревшее число прожило рядом со своим исправленным
# близнецом: страж видел одно и не видел другого.
#
# Окно АСИММЕТРИЧНОЕ: историческая рамка («Symptom:», «было», «Раньше») стоит
# ПЕРЕД числом, а слово-хвост («earlier» в «…so the earlier dip was wider»)
# стоит ПОСЛЕ и к данному числу не относится. Поэтому слева 200, справа 40:
# этого достаточно, чтобы не задеть историю, и мало, чтобы спрятать живое
# число за словом из соседнего предложения.
HISTORY_BEFORE = 200
HISTORY_AFTER = 40


# Очередь точечных правок для `--fix`: (файл, строка, обещано, факт).
_FIX_QUEUE: list[tuple[str, int, int, int]] = []


def violations_in_line(rel: str, lineno: int, line: str, rules) -> list[str]:
    """Все нарушения в одной строке. Вынесено из main(), чтобы мета-тест
    проверял РОВНО ту же логику, которая работает в CI (иначе тест фиктивен)."""
    low = line.lower()
    # `canfail --only <target>` печатает счётчик ОДНОЙ цели: это не агрегат.
    if "--only" in low:
        return []
    # Строка журнала дефектов — датированная запись, а не текущее обещание.
    # ДЕФЕКТ #311: правило применялось к ЛЮБОМУ файлу, поэтому строка сводной
    # таблицы `| 1 | Поиск багов (QuixBugs) | **33/40** |` в CAPABILITIES.md
    # молча выпадала из проверки — и 33/40 жило рядом с 40/40.
    # Теперь: строки с НОМЕРОМ ДЕФЕКТА (`| **#131** | …`) пропускаются везде,
    # а строки вида `| 1 | …` — только в самом журнале дефектов.
    if re.match(r"^\| (?:\*\*)?#\d+(?:\*\*)? \|", line) or (
            Path(rel).name.startswith("CAPABILITY_STATUS")
            and re.match(r"^\| (?:\*\*)?\d+(?:\*\*)? \|", line)):
        return []
    scanned = line
    if rel.startswith("docs/RELEASE_NOTES") and line.startswith("|") \
            and line.count("|") >= 4:
        scanned = line.rstrip().rstrip("|").rsplit("|", 1)[-1]
    out: list[str] = []
    for rule in rules:
        pattern, expect, label = rule[0], rule[1], rule[2]
        need = rule[3] if len(rule) > 3 else ()
        if need and not any(x in low for x in need):
            continue
        for m in re.finditer(pattern, scanned, re.IGNORECASE):
            if label == "файлы мутации" and "lean" in low[max(0, m.start() - 60):m.start()]:
                continue
            # Ступень 1 (`6/40 SMT`, «формальный SMT», «Stage 1») — отдельная
            # метрика: её число не обязано равняться differential.
            if label == "QuixBugs differential" and re.search(
                    r"SMT|Ступень|Stage", scanned[m.end():m.end() + 40], re.IGNORECASE):
                continue
            # История — по ОКНУ вокруг числа, а не по всей строке (дефект #311).
            if any(mk in low[max(0, m.start() - HISTORY_BEFORE):m.end() + HISTORY_AFTER]
                   for mk in HISTORY_MARKERS):
                continue
            for g in (g for g in m.groups() if g is not None):
                if int(g) != expect:
                    _FIX_QUEUE.append((rel, lineno, int(g), expect))
                    out.append(f"{rel}:{lineno}  {label}: «{m.group(0).strip()}» "
                               f"→ обещано {g}, факт {expect}")
    return out


HISTORY_SKIP = ("docs/RELEASE_NOTES_", "RELEASE_NOTES_", "CHANGELOG.md",
                "docs/archive/")


def is_history(rel: str) -> bool:
    """Исторические документы описывают ПРОШЛЫЙ релиз и не обязаны совпадать
    с текущими числами. Их правка была бы переписыванием истории."""
    return any(rel.startswith(pfx) or Path(rel).name.startswith(pfx)
               for pfx in HISTORY_SKIP)


def apply_fix() -> int:
    """Точечная правка: на КАЖДОЙ указанной строке заменить только те числа,
    которые страж признал устаревшими (а не все числа файла)."""
    by_file: dict[str, dict[int, list[tuple[int, int]]]] = {}
    for rel, lineno, exp, act in _FIX_QUEUE:
        by_file.setdefault(rel, {}).setdefault(lineno, []).append((exp, act))
    total = 0
    for rel, lines in by_file.items():
        path = ROOT / rel
        src = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        for lineno, pairs in lines.items():
            if not (1 <= lineno <= len(src)):
                continue
            line = src[lineno - 1]
            for exp, act in pairs:
                new_line = re.sub(rf"(?<!\d){exp}(?!\d)", str(act), line)
                if new_line != line:
                    total += 1
                    line = new_line
            src[lineno - 1] = line
        path.write_text("".join(src), encoding="utf-8")
    return total


def selftest() -> int:
    """Мета-тест стража: подсадки ОБЯЗАНЫ ловиться, история — НЕ трогаться.

    Дефект #239: страж трижды оказывался слепым (#220/#223/#229/#230).
    Поэтому проверка проверяющего стала обязательной: 5 форматов подсадок,
    4 чистые строки, 3 исторические.
    """
    rules = _rules(401, 53, 425, 128, 144, 1345, 21, 154, 7, 119, 40)
    stale = [
        ("README.ru.md", 596, "| **CHECK с доказательством «может упасть»** | **125/125 (100 %)** |"),
        ("README.ru.md", 598, "| can-fail кейсов | 141 (не-вакуумных 141 · вакуумных 0 · ошибок кейсов 0) |"),
        ("README.ru.md", 595, "| Целей всего | 151 (CHECK 126 · MEASURE 1 · BUILD 6 · EXTERNAL 3 · META 15) |"),
        ("docs/index.html", 732, "<td>divergences confirmed; 12 tasks: no divergence found.</td>"),
        ("README.md", 544, "pre-flight (all 108 literal anchors verified in ~1 s)"),
        # ДЕФЕКТ #311: формы, которые не покрывал ни один правило — «N/N killed»,
        # «N sites» рядом с синхронизированным якорем, «N CHECK-целей», «N/40».
        ("README.md", 622, "| Mutation score | 100.0 % (1225 / 1225 killed) over 21 files / 1152 sites. Full sweep: 1225 / 1225 killed |"),
        ("docs/CAPABILITIES.md", 252, "| 1 | Поиск багов (QuixBugs) | ⚠️ **33/40**, но **исполнением** |"),
        ("docs/CYBERNETIC_VISION.md", 59, "* 401 теста ядра, 125 CHECK-целей can-fail |"),
        # История определяется ОКНОМ: «earlier»/«used to» стоят ПОСЛЕ числа и к
        # нему не относятся — живое «1152 sites» обязано быть поймано.
        ("README.md", 622, "over 21 files / 1152 sites. **Canonical gate**: 40/40 — same verdicts. The mutator used to cover only 6 files / 63 sites, so the earlier dip was wider |"),
    ]
    clean = [
        ("README.ru.md", 596, "| **CHECK с доказательством «может упасть»** | **128/128 (100 %)** |"),
        ("README.ru.md", 598, "| can-fail кейсов | 144 (не-вакуумных 144 · вакуумных 0 · ошибок кейсов 0) |"),
        ("README.ru.md", 595, "| Целей всего | 154 (CHECK 128 · MEASURE 1 · BUILD 6 · EXTERNAL 3 · META 16) |"),
        ("docs/index.html", 732, "<td>divergences confirmed; 7 tasks: no divergence found.</td>"),
        ("README.md", 544, "pre-flight (all 119 literal anchors verified in ~1 s)"),
        ("README.md", 622, "| Mutation score | 100.0 % (1345 / 1345 killed) over 21 files / 1345 sites. Full sweep: 1345 / 1345 killed |"),
        ("docs/CAPABILITIES.md", 252, "| 1 | Поиск багов (QuixBugs) | ⚠️ **40/40**, но **исполнением** |"),
        ("docs/CYBERNETIC_VISION.md", 59, "* 401 теста ядра, 128 CHECK-целей can-fail |"),
    ]
    history = [
        ("docs/CAPABILITY_STATUS.md", 1, "| **125** | дефект: историческая запись |"),
        ("docs/CAPABILITY_STATUS.md", 2, "| **141** | дефект: историческая запись |"),
        ("README.ru.md", 3, "| Сигнальный флуд | 1441 запуск |"),
        # Окно: историческая рамка ПЕРЕД числом — не трогаем (это симптом
        # старого дефекта, а не обещание текущего пула сайтов).
        ("docs/index.html", 545, "<p><em>Symptom:</em> \"mutation coverage over 14 files\" — but <code>proof_check.zig</code> holds 266 of the 420 sites |"),
    ]
    bad = 0
    for rel, ln, line in stale:
        if not violations_in_line(rel, ln, line, rules):
            _fail(f"selftest: ПРОПУЩЕНА подсадка {rel}:{ln}: {line[:70]}")
            bad += 1
    for rel, ln, line in clean:
        hits = violations_in_line(rel, ln, line, rules)
        if hits:
            _fail(f"selftest: ЛОЖНАЯ ТРЕВОГА {rel}:{ln}: {hits[0]}")
            bad += 1
    for rel, ln, line in history:
        hits = violations_in_line(rel, ln, line, rules)
        if hits:
            _fail(f"selftest: ИСТОРИЯ ЗАДЕТА {rel}:{ln}: {hits[0]}")
            bad += 1
    print(f"[{'OK' if bad == 0 else 'FAIL'}] metrics-guard selftest: "
          f"{len(stale)} подсадок, {len(clean)} чистых, {len(history)} исторических; "
          f"ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()

    core = fact_core_tests()
    nxt = fact_next_tests()
    cat = fact_catalog()
    reg = fact_registry()
    arch = fact_cross_arch()
    sites = fact_mutation_sites()
    tgt = fact_mutation_files()
    explored = fact_quixbugs_explored()
    anchors = fact_canfail_anchors()
    qb_diff = fact_quixbugs_differential()

    if core is None or nxt is None or cat is None or reg is None \
            or sites is None or tgt is None:
        _fail("не удалось получить факты (свидетельства/реестр/каталог) — проверка невозможна")
        return 1

    checks = reg.get("checks") or []
    cases = reg.get("canfail_cases") or []
    n_checks = len(checks) if isinstance(checks, list) else int(checks)
    n_cases = len(cases) if isinstance(cases, list) else int(cases)
    reg_targets = int(reg.get("targets", 0)) if isinstance(reg, dict) else 0
    if "--json" in args:
        print(json.dumps({
            "core_tests": core, "next_tests": nxt, "catalog": cat,
            "check_targets": n_checks, "canfail_cases": n_cases,
            "mutation_sites": sites, "mutation_files": tgt,
            "registry_targets": reg_targets, "meta_targets": len(reg.get("meta") or []) if isinstance(reg, dict) else 0,
            "build_targets": len(reg.get("builds") or []) if isinstance(reg, dict) else 0,
            "cross_arch_passed": arch[0] if arch else 0,
            "cross_arch_skipped": arch[1] if arch else 0,
            "quixbugs_explored": explored,
            "canfail_anchors": anchors,
            "cross_arch": arch, "max_defect": fact_max_defect(),
        }, ensure_ascii=False, indent=1))
        return 0

    tail = f" · QEMU {arch[0]}+{arch[1]}" if arch else ""
    print(f"ФАКТЫ: ядро {core} · next {nxt} · каталог {cat} · "
          f"CHECK {n_checks} · кейсов {n_cases} · сайтов {sites} в {tgt} файлах"
          f" · целей {reg_targets} · якорей {anchors if anchors is not None else '?'} "
          f"· QuixBugs EXPLORED {explored if explored is not None else '?'}{tail}")

    bad = 0

    # Кросс-архитектура обязана покрывать ВЕСЬ набор ядра (passed + skipped).
    if arch and arch[0] + arch[1] != core:
        _fail(f"cross_arch.log: {arch[0]}+{arch[1]}={arch[0] + arch[1]}, "
              f"а тестов ядра {core} — лог устарел")
        bad += 1

    rules = _rules(core, nxt, cat, n_checks, n_cases, sites, tgt if tgt else 0,
                   reg_targets, explored, anchors, qb_diff)
    for rel in SURFACES:
        if is_history(rel):
            continue
        p = ROOT / rel
        if not p.exists():
            continue
        for lineno, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            # ДЕФЕКТ #245: якорь `<!-- fact:key -->128` стоит МЕЖДУ знаком и
            # числом. Если правила читают сырую строку, число «прячется» за
            # комментарием и проверка становится ВАКУУМНОЙ — ровно то, против
            # чего она написана. Комментарии вырезаются перед разбором.
            scan = re.sub(r"<!--.*?-->", "", line)
            for msg in violations_in_line(rel, lineno, scan, rules):
                _fail(msg)
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
                scan = re.sub(r"<!--.*?-->", "", line)
                low = scan.lower()
                if any(mk in low for mk in HISTORY_MARKERS):
                    continue
                for m in re.finditer(r"#1[–-]#(\d{2,3})", scan):
                    if int(m.group(1)) != mx:
                        _fail(f"{rel}:{lineno}  диапазон реестра: «{m.group(0)}» "
                              f"→ обещано {m.group(1)}, факт #{mx}")
                        bad += 1

    if bad and "--fix" in args:
        n = apply_fix()
        print(f"\n[FIX] точечных правок: {n} — перезапустите проверку")
        return 0
    if bad:
        print(f"\n[FAIL] расхождений: {bad}")
        return 1
    print("[OK] числа тестов / каталога / CHECK / кейсов согласованы с фактами")
    return 0


if __name__ == "__main__":
    sys.exit(main())
