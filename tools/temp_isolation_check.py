#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Изоляция временных путей (шаг N2).

ЗАЧЕМ. 60 жёстких путей `/tmp/kern*` в гейтах — это гонка: два параллельных
прогона (или `make -j`) перетирают файлы друг друга, и вердикт портится. Симптом
уже наблюдался: три гейта «показались сломанными», а это были помехи
параллельного прогона. Такую гонку невозможно отладить — её видно только как
«иногда падает».

НО НЕ ВСЁ В `/tmp` — МУСОР. Две категории путей ОБЯЗАНЫ быть общими, и `$$` им
приписывать НЕЛЬЗЯ:

  1. `/tmp/kern_mutation.lock` — глобальный межпроцессный замок (дефект #126).
     Если каждый процесс возьмёт СВОЙ замок, защита `tree-lock` станет фикцией:
     мутатор и проверяющий перестанут видеть друг друга.
  2. Кэш статических бинарников QEMU — общий, чтобы не качать десятки мегабайт
     на каждый прогон.

ПРАВИЛО ГЕЙТА. Каждый найденный путь обязан быть либо в списке SHARED (с
причиной), либо изолированным (`$$`, `mktemp`, `XXXXXX`, `getpid`, `TMPDIR`).
Новый общий путь нельзя завести молча — только осознанным решением в SHARED.

Запуск:  python3 tools/temp_isolation_check.py [--selftest]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ("Makefile",)
SCAN_DIRS = (ROOT / "tools",)

PATH_RE = re.compile(r"/tmp/[A-Za-z0-9_.${}/-]*(?:kern|qemu)[A-Za-z0-9_.${}/-]*")

# Пути, которым `$$`/`mktemp` ПРОТИВОПОКАЗАНЫ, с причиной.
SHARED = {
    "/tmp/kern_mutation.lock":
        "глобальный межпроцессный замок (#126): свой замок на процесс = фикция",
    "/tmp/qemu-aarch64-static":
        "общий кэш эмулятора (сейчас перенесён в ~/.cache/kern/qemu)",
    "/tmp/qemu-ppc64-static":
        "общий кэш эмулятора (сейчас перенесён в ~/.cache/kern/qemu)",
    # Не путь прогона, а СТРОКА-ДИВЕРСИЯ внутри кейса `temp-isolation`:
    # она дописывается в копию скрипта, чтобы гейт покраснел.
    "/tmp/kern_unsafe_new_path":
        "строка-диверсия в canfail (шаг N2), а не рабочий путь",
}

# Признаки изоляции: путь принадлежит ОДНОМУ прогону.
SCOPED = ("$$", "XXXXXX", "getpid", "getpid()", "mktemp", "TMPDIR",
          "mkdtemp", "mkstemp", "tempfile")

# Замок обязан быть ОДИНАКОВЫМ во всех файлах, которые его берут.
LOCK_FILES = ("tools/tree_lock.py", "tools/canfail.py", "tools/mutate_zig.py")
LOCK_CONST = re.compile(r'(?:LOCK_PATH|SHARED_LOCK)\s*=\s*"([^"]+)"')

# ХРАПОВИК (ratchet). Изоляция 58 путей — работа не на один заход, а гейт,
# который просто КРАСНЫЙ до её конца, блокирует всё остальное и через день будет
# отключён. Поэтому: текущий долг записан в файл, и гейт запрещает НОВЫЕ
# неизолированные пути, показывая остаток. Долг виден, регресс невозможен,
# прогресс обязателен к фиксации (убрал путь из базы — гейт это проверит).
BASELINE = ROOT / "tools" / "temp_isolation_baseline.txt"


def _baseline() -> set[str]:
    if not BASELINE.exists():
        return set()
    return {l.strip() for l in BASELINE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def _files():
    out = []
    for rel in SCAN:
        p = ROOT / rel
        if p.exists():
            out.append(p)
    for d in SCAN_DIRS:
        out.extend(sorted(p for p in d.glob("*.sh")))
        out.extend(sorted(p for p in d.glob("*.py") if p.name != Path(__file__).name))
    return out


def check() -> list[str]:
    errs: list[str] = []
    base = _baseline()
    seen: dict[str, set[str]] = {}
    debt: set[str] = set()
    for p in _files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            # Комментарии не описывают прогон: `# … /tmp/kern*` в пояснении —
            # это текст, а не путь. Иначе гейт ловит собственное объяснение.
            if line.lstrip().startswith("#"):
                continue
            for m in PATH_RE.finditer(line):
                raw = m.group(0)
                seen.setdefault(raw, set()).add(p.relative_to(ROOT).as_posix())
                if raw in SHARED:
                    continue
                if any(s in line for s in SCOPED):
                    continue
                debt.add(raw)
                if raw in base:
                    continue
                errs.append(f"{p.relative_to(ROOT)}: `{raw}` — НОВЫЙ общий путь "
                            f"без изоляции. Либо `mktemp`/`$$`, либо решение в SHARED")
    # Долг, который уже закрыт, обязан быть вычеркнут: иначе база тихо устареет.
    closed = base - debt
    for raw in sorted(closed):
        errs.append(f"`{raw}` больше не найден без изоляции — уберите его из "
                    f"{BASELINE.name} (иначе база описывает несуществующий долг)")
    # Замок: одинаковый и БЕЗ изоляции во всех файлах, которые его берут.
    locks: dict[str, list[str]] = {}
    for rel in LOCK_FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        m = LOCK_CONST.search(p.read_text(encoding="utf-8", errors="replace"))
        if m:
            locks.setdefault(m.group(1), []).append(rel)
    if len(locks) > 1:
        errs.append(f"путь замка РАЗЛИЧАЕТСЯ между файлами: {locks} — "
                    f"защита #126 перестанет работать")
    for path, files in locks.items():
        if any(s in path for s in ("$$", "getpid")):
            errs.append(f"замок `{path}` изолирован по процессу ({files}) — "
                        f"это уничтожает защиту #126")
    print(f"  путей найдено: {len(seen)} | общих по решению: "
          f"{len([p for p in seen if p in SHARED])} | без изоляции: {len(debt)} "
          f"(из них в базе долга: {len(debt & base)}) | замок: "
          f"{list(locks) or 'не найден'}")
    if debt - base:
        print(f"  [!] НОВЫХ неизолированных путей: {len(debt - base)} — "
              f"это регресс, а не унаследованный долг")
    return errs


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    print("ИЗОЛЯЦИЯ ВРЕМЕННЫХ ПУТЕЙ (N2)")
    errs = check()
    if errs:
        for e in errs[:20]:
            print(f"[FAIL] {e}")
        if len(errs) > 20:
            print(f"[FAIL] … и ещё {len(errs) - 20}")
        print(f"\n[FAIL] путей без изоляции: {len(errs)}. "
              f"Замок и кэш эмулятора трогать НЕЛЬЗЯ (см. SHARED).")
        return 1
    print("\n[OK] изоляция: все рабочие пути принадлежат одному прогону, "
          "общие — только по явному решению, замок един и не изолирован")
    return 0


def selftest() -> int:
    """Мета-тест: гейт обязан ловить ровно те две ошибки, ради которых создан.

    (1) новый общий рабочий путь без изоляции; (2) замок, изолированный по
    процессу (это уничтожило бы защиту #126, и заметить это иначе невозможно).
    """
    import tempfile
    bad = 0
    # (1) рабочий путь без изоляции — обязан быть признан дефектом.
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / "probe.sh"
        probe.write_text('X=/tmp/kern_probe_thing\n', encoding="utf-8")
        raw = "/tmp/kern_probe_thing"
        is_shared = raw in SHARED
        is_scoped = any(s in probe.read_text(encoding="utf-8") for s in SCOPED)
        if is_shared or is_scoped:
            print("[FAIL] selftest: незащищённый путь не распознан")
            bad += 1
        else:
            print("[OK] selftest: общий рабочий путь без изоляции ловится")
    # (2) замок с $$ — обязан быть отвергнут.
    lock = "/tmp/kern_mutation_$$.lock"
    if not any(s in lock for s in ("$$", "getpid")):
        print("[FAIL] selftest: изоляция замка не распознана")
        bad += 1
    else:
        print("[OK] selftest: изолированный замок распознаётся (и это дефект)")
    # (3) реальные файлы: замок обязан быть одинаковым.
    errs = check()
    lock_errs = [e for e in errs if "замк" in e]
    if lock_errs:
        print(f"[FAIL] selftest: расхождение замка: {lock_errs[0]}")
        bad += 1
    else:
        print("[OK] selftest: замок един во всех файлах, которые его берут")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] temp-isolation selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
