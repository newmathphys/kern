#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ГЕЙТ #474: `PROVEN` В ТАБЛИЦЕ ДОКАЗАТЕЛЬСТВ ОБЯЗАН НЕСТИ ЧИСЛО ДОВЕРЕННЫХ ШАГОВ.

ЗАЧЕМ. Слово `PROVEN` — это вердикт РЕШАТЕЛЯ. Пруф-чекер проверяет вывод
ОТДЕЛЬНО и для QF_BV честно сообщает `[PROOF PARTIAL]` с числом доверенных
шагов (аксиомы бит-бластера `k!`). ИЗМЕРЕНО на `hex_index_deepjit_hex_hi`:
решатель `ДОКАЗАНО`, чекер `ДОВЕРЕННЫХ 15`. Пока таблица печатала просто
`**PROVEN**`, внешний читатель получал ДВЕ РАЗНЫЕ претензии под одним словом,
и «доказательство, проверяемое без решателя» превращалось в обещание, которого
для BV нет.

ПРАВИЛО (проверяется машинно):
  1. каждая строка с `**PROVEN**` обязана содержать `trusted`;
  2. `trusted 0` — доказательство ПРОВЕРЕНО полностью;
  3. `trusted N > 0` — рядом обязан стоять маркер `[PROOF PARTIAL]`;
  4. строка не может одновременно утверждать `trusted 0` и `PARTIAL`.

Невакуумность (`--selftest`): на синтетической таблице обе стороны — «правильная»
и «нарушающая» — проверяются здесь же, поэтому гейт не может быть зелёным от
того, что просто не нашёл строк (пустой файл = отдельная ошибка).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "audits" / "EVIDENCE.md"

RE_PROVEN = re.compile(r"\|\s*`[^`]+`\s*\|.*\*\*PROVEN\*\*")
RE_TRUSTED = re.compile(r"trusted\s+(\d+|\?)")
RE_PARTIAL = re.compile(r"\[PROOF PARTIAL\]")


def audit(text: str) -> tuple[int, list[str], int]:
    """Проверить таблицу. Возвращает (число PROVEN-строк, нарушения, число trusted 0)."""
    bad: list[str] = []
    proven = 0
    zero = 0
    for ln in text.splitlines():
        if not RE_PROVEN.search(ln):
            continue
        proven += 1
        m = RE_TRUSTED.search(ln)
        if not m:
            bad.append(f"PROVEN без числа доверенных шагов: {ln.strip()[:110]}")
            continue
        val = m.group(1)
        if val == "0":
            zero += 1
            if RE_PARTIAL.search(ln):
                bad.append(f"`trusted 0` вместе с `[PROOF PARTIAL]` — противоречие: {ln.strip()[:110]}")
        elif val == "?":
            continue            # чекер не сообщил счётчик — помечено честно
        else:
            if not RE_PARTIAL.search(ln):
                bad.append(f"`trusted {val}` без маркера `[PROOF PARTIAL]`: {ln.strip()[:110]}")
    return proven, bad, zero


def main() -> int:
    if "--selftest" in sys.argv:
        good = ("| `a.c` | `f` | QF_LIA (Int) | **PROVEN** (trusted 0) | — | — |\n"
                "| `b.c` | `g` | QF_BV _ BitVec 32 | **PROVEN** — `[PROOF PARTIAL]` trusted 15 | — | — |")
        n, bad, z = audit(good)
        assert n == 2 and not bad and z == 1, (n, bad, z)
        # НЕВАКУУМНОСТЬ: каждая из трёх поломок обязана быть поймана.
        for broken, why in (
                ("| `a.c` | `f` | QF_LIA (Int) | **PROVEN** | — | — |", "нет счётчика"),
                ("| `b.c` | `g` | QF_BV | **PROVEN** (trusted 15) | — | — |", "нет PARTIAL"),
                ("| `b.c` | `g` | QF_BV | **PROVEN** (trusted 0) — `[PROOF PARTIAL]` | — | — |",
                 "противоречие")):
            _n, _b, _z = audit(broken)
            assert _b, f"selftest: поломка «{why}» НЕ поймана"
        # Пустая таблица даёт НОЛЬ `PROVEN`-строк — это ловится в main().
        assert audit("| nothing |")[0] == 0, "selftest: пустая таблица дала PROVEN-строки"
        print("[OK] #474 selftest: 3 типа поломок ловятся, пустая таблица даёт 0 строк")
        return 0

    if not TABLE.exists():
        print(f"[!] #474: нет файла {TABLE.relative_to(ROOT)} — сначала `make audits`")
        return 1
    proven, bad, zero = audit(TABLE.read_text(encoding="utf-8"))
    print(f"[i] #474: строк `PROVEN` — {proven}, из них `trusted 0` — {zero}")
    for b in bad:
        print(f"[!] {b}")
    if proven == 0:
        print("[!] #474: `PROVEN`-строк нет вовсе — проверка вырождена (таблица пуста?)")
        return 1
    if bad:
        print(f"[FAIL] #474: {len(bad)} строк с неподтверждённой претензией `PROVEN`")
        return 1
    print("[OK] #474: каждый `PROVEN` несёт число доверенных шагов; PARTIAL помечен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
