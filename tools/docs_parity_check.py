#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""EN/RU parity of numeric facts.

Every public document has an EN/RU pair. Prose is NOT compared (condensed
mirrors are allowed), but the same `<!-- fact:key -->N` anchors must exist in
both files and carry the same value. This is what keeps the English and
Russian showcases from drifting apart.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "docs" / "facts.json"
PAIRS = (
    ("README.md", "README.ru.md"),
    ("docs/ATTESTATION_PASSPORT.md", "docs/ATTESTATION_PASSPORT.en.md"),
    ("docs/ALL_CAPABILITIES_LIVE_GUIDE.ru.md", "docs/ALL_CAPABILITIES_LIVE_GUIDE.md"),
    ("docs/CAPABILITIES.md", "docs/CAPABILITIES.en.md"),
    ("docs/CAPABILITY_STATUS.md", "docs/CAPABILITY_STATUS.en.md"),
    ("docs/STATUS.ru.md", "docs/STATUS.md"),
    ("docs/SELF_VERIFICATION.ru.md", "docs/SELF_VERIFICATION.md"),
    ("docs/CHARTER.ru.md", "docs/CHARTER.md"),
    ("docs/CYBERNETIC_VISION.md", "docs/CYBERNETIC_VISION.en.md"),
    ("docs/METRICS.md", "docs/METRICS.en.md"),
    ("docs/ROADMAP.md", "docs/ROADMAP.en.md"),
    ("docs/TESTING_AND_SPEED_GUIDE.md", "docs/TESTING_AND_SPEED_GUIDE.en.md"),
    ("docs/EXAMPLE_WHY_KERN.ru.md", "docs/EXAMPLE_WHY_KERN.md"),
    # §B плана: инвентарь корпусов обязан иметь паритет RU/EN — иначе русская
    # версия разойдётся молча (класс #335 «дефект, живущий только по-русски»).
    ("docs/CORPORA.md", "docs/CORPORA.en.md"),
    # ЭТАП 3: документ покрытия CWE обязан иметь паритет RU/EN, иначе русская
    # версия может разойтись молча (класс #335 — «дефект, живущий только
    # по-русски»).
    ("docs/CWE_COVERAGE.ru.md", "docs/CWE_COVERAGE.md"),
    # ЭТАП 4А: полигон ИИ-ловушек обязан иметь паритет RU/EN (класс #335).
    ("docs/AI_TRAPS_SHOWCASE.ru.md", "docs/AI_TRAPS_SHOWCASE.md"),
    # ЭТАП 5: матрица реальных возможностей — паритет RU/EN.
    ("docs/REAL_WORLD_CAPABILITIES.ru.md", "docs/REAL_WORLD_CAPABILITIES.md"),
    # ШАГ E плана: матрица возможностей (одна команда / оракул / граница) — паритет RU/EN.
    ("docs/CAPABILITY_MATRIX.ru.md", "docs/CAPABILITY_MATRIX.md"),
    # Десять доказательств (сверенные команды) — паритет RU/EN, иначе
    # русская версия разойдётся молча (класс #335).
    ("docs/TEN_PROOFS.ru.md", "docs/TEN_PROOFS.md"),
    # Передача дел: файл несёт якоря фактов, значит обязан иметь паритет RU/EN.
    ("docs/NEXT_SESSION.ru.md", "docs/NEXT_SESSION.md"),
    # Такт 2.2: план работ несёт якоря фактов и читается НОВОЙ сессией первой —
    # паритет RU/EN обязателен, иначе одна из версий разойдётся молча (#335).
    ("docs/PLAN_takt22.ru.md", "docs/PLAN_takt22.md"),
    # Такт 2.3: тот же класс — план читается новой сессией, паритет обязателен.
    ("docs/PLAN_takt23.ru.md", "docs/PLAN_takt23.md"),
    # Такт 2.4: три класса ложных обвинений (#471/#472/#473) — тот же класс документа.
    ("docs/PLAN_takt24.ru.md", "docs/PLAN_takt24.md"),
    # План следующего такта: задача — ДОКАЗАТЬ работоспособность, а не добавить фичи.
    ("docs/PLAN_NEXT.ru.md", "docs/PLAN_NEXT.md"),
    # Границы проекта («чего НЕ доказываем») — документ, который читают ДО покупки;
    # одна версия без другой разошлась бы молча (#335).
    ("docs/LIMITS.ru.md", "docs/LIMITS.md"),
    # Карта возможностей СГЕНЕРИРОВАНА из реестра: одна версия без другой
    # разошлась бы молча (#335), а карта — вход для внешнего аудита (#485).
    ("docs/CAPABILITY_MAP.ru.md", "docs/CAPABILITY_MAP.md"),
)
REQUIRED = ("core_tests", "next_tests", "catalog", "check_targets",
            "canfail_cases", "anchors", "registry_targets", "meta_targets",
            "lean_theorems", "quixbugs.smt", "quixbugs.differential")
ANCHOR = re.compile(r"<!--\s*fact:([a-z0-9_.]+)\s*-->\s*(\d+)")


def anchors(path: Path) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    if not path.exists():
        return out
    for key, val in ANCHOR.findall(path.read_text(encoding="utf-8", errors="replace")):
        out.setdefault(key, set()).add(int(val))
    return out


def compare(ru: Path, en: Path, required=REQUIRED) -> list[str]:
    a, b = anchors(ru), anchors(en)
    errs: list[str] = []
    for key in required:
        if key not in a:
            errs.append(f"{ru}: нет якоря fact:{key}")
        if key not in b:
            errs.append(f"{en}: нет якоря fact:{key}")
        if key in a and key in b and a[key] != b[key]:
            errs.append(f"fact:{key}: {ru}={sorted(a[key])} != {en}={sorted(b[key])}")
    for key in (set(a) & set(b)) - set(required):
        if a[key] != b[key]:
            errs.append(f"fact:{key}: {ru}={sorted(a[key])} != {en}={sorted(b[key])}")
    return errs


def cyr_selftest() -> list[str]:
    """НЕВАКУУМНОСТЬ гейта #506: русская ПРОЗА в EN-доке обязана ловиться,
    а кириллица ВНУТРИ кода/цитаты (`…`) — НЕ ловиться (это факт, не проза)."""
    import tempfile
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.en.md"
        bad.write_text("# Title\n\n" + "Это русская проза в английском документе.\n", encoding="utf-8")
        ok = Path(td) / "ok.en.md"
        ok.write_text("# Title\n\nThe checker prints `КОНТРАКТ НАРУШЕН` — a quoted fact.\n",
                      encoding="utf-8")
        if not cyrillic_in_en_docs([bad]):
            problems.append("проза с кириллицей НЕ поймана (вакуум)")
        if cyrillic_in_en_docs([ok]):
            problems.append("цитата в бэктиках ловится ЛОЖНО")
    return problems


def selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ru, en = Path(d) / "ru.md", Path(d) / "en.md"
        ru.write_text("<!-- fact:core_tests -->402 <!-- fact:check_targets -->128", encoding="utf-8")
        en.write_text("<!-- fact:core_tests -->402 <!-- fact:check_targets -->128", encoding="utf-8")
        ok = compare(ru, en, ("core_tests", "check_targets"))
        en.write_text("<!-- fact:core_tests -->401 <!-- fact:check_targets -->128", encoding="utf-8")
        bad = compare(ru, en, ("core_tests", "check_targets"))
    if ok:
        print(f"[FAIL] parity selftest: чистые пары дали {ok}")
        return 1
    if not bad:
        print("[FAIL] parity selftest: расхождение 402/401 НЕ поймано")
        return 1
    for prob in cyr_selftest():
        print(f"[FAIL] #506 selftest: {prob}")
        return 1
    print("  [OK] #506: русская проза в EN-доке ловится, цитата в бэктиках — нет")
    print("[OK] docs-parity selftest: расхождение ловится, чистые пары проходят")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# ДЕФЕКТ #506 (аудит EN-документации): «английский» документ с русской прозой.
# ПРАВИЛО: в EN-документах кириллица допустима ТОЛЬКО внутри кода/цитаты
# (`…` или блок ```…```), потому что там она — ФАКТ (сообщение инструмента,
# команда, вывод прогона). Русская ПРОЗА в английском документе — дефект.
# Исключения названы, а не «молча пропущены». Ссылки на `*.ru.md` легальны
# всегда: они не текст, а путь.
# ─────────────────────────────────────────────────────────────────────────────
EN_DOCS = ("README.md", "docs/LIMITS.md", "docs/CAPABILITY_MAP.md",
           "LICENSE-COMMERCIAL.md", "docs/RELEASE_NOTES_v2.8.2.md")
# ЗЕРКАЛА ЖУРНАЛОВ: там русские ЦИТАТЫ вердиктов идут в таблицах, и вырезать их
# значит потерять доказательство. Исключение НАЗВАНО и обосновано.
EN_DOCS_MIRRORS_ALLOWED = {"docs/METRICS.en.md": "цитаты вердиктов/вывода в таблицах",
                           "docs/CAPABILITY_STATUS.en.md": "цитаты вердиктов в таблицах",
                           "docs/BELNAP_SOURCES.en.md": "имя источника на языке оригинала"}
CYR = re.compile(r"[\u0400-\u04FF]")


def _strip_code(text: str) -> str:
    """Убрать блоки ```…``` и `…` — там кириллица ЛЕГАЛЬНА (это факт, не проза)."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`]*`", "", text)
    return text


def cyrillic_in_en_docs(paths: list | None = None) -> list[str]:
    out: list[str] = []
    if paths is not None:
        cand = list(paths)
    else:
        cand = [ROOT / f for f in EN_DOCS]
        cand += [p for p in ROOT.glob("docs/*.en.md")]
    for path in cand:
        if not path.exists():
            continue
        try:
            rel = str(path.relative_to(ROOT))
        except ValueError:      # путь вне репозитория (selftest во временном каталоге)
            rel = path.name
        if rel in EN_DOCS_MIRRORS_ALLOWED:
            continue
        prose = _strip_code(path.read_text(encoding="utf-8", errors="replace"))
        n = len(CYR.findall(prose))
        if n:
            try:
                label = str(path.relative_to(ROOT))
            except ValueError:      # файл вне репозитория (selftest во временном каталоге)
                label = path.name
            out.append(f"{label}: {n} кириллических символов В ПРОЗЕ "
                       f"(в коде/цитатах — легально)")
    return out


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    if not FACTS.exists():
        print(f"[FAIL] нет {FACTS} — запустите make sync")
        return 1
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    bad = 0
    for ru_rel, en_rel in PAIRS:
        errs = compare(ROOT / ru_rel, ROOT / en_rel)
        for e in errs:
            print(f"[FAIL] {e}")
            bad += 1
    for e in cyrillic_in_en_docs():
        print(f"[FAIL] #506: {e}")
        bad += 1
    if bad:
        print(f"\n[FAIL] EN/RU расхождений: {bad}")
        return 1
    print(f"[OK] EN/RU parity: {len(PAIRS)} пар, факты совпадают")
    print(f"     core {facts['core_tests']} · CHECK {facts['check_targets']} · "
          f"cases {facts['canfail_cases']} · targets {facts['registry_targets']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
