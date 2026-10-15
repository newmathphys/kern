#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: генератор КАТАЛОГА ТЕСТОВ из исходников.

ЗАЧЕМ. `docs/TEST_CATALOG.md` отставал от кода: заявлял 213 тестов, тогда
как в исходниках было 218 (не учтены `src/compat.zig` и 4 теста
`src/tests/os_stress_test.zig`). Документ, который расходится с кодом,
хуже отсутствующего: он создаёт ЛОЖНУЮ картину полноты.

Теперь каталог генерируется из исходников, а режим `--check` (для CI)
падает, если каталог отстал от кода.

Использование:
  python3 tools/gen_test_catalog.py          # перегенерировать
  python3 tools/gen_test_catalog.py --check  # только проверить (для CI)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "docs" / "TEST_CATALOG.md"

# Порядок и названия групп: (префикс пути, заголовок раздела)
GROUPS = [
    ("src/core/",     "Ядро формата и ФС (L0/L3)"),
    ("src/verifier/", "Верификатор (Врата, SMT, теории)"),
    ("src/tests/",    "Специализированные сьюты"),
    ("src/next/",     "KERN-Next (парсер, каталог, конвейер)"),
    ("src/runtime/",  "Среда исполнения"),
    ("src/root",      "Корень `src/`"),  # спец-ключ: файлы прямо в src/
]

TEST_RE = re.compile(r'^\s*test\s+"([^"]+)"', re.M)


def collect() -> dict:
    """Возвращает {group_title: {relpath: [имена тестов]}}."""
    buckets = {title: {} for _, title in GROUPS}
    for p in sorted(ROOT.glob("src/**/*.zig")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("src/next/test_root") or rel.endswith("test_root.zig"):
            pass  # test_root — агрегатор, тестов не объявляет
        names = TEST_RE.findall(p.read_text(encoding="utf-8", errors="replace"))
        if not names:
            continue
        for prefix, title in GROUPS:
            if prefix == "src/root":
                if "/" not in rel[len("src/"):]:
                    buckets[title][rel] = names
                    break
            elif rel.startswith(prefix):
                buckets[title][rel] = names
                break
    return buckets


def render_body(buckets: dict) -> str:
    out = []
    total = sum(len(n) for b in buckets.values() for n in b.values())
    out.append(f"**Всего объявлений тестов:** {total}\n")
    out.append("| Группа | Файлов | Тестов |")
    out.append("|:--|--:|--:|")
    for _, title in GROUPS:
        b = buckets[title]
        nf = len(b)
        nt = sum(len(v) for v in b.values())
        if nf:
            out.append(f"| {title} | {nf} | {nt} |")
    out.append("\n")
    for _, title in GROUPS:
        b = buckets[title]
        if not b:
            continue
        out.append(f"\n## {title}\n")
        for rel, names in b.items():
            out.append(f"\n### `{rel}` — {len(names)}\n")
            for n in names:
                out.append(f"- {n}")
            out.append("")
    return "\n".join(out) + "\n"


HEADER = """# KERN — КАТАЛОГ ТЕСТОВ (полный)

> **СГЕНЕРИРОВАНО** из исходников (`python3 tools/gen_test_catalog.py`).
> Каждое имя ниже — реальный тест, который можно запустить.
> Пропусков и «планируемых» тестов нет. Рассинхрон с кодом ловит
> `python3 tools/gen_test_catalog.py --check` (стадия CI).

"""


def build() -> str:
    body = render_body(collect())
    # Хвост (курируемый вручную): от «## Внешние бенчмарки» до конца.
    old = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else ""
    i = old.find("## Внешние бенчмарки")
    tail = "\n---\n\n" + old[i:] if i != -1 else ""
    return HEADER + body + tail


def main() -> int:
    new = build()
    old = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else ""
    if "--check" in sys.argv:
        if new == old:
            n = sum(len(v) for b in collect().values() for v in b.values())
            print(f"[OK] каталог тестов синхронен с кодом ({n} тестов)")
            return 0
        # Показываем, что именно разошлось
        import difflib
        diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                         "docs/TEST_CATALOG.md", "сгенерировано", n=0))
        print("[!] КАТАЛОГ ОТСТАЛ ОТ КОДА (запустите: python3 tools/gen_test_catalog.py)")
        for line in diff[:25]:
            print("   ", line)
        return 1
    CATALOG.write_text(new, encoding="utf-8")
    total = sum(len(n) for b in collect().values() for n in b.values())
    print(f"[OK] каталог перегенерирован: {total} тестов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
