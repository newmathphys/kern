#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# SPDX-License-Identifier: LicenseRef-KERN-Proprietary
"""ГЕЙТ #399: справка CLI обязана называть КАЖДУЮ реализованную команду.

ЗАЧЕМ. Бинарник `kernc` реализовал 25 команд, а справка называла 10: `verify-zig`,
`theory`, `smtlib`, `check-proof`, `fsck`, `inspect`, `diff`, `pack-dir` — то есть
ВСЕ главные новинки релиза — из самого бинарника обнаружить было нельзя. Хуже:
`--help` не обрабатывался вообще (проваливался в ветку «укажите путь к образу»),
справка уходила в STDERR, а запуск без аргументов возвращал rc=0 — скрипт не мог
отличить «показал справку» от «сделал работу».

ЧТО ПРОВЕРЯЕТСЯ (всё — из ЖИВОГО прогона бинарника, не из текста файла):
  1. `kernc --help` -> rc=0, stdout НЕ пуст, stderr ПУСТ (справка — это данные);
  2. запуск без аргументов -> rc!=0 (названный отказ, а не тихий успех);
  3. каждое сравнение `std.mem.eql(u8, command, "...")` в `src/main.zig` названо
     в выводе `kernc --help` (26-я команда не сможет появиться недокументированной).

ЧЕГО НЕ ПРОВЕРЯЕТ: что справка ПРАВДИВА по существу (что у команды именно те
опции, что написаны) — это проверяет человек; гейт ловит только расхождение
СПИСКА команд.

Мутации (`--selftest`) — шесть: вырезать команду из справки; вернуть rc=0 на
запуск без аргументов; увести справку в stderr; пустой stdout; новая команда без
строки в справке; границы слова (`pack` не найден внутри `pack-dir`). Без этих
ветвей гейт мог бы «проходить» на пустом выводе.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_ZIG = ROOT / "src" / "main.zig"
KERNC = ROOT / "zig-out" / "bin" / "kernc"

# Сравнение ИМЕННО с `command` — под-опции (`--query-kind`, `sat`, `LE`) идут
# против ДРУГИХ переменных и в справку как команды попадать не обязаны.
DISPATCH_RE = re.compile(r'std\.mem\.eql\(u8,\s*command,\s*"([^"]+)"\)')


def dispatched_commands(src: str) -> list[str]:
    return sorted(set(DISPATCH_RE.findall(src)))


def run_kernc(*argv: str) -> tuple[int, str, str]:
    p = subprocess.run([str(KERNC), *argv], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout or "", p.stderr or ""


def violations(help_rc: int, help_out: str, help_err: str,
               noarg_rc: int, commands: list[str]) -> list[str]:
    """Возвращает список нарушений. Пусто = гейт зелёный."""
    bad: list[str] = []
    if help_rc != 0:
        bad.append(f"`kernc --help` вернул rc={help_rc}, ожидалось 0")
    if not help_out.strip():
        bad.append("`kernc --help` ничего не вывел в stdout")
    if help_err.strip():
        bad.append("`kernc --help` писал в stderr (справка — это ДАННЫЕ, stdout)")
    if noarg_rc == 0:
        bad.append("запуск без аргументов вернул rc=0 (тихий успех вместо отказа)")
    for c in commands:
        # Границы слова: `pack` не должен «находиться» внутри `pack-dir`.
        if not re.search(rf'(?<![A-Za-z0-9_-]){re.escape(c)}(?![A-Za-z0-9_-])', help_out):
            bad.append(f"команда `{c}` реализована, но НЕ названа в `kernc --help`")
    return bad


def selftest() -> int:
    """Шесть диверсий: гейт обязан краснеть на каждой."""
    src = MAIN_ZIG.read_text(encoding="utf-8")
    cmds = dispatched_commands(src)
    rc, out, err = run_kernc("--help")
    noarg_rc, _, _ = run_kernc()
    base = violations(rc, out, err, noarg_rc, cmds)
    if base:
        print(f"[FAIL] базовое состояние уже красное: {base[:2]}")
        return 1
    diversions = (
        ("команда вырезана из справки",
         lambda: violations(rc, out.replace("verify-zig", "XXX", 1), err, noarg_rc, cmds)),
        ("rc=0 при запуске без аргументов",
         lambda: violations(rc, out, err, 0, cmds)),
        ("справка уведена в stderr",
         lambda: violations(rc, out, "диагностика", noarg_rc, cmds)),
        ("пустой stdout",
         lambda: violations(rc, "", err, noarg_rc, cmds)),
        ("новая команда без строки в справке",
         lambda: violations(rc, out, err, noarg_rc, cmds + ["brand-new-cmd"])),
        ("границы слова: `pack` внутри `pack-dir`",
         lambda: violations(rc, "pack-dir", err, noarg_rc, ["pack"])),
    )
    for name, fn in diversions:
        if not fn():
            print(f"[FAIL] диверсия НЕ поймана: {name}")
            return 1
    print(f"[OK] selftest: {len(diversions)}/{len(diversions)} диверсий поймано")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not KERNC.exists():
        print(f"[FAIL] нет бинарника {KERNC} — сначала `make build`")
        return 1
    if not MAIN_ZIG.exists():
        print(f"[FAIL] нет {MAIN_ZIG}")
        return 1
    cmds = dispatched_commands(MAIN_ZIG.read_text(encoding="utf-8"))
    if not cmds:
        print("[FAIL] в src/main.zig не найдено ни одного сравнения с `command` "
              "— проверка была бы вакуумной")
        return 1
    help_rc, help_out, help_err = run_kernc("--help")
    noarg_rc, _, _ = run_kernc()
    bad = violations(help_rc, help_out, help_err, noarg_rc, cmds)
    print(f"CLI HELP PARITY (#399): команд реализовано {len(cmds)}, "
          f"справка {len(help_out.splitlines())} строк")
    if bad:
        for b in bad:
            print(f"  [FAIL] {b}")
        return 1
    # БАЙТЫ, а не символы: кириллица в UTF-8 — 2 байта, и метка «байт» на длине
    # строки в символах врала бы (класс #320: подпись обязана совпадать с мерой).
    print(f"  [OK] --help: rc=0, stdout {len(help_out.encode('utf-8'))} байт, "
          f"stderr пуст")
    print(f"  [OK] без аргументов: rc={noarg_rc} (названный отказ)")
    print(f"  [OK] все {len(cmds)} команд названы в справке")
    return 0


if __name__ == "__main__":
    sys.exit(main())
