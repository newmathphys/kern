#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Гейт: `--xray` находит переполнение ВНУТРИ выражения (дефект #367).

ЗАЧЕМ. До этой правки C-путь `--xray` имел детекторы деления на ноль, границ
массива, РАЗМЕРА АЛЛОКАЦИИ и ветвлений, но НЕ имел детектора переполнения
обычного выражения. ИЗМЕРЕНО на официальной категории SV-COMP
`signedintegeroverflow-regression`: поймано 0 из 10 unsafe. Контрактный путь
тоже молчал: он проверяет ИТОГОВОЕ значение возврата, а `(2147483647 + 1) - 23`
переполняется ВНУТРИ и «схлопывается» обратно в диапазон.

ЧТО ТРЕБУЕТ ГЕЙТ (обе половины обязательны):

  * НАХОДКА ровно одна и на функции `collapsing_sum` — переполнение внутри
    выражения, итог которого снова в диапазоне. Это и есть целевой случай;
  * ЧИСТО на четырёх функциях-ЛОВУШКАХ, каждая из которых в первой версии
    детектора давала ЛОЖНОЕ обвинение (дефект #368):
      - `guarded_sum`   — гард снимает переполнение;
      - `promoted_sum`  — целочисленное ПОВЫШЕНИЕ до `int` (C11 6.3.1.1);
      - `wide_sum`      — тип `long`, обязательства `i32` нет;
      - `wrapping_sum`  — беззнаковое заворачивание ОПРЕДЕЛЕНО стандартом.

ПОЧЕМУ ВТОРАЯ ПОЛОВИНА ВАЖНЕЕ ПЕРВОЙ. Детектор, который находит переполнение
ценой ложных обвинений, ХУЖЕ отсутствующего: ложное обвинение хуже пропуска
(урок #178/#183). Каждая ловушка здесь — это измеренный случай, где первая
версия ошибалась, и файл-эталон SV-COMP объяснял причину в своих комментариях.

ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ: он проверяет ОДИН файл-эталон, а не полноту детектора;
не проверяет качество сообщений; не покрывает беззнаковые типы (они намеренно
пропускаются — см. `_clike_overflow_findings`).

Запуск:  python3 tools/xray_overflow_check.py [--selftest]
Код возврата: 0 — обе половины выполнены; 1 — иначе.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
KERN_CONTRACTS = ROOT / "tools" / "kern_contracts.py"
DEMO = ROOT / "examples" / "overflow_xray_demo.c"

# Функция, на которой находка ОБЯЗАНА быть.
MUST_FIND = "collapsing_sum"
# Функции, на которых находок быть НЕ ДОЛЖНО (каждая — измеренная ловушка).
MUST_BE_CLEAN = ("guarded_sum", "promoted_sum", "wide_sum", "wrapping_sum")


def run_demo() -> tuple[dict[str, int], str]:
    """Прогон `--xray` на эталоне. Возвращает ({функция: находок}, вывод).

    Эталон копируется в ОТДЕЛЬНЫЙ временный каталог: `--xray` берёт каталог, а
    `examples/` содержит десятки других файлов, и их находки попали бы в счёт
    (ИЗМЕРЕНО: `contracts_demo.rs: double_it` даёт законную находку и ломала бы
    «неожиданные функции»). Гейт обязан судить РОВНО по эталону.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / DEMO.name
        dst.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        r = subprocess.run([PY, str(KERN_CONTRACTS), "--xray", td],
                           cwd=str(ROOT), capture_output=True, text=True,
                           timeout=900)
    out = r.stdout + r.stderr
    hits: dict[str, int] = {}
    for m in re.finditer(r"\[OVERFLOW PATH\]\s+(\w+):", out):
        hits[m.group(1)] = hits.get(m.group(1), 0) + 1
    return hits, out


def verdict(hits: dict[str, int]) -> list[str]:
    """Список нарушений. Пустой = гейт зелёный."""
    bad: list[str] = []
    n = hits.get(MUST_FIND, 0)
    if n == 0:
        bad.append(f"ПРОПУСК: на `{MUST_FIND}` находки НЕТ, а переполнение "
                   f"`2147483647 + 1` внутри выражения обязано быть найдено")
    elif n > 1:
        bad.append(f"ДУБЛИКАТЫ: на `{MUST_FIND}` находок {n} (ожидалась 1)")
    for fn in MUST_BE_CLEAN:
        if hits.get(fn, 0):
            bad.append(f"ЛОЖНОЕ ОБВИНЕНИЕ: `{fn}` объявлена переполняющейся "
                       f"({hits[fn]} раз), а она БЕЗОПАСНА по стандарту C")
    extra = set(hits) - {MUST_FIND} - set(MUST_BE_CLEAN)
    if extra:
        bad.append(f"НЕОЖИДАННЫЕ ФУНКЦИИ в находках: {sorted(extra)}")
    return bad


def selftest() -> int:
    """Мета-тест: гейт обязан ловить КАЖДЫЙ из классов поломки."""
    bad = 0
    ok = {MUST_FIND: 1}

    if verdict(dict(ok)) != []:
        print("[FAIL] selftest: здоровый набор НЕ проходит")
        bad += 1
    else:
        print("[OK] selftest: здоровый набор проходит")

    if not verdict({}):
        print("[FAIL] selftest: ПРОПУСК находки НЕ пойман")
        bad += 1
    else:
        print("[OK] selftest: пропуск находки ловится")

    if not verdict(dict(ok, promoted_sum=2)):
        print("[FAIL] selftest: ложное обвинение НЕ поймано")
        bad += 1
    else:
        print("[OK] selftest: ложное обвинение ловится")

    if not verdict({MUST_FIND: 3}):
        print("[FAIL] selftest: дубликаты НЕ пойманы")
        bad += 1
    else:
        print("[OK] selftest: дубликаты ловятся")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] xray-overflow selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="--xray: переполнение в выражении")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.selftest:
        return selftest()
    if not DEMO.exists():
        print(f"[FAIL] нет эталона {DEMO}")
        return 1

    print("=" * 76)
    print("KERN: `--xray` — переполнение ВНУТРИ выражения (дефект #367)")
    print("=" * 76)
    print(f"  эталон: {DEMO.relative_to(ROOT)}")
    hits, out = run_demo()
    for fn in (MUST_FIND,) + MUST_BE_CLEAN:
        mark = "НАХОДКА" if hits.get(fn) else "чисто"
        print(f"  {fn:<16} {mark}")
    bad = verdict(hits)
    print("-" * 76)
    if bad:
        for b in bad:
            print(f"[FAIL] {b}")
        return 1
    print(f"[OK] `{MUST_FIND}` найдена (переполнение внутри выражения), "
          f"{len(MUST_BE_CLEAN)} ловушек ложных обвинений чисты")
    return 0


if __name__ == "__main__":
    sys.exit(main())
