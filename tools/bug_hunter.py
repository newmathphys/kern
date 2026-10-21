#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
"""ПУНКТ 39: ОХОТА ЗА НАСТОЯЩИМИ БАГАМИ В ЖИВОМ ЧУЖОМ КОДЕ.

ЗАЧЕМ. Прогоняем наш БЕЗАННОТАЦИОННЫЙ рентген (`--xray`) по реальным файлам
стандартной библиотеки Python и честно печатаем, что найдено. Никаких «5000
функций проверено»: печатается ВОРОНКА (`checked N / M, skipped K с причинами`).

КОНТРОЛЬ (анти-вакуум): помимо stdlib сканируется НАША фикстура
`examples/xray_demo.py` с ИЗВЕСТНЫМИ находками — если детектор перестал их
находить, цель обязана покраснеть (иначе «0 находок в stdlib» ничего не значит).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"
CONTROL = ROOT / "examples" / "xray_demo.py"
RE_FIND = re.compile(r"\[(DEAD BRANCH|REDUNDANT GUARD|CRASH PATH|BOUNDS PATH|IMPURE)\]")
# ОБВИНЕНИЕ (утверждается дефект) против КАНДИДАТА (печатается свидетельство,
# решение за человеком). `[BOUNDS PATH]` по СИМВОЛИЧЕСКОЙ длине — кандидат:
# анализатор не моделирует инварианты циклов вида `while len(x) <= i: x.append`
# (дефект #315), поэтому такой индекс объявляется «возможным» с контрпримером,
# который на самом деле недостижим. `[CRASH PATH]`, `[DEAD BRANCH]`,
# `[REDUNDANT GUARD]`, `[IMPURE]` — обвинения, и ложных среди них быть не должно.
RE_HARD = re.compile(r"\[(DEAD BRANCH|REDUNDANT GUARD|CRASH PATH|IMPURE)\]")
# ДЕФЕКТ #313: формат сводки `--xray` получил пояснение в скобках
# (`functions (SMT-verified 2, no obligations 1), skipped …`), а регулярка
# осталась прежней и НЕ совпадала НИКОГДА. Из-за этого воронка охвата в
# `bug_hunter` показывала `checked 0/0` — в том числе на контрольной фикстуре,
# то есть проверка «охват непустой» была сломана молча. Скобка необязательна.
RE_SUM = re.compile(
    r"\[XRAY SUMMARY\] checked (\d+) / (\d+) functions"
    r"(?:\s*\([^)]*\))?, skipped (\d+)")

def scan(path: Path) -> tuple[int, int, int, list[str]]:
    r = subprocess.run([sys.executable, str(EXTRACTOR), "--xray", str(path)],
                       capture_output=True, text=True, timeout=300)
    out = (r.stdout or "") + (r.stderr or "")
    m = RE_SUM.search(out)
    checked, total, skipped = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
    found = [ln.strip() for ln in out.splitlines() if RE_FIND.search(ln)]
    return checked, total, skipped, found

def _run(args: list[str], timeout: int = 300) -> tuple[int, str]:
    """Запуск подпроцесса с захватом вывода (общий помощник сценариев)."""
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def trophies() -> int:
    """ПУНКТ 3: 4 БОЕВЫХ СЦЕНАРИЯ v2.5 (реальные прогоны, а не декларации).

    Каждый сценарий требует ПОЗИТИВНЫЙ и НЕГАТИВНЫЙ исход: если детектор
    перестанет ловить баг (или начнёт обвинять корректный код) — цель краснеет.
    """
    py = sys.executable
    kc = str(EXTRACTOR)
    kernc = str(ROOT / "zig-out" / "bin" / "kernc")
    ok = 0
    total = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok, total
        total += 1
        if cond:
            ok += 1
            print(f"  [OK] {name}")
        else:
            print(f"  [FAIL] {name} {detail}")

    print("[1] СЦЕНАРИЙ 1: баг переполнения binary_search (Джошуа Блох, JDK 2006)")
    # Баговая версия — В BV-РЕЖИМЕ (@kern:bitvec32): в теории Int промежуточная
    # сумма не переполняется, поэтому баг виден ТОЛЬКО в машинной семантике.
    rc_b, out_b = _run([py, kc, "audits/bloch/binary_search.zig"])
    check("баговый mid ловится (REFUTED + контрпример в QF_BV)",
          "КОНТРАКТ НАРУШЕН" in out_b and "#xc0000000" in out_b,
          out_b.strip().splitlines()[-1][:120] if out_b.strip() else "")
    # Безопасная версия — в теории Int (без BV-аннотации).
    rc_s, out_s = _run([py, kc, "audits/bloch/binary_search_safe.zig"])
    check("безопасный mid доказывается (PROVEN)",
          "ДОКАЗАНО" in out_s and "нарушено 0" in out_s, "")

    print("[2] СЦЕНАРИЙ 2: аудит Pull Request через --diff-equiv")
    rc_d, out_d = _run([py, kc, "--diff-equiv", "examples/refactor_before.py",
                        "examples/refactor_after.py"])
    check("регрессия рефакторинга поймана ([DIVERGED] + контрпример)",
          "DIVERGED" in out_d and "КОНТРПРИМЕР" in out_d, "")
    # Корректный рефакторинг: та же семантика, другая запись.
    tmp = ROOT / ".bug_hunter_refactor_ok.py"
    tmp.write_text(
        "def charge(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n", encoding="utf-8")
    try:
        rc_e, out_e = _run([py, kc, "--diff-equiv",
                            "examples/refactor_before.py", str(tmp)])
    finally:
        tmp.unlink(missing_ok=True)
    check("корректный рефакторинг эквивалентен ([EQUIVALENT])",
          "EQUIVALENT" in out_e, "")

    print("[3] СЦЕНАРИЙ 3: Web3/DeFi анти-арбитраж (@kern:no_arbitrage)")
    # ВАЖНО: пресеты включаются флагом --presets (иначе они не применяются).
    rc_a, out_a = _run([py, kc, "--presets", "examples/arbitrage_demo.py"])
    check("дробление платежа выгодно -> ARBITRAGE FOUND",
          "no_arbitrage REFUTED" in out_a, "")
    check("пропорциональная комиссия доказана (PROVEN, trusted: 0)",
          "no_arbitrage PROVEN (trusted: 0" in out_a, "")

    print("[4] СЦЕНАРИЙ 4: Python stdlib — 0 ложных тревог на эталонном коде")
    base = Path(os.path.dirname(os.__file__))
    files = sorted(p for p in base.rglob("*.py") if p.is_file())[:8]
    ck = tot = found = hard = 0
    for f in files:
        try:
            c, t, _s, fd = scan(f)
        except Exception:
            continue
        ck += c
        tot += t
        found += len(fd)
        hard += sum(1 for ln in fd if RE_HARD.search(ln))
    print(f"  checked {ck}/{tot} функций в {len(files)} файлах, находок {found} "
          f"(из них обвинений {hard})")
    # ДЕФЕКТ #315: `[BOUNDS PATH]` по символической длине — КАНДИДАТ, а не
    # приговор: инвариант `while len(x) <= i: x.append({})` гарантирует
    # `i < len(x)`, но не моделируется. Поэтому здесь утверждается 0 ЛОЖНЫХ
    # ОБВИНЕНИЙ (это и есть обещание инструмента), а число кандидатов
    # печатается рядом — оно требует проверки человеком.
    check("0 ложных ОБВИНЕНИЙ на stdlib", hard == 0, f"(обвинений {hard})")
    check("воронка охвата непустая", ck > 0, f"(checked {ck})")

    print("-" * 78)
    print(f"[TROPHIES] сценариев 4 | проверок {ok}/{total}")
    return 0 if ok == total else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Охота за багами в живом коде")
    ap.add_argument("--dir", default=None, help="каталог (по умолчанию stdlib Python)")
    ap.add_argument("--max-files", type=int, default=25)
    ap.add_argument("--trophies", action="store_true",
                    help="4 боевых сценария v2.5 (Bloch, PR-диф, DeFi, stdlib)")
    args = ap.parse_args()

    if args.trophies:
        return trophies()

    # 1) КОНТРОЛЬ: детектор обязан находить ИЗВЕСТНЫЕ находки.
    c_checked, c_total, _cs, c_found = scan(CONTROL)
    print(f"[контроль] {CONTROL.name}: checked {c_checked}/{c_total}, находок {len(c_found)}")
    if len(c_found) < 2:
        print("[!] КОНТРОЛЬ НЕ ПРОЙДЕН: детектор не видит известные находки")
        return 2

    base = Path(args.dir) if args.dir else Path(os.path.dirname(os.__file__))
    files = sorted(p for p in base.rglob("*.py") if p.is_file())[: args.max_files]
    total_found = 0
    files_with = 0
    checked_sum = total_sum = skipped_sum = 0
    print("-" * 78)
    print(f"[i] каталог: {base} | файлов к сканированию: {len(files)}")
    for f in files:
        try:
            ck, tot, sk, found = scan(f)
        except Exception as e:
            print(f"  [SKIP] {f.name}: {e}")
            continue
        checked_sum += ck
        total_sum += tot
        skipped_sum += sk
        if found:
            files_with += 1
            total_found += len(found)
            print(f"  {f.name}: находок {len(found)}")
            for ln in found[:3]:
                print(f"     {ln[:150]}")
    print("-" * 78)
    print(f"[BUG HUNT] файлов {len(files)} | функций checked {checked_sum} / {total_sum} "
          f"(skipped {skipped_sum}) | файлов с находками {files_with} | находок {total_found}")
    print("[i] Честно: находки в чужом коде НЕ являются приговором — каждая требует "
          "проверки контрпримером (--xray печатает его для CRASH PATH).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
