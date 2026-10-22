#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""KERN: аудит ЧИСЛОВЫХ УТВЕРЖДЕНИЙ в документации (шаг B плана v2.7.0).

ЗАЧЕМ ЭТОТ ИНСТРУМЕНТ, ЕСЛИ ЕСТЬ `metrics-guard`.

`check_metrics_consistency.py` проверяет СПИСОК ИЗВЕСТНЫХ поверхностей и
конкретные форматы. Дефект #320 показал границу такого подхода: утверждение,
для которого правила НЕТ, дрейфует молча. Шаг A2 нашёл руками «32 теоремы в
7 файлах» (факт — 143 в 8) и «SHA-256 по каждому payload» (дефолт — BLAKE3).

Этот скрипт делает то же СИСТЕМНО: сканирует ВСЕ отслеживаемые .md/.html по
набору шаблонов «число + единица измерения» и классифицирует каждое
вхождение: ANCHORED (рядом якорь), GUARDED (совпало с фактом), STALE
(НЕ совпало -> дефект), UNKNOWN (шаблон совпал, факта нет).

ИСТОРИЯ НЕ ПРАВИТСЯ: HISTORICAL-файлы, CHANGELOG, METRICS, CAPABILITY_STATUS и
archive/ пропускаются — их числа описывают прошлое.

Запуск: python3 tools/claims_audit.py [--json] [--list-naked]
Код возврата: 0 — расхождений нет; 1 — есть STALE.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "docs" / "facts.json"

SKIP_PREFIXES = ("docs/archive/",)
SKIP_FILES = {
    "CHANGELOG.md",
    "docs/METRICS.md", "docs/METRICS.en.md",
    "docs/CAPABILITY_STATUS.md", "docs/CAPABILITY_STATUS.en.md",
    "docs/PLAN_v2.5.3.md",
    "docs/RELEASE_NOTES_v2.5.0.md", "docs/RELEASE_NOTES_v2.5.1.md",
    "docs/RELEASE_NOTES_v2.5.1.en.md", "docs/RELEASE_NOTES_v2.5.2.md",
    "docs/RELEASE_NOTES_v2.5.2.en.md",
    "docs/VERIFICATION_0_17.md", "docs/KERN_FIXES_v1_3.md",
    "docs/MIGRATION_REPORT_0_17.md",
}

# (имя факта, ключ в facts.json, регулярка с ОДНОЙ группой-числом)
#
# ВАЖНО (измерено на первом прогоне): `re.I` на шаблоне CHECK давал ложные
# срабатывания на «4 checks, 3 counterexamples» (CEGIS), а шаблон «мутац»
# ловил хвост числа «1 000 000 мутаций» (группа пробелов). Поэтому:
#   * CHECK — ТОЛЬКО верхний регистр (это имя цели, а не слово «checks»);
#   * числа, входящие в группу «1 000», отбрасываются отдельной проверкой;
#   * строки журнала дефектов (`| **NN** |`) пропускаются: они описывают прошлое.
RULES = (
    # `(\d+)` + необязательное «Lean 4» перед словом: без этого «143 Lean 4
    # theorems» давало группу «4» (версия Lean), а не 143 (число теорем).
    ("теоремы Lean", "lean_theorems",
     re.compile(r"(\d+)\s*(?:Lean\s*)?(?:\d+\s*)?(?:теорем|theorems?)", re.I)),
    ("цели реестра", "registry_targets",
     re.compile(r"(\d+)\s*(?:цел(?:ей|и|ь)|targets?)\b", re.I)),
    ("CHECK-цели", "check_targets",
     re.compile(r"(\d+)\s*(?:CHECK\b|check[- ](?:targets?|цел))")),
    ("can-fail кейсы", "canfail_cases",
     re.compile(r"(\d+)\s*(?:кейс|non-vacuous)")),
    ("тесты ядра", "core_tests",
     re.compile(r"(\d+)\s*(?:тест(?:ов|а)?\s+ядра|core tests)")),
    ("мутации", "mutation_sites",
     re.compile(r"(\d+)\s*(?:мутац|mutants?)")),
)

ANCHOR_NEAR = re.compile(r"<!--\s*fact:([a-z0-9_.]+)\s*-->")

# Строка журнала дефектов: `| **123** | ...` — описывает ПРОШЛОЕ.
DEFECT_ROW = re.compile(r"^\s*\|\s*\*\*\d+\*\*\s*\|")


def _in_space_group(line: str, start: int) -> bool:
    """`1 000 000 мутаций`: совпал хвост «000». Признак — цифра через пробел слева."""
    if start == 0:
        return False
    return bool(re.search(r"\d[\s\u00a0]$", line[:start]))


# Утверждение о КОНКРЕТНОМ файле («KernSemanticGap.lean: 8 теорем») — не общее
# число проекта. Проверено на первом прогоне: 8 таких строк давали ложные STALE.
SPECIFIC_FILE = re.compile(r"`?[A-Za-z_]+\.lean`?")
# «25 mutants» / «over 14 files» — ПЕРИОД или доля, а не общее число.
PERIOD_WORD = re.compile(r"every|each|per\b|over\s+\d+\s+file|coverage", re.I)
# «снимок 2026-10-14: 75 целей» — ИСТОРИЧЕСКИЙ снимок, а не текущее обещание.
# «2 теоремы Lean были тавтологиями» / «40 — «Lean 50 теорем» одним блоком» —
# урок или ЦИТАТА дефекта в прошедшем времени.
HISTORY_WORD = re.compile(
    r"снимок|snapshot|\bбыли\b|\bбыл[аио]?\b|\bwas\b|\bwere\b|"
    r"^\s*\|\s*\d+\s*\||`--only|non-vacuous,\s*0", re.I)


def _is_claim_about_total(line: str, start: int) -> bool:
    """Отличить утверждение об ОБЩЕМ числе от числа конкретного файла/периода."""
    if SPECIFIC_FILE.search(line):
        return False
    if PERIOD_WORD.search(line):
        return False
    if HISTORY_WORD.search(line):
        return False
    # «Lean 4 theorems» / «Lean&nbsp;4 theorems»: «4» — ВЕРСИЯ Lean, а не число
    # теорем. Без этой проверки пять строк давали ложные STALE (измерено).
    if re.search(r"Lean(?:\s|&nbsp;|&#160;)*$", line[max(0, start - 10):start], re.I):
        return False
    return True




def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.md", "*.html"],
                         cwd=ROOT, capture_output=True, text=True)
    return [f for f in out.stdout.splitlines() if f.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Аудит числовых утверждений в документации")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-naked", action="store_true",
                    help="показать UNKNOWN-вхождения (шаблон совпал, факта нет)")
    args = ap.parse_args()

    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    stale: list = []
    unknown: list = []
    guarded = anchored = 0
    scanned = 0

    for rel in tracked():
        if rel in SKIP_FILES or rel.startswith(SKIP_PREFIXES):
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            if ANCHOR_NEAR.search(line):
                anchored += 1
                continue
            if DEFECT_ROW.match(line):
                continue  # журнал дефектов описывает ПРОШЛОЕ
            for label, key, rx in RULES:
                want = facts.get(key)
                if want is None:
                    continue
                for m in rx.finditer(line):
                    if _in_space_group(line, m.start()):
                        continue  # «1 000 000 мутаций»: это не утверждение о 0
                    if not _is_claim_about_total(line, m.start()):
                        continue  # число конкретного файла или периода
                    got = int(m.group(1))
                    if got == want:
                        guarded += 1
                    else:
                        stale.append((rel, lineno, label, got, want))

    if args.json:
        print(json.dumps({"files_scanned": scanned, "anchored_lines": anchored,
                          "guarded": guarded, "stale": stale, "unknown": unknown},
                         ensure_ascii=False, indent=2))
        return 1 if stale else 0

    print("=" * 68)
    print("KERN: АУДИТ ЧИСЛОВЫХ УТВЕРЖДЕНИЙ В ДОКУМЕНТАЦИИ")
    print("=" * 68)
    print(f"  файлов просканировано: {scanned} (история пропущена)")
    print(f"  строк с якорем (make sync): {anchored}")
    print(f"  значений совпало с фактом:  {guarded}")
    print(f"  расхождений:                {len(stale)}")
    print(f"  неклассифицировано:         {len(unknown)}")

    if stale:
        print("\n  РАСХОЖДЕНИЯ (значение != факт) — ЭТО ДЕФЕКТ:")
        for rel, lineno, label, got, want in stale:
            print(f"    {rel}:{lineno}  {label}: обещано {got}, факт {want}")
    if args.list_naked and unknown:
        print("\n  НЕКЛАССИФИЦИРОВАНО (шаблон совпал, факта нет) — проверить глазами:")
        for rel, lineno, label, raw in unknown[:40]:
            print(f"    {rel}:{lineno}  {label}: {raw!r}")

    print()
    if stale:
        print(f"ПРОВАЛОВ: {len(stale)}")
        return 1
    print("РАСХОЖДЕНИЙ НЕТ: каждое распознанное число совпадает с facts.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

