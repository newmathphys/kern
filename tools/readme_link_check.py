#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN gate: every relative link in the READMEs must resolve to a real file.

WHY THIS GATE EXISTS (defect #354).

`docs-parity` compares fact ANCHORS, `claims-audit` scans NUMBERS, and
`journal-parity-check` compares defect record numbers. NONE of them looks at
whether a link in the README actually points at a file that exists.

Measured: commit `7480996` ("Release v2.7.1") added the line
`[Plan v2.7.1](docs/PLAN_v2.7.1.md)` to BOTH READMEs, and that file was never
created (no commit in the history ever adds or deletes it). So the README of the
published release `v2.7.1` pointed at a document that does not exist - for an
entire release, in the first screen a visitor clicks. The class is the same as
#335/#350: an artefact that describes the project was not checked against
reality.

WHAT IS ASSERTED.

  For `README.md` and `README.ru.md`: every markdown link target that is a
  RELATIVE path resolves to an existing file or directory inside the repository.

WHAT THIS GATE DOES NOT CLAIM.

  * It does NOT fetch `http(s)://` links - a network gate would be flaky and
    would make the suite depend on someone else's uptime.
  * It does NOT check whether the target is the RIGHT document, only that it
    exists. A link to an existing but stale page is a human judgement.
  * It does NOT check anchors (`#section`) inside the target file - only the
    file's existence. Anchor checking is a separate, stricter contract.
  * It reads the READMEs ONLY. Other documents are covered by their own gates;
    widening the scope is a deliberate decision, not a default.

Запуск:  python3 tools/readme_link_check.py [--selftest]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "README.md", ROOT / "README.ru.md"]

# Markdown-ссылка: [текст](цель). Цель может содержать пробелы в <...>.
LINK = re.compile(r"\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
# Ограждение блока кода: ``` ... ``` — внутри ссылки не являются разметкой.
FENCE = re.compile(r"^\s*(```|~~~)")


def links_in(path: Path) -> list[tuple[int, str]]:
    """(номер строки, цель) для всех markdown-ссылок ВНЕ блоков кода."""
    out: list[tuple[int, str]] = []
    if not path.exists():
        return out
    inside = False
    text = path.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            inside = not inside
            continue
        if inside:
            continue
        for target in LINK.findall(line):
            out.append((i, target))
    return out


def _is_external(target: str) -> bool:
    low = target.lower()
    if low.startswith(("http://", "https://", "mailto:", "tel:")):
        return True
    if target.startswith("#"):          # ссылка-якорь внутри документа
        return True
    if target.startswith("//"):         # протокол-относительная
        return True
    return False


def check(targets: list[Path] | None = None) -> list[str]:
    """Возвращает список расхождений (пустой список = все ссылки живые)."""
    targets = TARGETS if targets is None else targets
    errs: list[str] = []
    for path in targets:
        if not path.exists():
            errs.append(f"нет файла {path.name} — проверять нечего (честный отказ)")
            continue
        for lineno, target in links_in(path):
            if _is_external(target):
                continue
            rel = target.split("#", 1)[0].split("?", 1)[0].strip("<>")
            if not rel:
                continue
            dest = (path.parent / rel).resolve()
            if not dest.exists():
                errs.append(f"{path.name}:{lineno}: битая ссылка `{target}` — "
                            f"файла `{rel}` нет в репозитории")
    return errs


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    print("ССЫЛКИ В README ВЕДУТ В СУЩЕСТВУЮЩИЕ ФАЙЛЫ")
    total = 0
    for p in TARGETS:
        n = len(links_in(p))
        total += n
        print(f"  {p.name}: ссылок {n}")
    errs = check()
    if errs:
        for x in errs:
            print(f"[FAIL] {x}")
        print("\n[FAIL] README ссылается на несуществующий файл: документ релиза "
              "врёт о собственном содержимом (класс #335/#350).")
        return 1
    print(f"\n[OK] все относительные ссылки ({total} проверено) ведут "
          f"в существующие файлы")
    return 0


def selftest() -> int:
    """Мета-тест: гейт обязан ловить битую ссылку, не считать внешние ссылки,
    якоря и содержимое блоков кода, и честно отказывать без файла."""
    import tempfile
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "docs").mkdir()
        (root / "docs" / "exists.md").write_text("x\n", encoding="utf-8")
        readme = root / "README.md"

        # (1) живая ссылка проходит
        readme.write_text("[a](docs/exists.md)\n", encoding="utf-8")
        if check([readme]):
            print("[FAIL] selftest: существующая ссылка признана битой")
            bad += 1
        else:
            print("[OK] selftest: живая ссылка проходит")

        # (2) битая ссылка ЛОВИТСЯ (это дефект #354)
        readme.write_text("[a](docs/PLAN_v2.7.1.md)\n", encoding="utf-8")
        if not any("битая ссылка" in x for x in check([readme])):
            print("[FAIL] selftest: битая ссылка НЕ поймана")
            bad += 1
        else:
            print("[OK] selftest: битая ссылка ловится")

        # (3) внешние ссылки и якоря НЕ считаются битыми
        readme.write_text("[a](https://example.org/nope.md)\n[b](#local-anchor)\n"
                          "[c](mailto:x@y.z)\n", encoding="utf-8")
        if check([readme]):
            print("[FAIL] selftest: внешняя ссылка/якорь признаны битыми")
            bad += 1
        else:
            print("[OK] selftest: внешние ссылки и якоря игнорируются")

        # (4) содержимое блока кода не считается разметкой
        readme.write_text("```\n[a](docs/nope.md)\n```\n", encoding="utf-8")
        if check([readme]):
            print("[FAIL] selftest: ссылка внутри блока кода признана битой")
            bad += 1
        else:
            print("[OK] selftest: блоки кода не сканируются")

        # (5) якорь в живой ссылке не мешает проверке файла
        readme.write_text("[a](docs/exists.md#section)\n", encoding="utf-8")
        if check([readme]):
            print("[FAIL] selftest: якорь в живой ссылке сломал проверку")
            bad += 1
        else:
            print("[OK] selftest: якорь отбрасывается, файл проверяется")

        # (6) отсутствующий README — честный отказ, а не молчаливое «ок»
        if not check([root / "nope.md"]):
            print("[FAIL] selftest: отсутствующий README НЕ пойман")
            bad += 1
        else:
            print("[OK] selftest: отсутствующий README ловится")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] readme-link selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

