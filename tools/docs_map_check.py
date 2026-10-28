#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the KERN Source License (see LICENSE).
"""
ДЕФЕКТЫ #402/#403/#404: КАРТА ДОКУМЕНТАЦИИ (`docs/README.md`) НЕ ПРОВЕРЯЛАСЬ НИЧЕМ.

Измерено 2026-10-28:
  * #402 — строка 29 карты содержала ДВЕ склеенные табличные строки через `||`
    (полная копия самой себя): читатель видел дубль, а гейт — ничего;
  * #403 — **21 ключевой документ** (`CAPABILITY_MATRIX`, `CORPORA`, `TEN_PROOFS`,
    `CHARTER`, `SEMVER`, `NEXT_SESSION`, `CONTRACT_ANY_PROJECT`, `EXAMPLE_WHY_KERN`,
    `SHADOW_AUDIT_EXAMPLE`, `REAL_WORLD_*`, `CWE_COVERAGE`, `AI_TRAPS_SHOWCASE`,
    `HIGH_STAKES_USE_CASES`, `SELF_VERIFICATION`, `LIVE_*`, `REAL_BUGS_FOUND`,
    `ALL_CAPABILITIES_LIVE_GUIDE`, `STATUS*`, `INTUITIONISTIC_DESIGN`) НЕ упоминались
    в карте вообще — найти их из оглавления было невозможно;
  * #404 — диапазоны разделов устарели (`§1–§149` при факте §167; `§1–§151` при §145).

Класс тот же, что #370 (журнал), #380 (метрики `--xray`) и #381 (`_XRAY_EXTS`):
документ говорит не то, что происходит, и ни один гейт этого не видит.

ПРАВИЛА (три, все обязательные):
  R1. Каждый `docs/*.md` обязан быть УПОМЯНУТ в карте как `](ИМЯ)` — либо
      объявлен в `EXEMPT` с ЯВНОЙ причиной.
  R2. Каждая ссылка карты вида `](ИМЯ.md)` обязана вести в СУЩЕСТВУЮЩИЙ файл.
  R3. Ни одна табличная строка карты не содержит `||` — это признак СКЛЕЙКИ
      двух строк в одну (#402).

Честная граница: гейт проверяет НАЛИЧИЕ упоминания, а не верность описания
(описание — проза, её машинно не проверить). Записи в `EXEMPT` обязаны
существовать: устаревшее исключение — это тоже дефект.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MAP = DOCS / "README.md"

# Исключения: документ -> ПОЧЕМУ он не обязан быть в карте.
# Устаревшее исключение (файла нет) — дефект, гейт краснеет.
EXEMPT = {
    "README.md": "сама карта документации",
    "RELEASE_NOTES_v2.5.0.md": "исторические релиз-ноты",
    "RELEASE_NOTES_v2.5.1.md": "исторические релиз-ноты",
    "RELEASE_NOTES_v2.5.1.en.md": "исторические релиз-ноты (EN-зеркало)",
    "RELEASE_NOTES_v2.5.2.md": "исторические релиз-ноты",
    "RELEASE_NOTES_v2.5.2.en.md": "исторические релиз-ноты (EN-зеркало)",
    "RELEASE_NOTES_v2.7.2.md": "исторические релиз-ноты",
    "BELNAP_SOURCES.en.md": "EN-зеркало описано в строке BELNAP_SOURCES.md",
    "CORPORA.en.md": "EN-зеркало описано в строке CORPORA.md",
    "SELF_VERIFICATION.ru.md": "RU-зеркало описано в строке SELF_VERIFICATION.md",
    "NEXT_SESSION.ru.md": "RU-зеркало описано в строке NEXT_SESSION.md",
    "STATUS.ru.md": "RU-зеркало описано в строке STATUS.md",
    "ALL_CAPABILITIES_LIVE_GUIDE.ru.md": "RU-зеркало описано в строке .md",
    "CAPABILITY_MATRIX.ru.md": "RU-зеркало описано в строке CAPABILITY_MATRIX.md",
    "TEN_PROOFS.ru.md": "RU-зеркало описано в строке TEN_PROOFS.md",
    "EXAMPLE_WHY_KERN.ru.md": "RU-зеркало описано в строке EXAMPLE_WHY_KERN.md",
    "REAL_WORLD_CAPABILITIES.ru.md": "RU-зеркало описано в строке .md",
    "CWE_COVERAGE.ru.md": "RU-зеркало описано в строке CWE_COVERAGE.md",
    "AI_TRAPS_SHOWCASE.ru.md": "RU-зеркало описано в строке AI_TRAPS_SHOWCASE.md",
    "CHARTER.ru.md": "RU-зеркало описано в строке CHARTER.md",
}


def read_map() -> str:
    return MAP.read_text(encoding="utf-8")


def referenced(text: str) -> set:
    """Все цели ссылок карты `](...)`."""
    return set(re.findall(r"\]\(([^)]+)\)", text))


def missing_from_map() -> list:
    out = []
    for p in sorted(DOCS.glob("*.md")):
        name = p.name
        if name in EXEMPT:
            continue
        if f"]({name})" not in read_map():
            out.append(name)
    return out


def stale_exempt() -> list:
    return [n for n in sorted(EXEMPT) if not (DOCS / n).exists()]


def broken_links() -> list:
    """Ссылки карты на .md, ведущие в никуда (в пределах docs/)."""
    out = []
    for target in sorted(referenced(read_map())):
        if not target.endswith(".md"):
            continue
        if target.startswith(("http://", "https://", "../")):
            continue
        if not (DOCS / target).exists():
            out.append(target)
    return out


def glued_lines() -> list:
    """R3: табличная строка с `||` внутри — признак склейки двух строк (#402)."""
    out = []
    for i, line in enumerate(read_map().splitlines(), 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        core = s[1:-1] if s.endswith("|") else s[1:]
        if "||" in core:
            out.append(i)
    return out


def check() -> int:
    bad = 0
    m = missing_from_map()
    if m:
        print(f"[FAIL #403] {len(m)} док(ов) есть в docs/, но НЕ в карте:")
        for n in m:
            print(f"    - {n}")
        bad += 1
    se = stale_exempt()
    if se:
        print(f"[FAIL] устаревшие записи EXEMPT (файла нет): {se}")
        bad += 1
    bl = broken_links()
    if bl:
        print(f"[FAIL] карта ссылается в никуда: {bl}")
        bad += 1
    gl = glued_lines()
    if gl:
        print(f"[FAIL #402] склейка табличных строк (`||`) в строках: {gl}")
        bad += 1
    if bad:
        return 1
    total = len(list(DOCS.glob("*.md")))
    print(f"[OK] карта полна: {total} док(ов) в docs/, {len(EXEMPT)} исключений с причиной, "
          f"ссылки ведут в существующие файлы, склеек нет")
    return 0


def selftest() -> int:
    """Мета-тест: гейт обязан ловить каждую из трёх диверсий."""
    import shutil
    import tempfile

    global DOCS, MAP
    failures = []
    saved_docs, saved_map = DOCS, MAP

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "docs").mkdir()
        for f in saved_docs.glob("*.md"):
            shutil.copy2(f, tmp / "docs" / f.name)
        DOCS, MAP = tmp / "docs", tmp / "docs" / "README.md"

        # 1. Новый документ вне карты
        (DOCS / "ZZZ_probe.md").write_text("# probe\n", encoding="utf-8")
        if check() == 0:
            failures.append("новый док вне карты НЕ пойман")
        (DOCS / "ZZZ_probe.md").unlink()

        orig = MAP.read_text(encoding="utf-8")

        # 2. Склейка строки
        MAP.write_text(orig.replace("| Документ | Что внутри |",
                                    "| Документ | Что внутри |  || | дубль |", 1),
                       encoding="utf-8")
        if check() == 0:
            failures.append("склейка `||` НЕ поймана")
        MAP.write_text(orig, encoding="utf-8")

        # 3. Ссылка в никуда
        MAP.write_text(orig + "\n| **[nope.md](nope.md)** | нет такого файла |\n",
                       encoding="utf-8")
        if check() == 0:
            failures.append("ссылка в никуда НЕ поймана")
        MAP.write_text(orig, encoding="utf-8")

    DOCS, MAP = saved_docs, saved_map
    if failures:
        for f in failures:
            print(f"[FAIL] мета-тест: {f}")
        return 1
    print("[OK] мета-тест: 3 диверсии пойманы (новый док / склейка / ссылка в никуда)")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    return check()


if __name__ == "__main__":
    sys.exit(main())
