#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`sema_probe` — ЖИВАЯ поведенческая проба двух версий одного файла (#508).

ЗАЧЕМ. `--xray` видит краши/UB/границы/ветви, но НЕ видит логический баг
(`return a + b` вместо `return a - b`): программа не падает, она тихо считает
другое. ИЗМЕРЕНО: на 40 парах QuixBugs `--diff-equiv` (Z3 по телам) даёт
`[UNKNOWN]` там, где тело содержит цикл (`_havoc_k`), а ЖИВОЙ вызов обеих
версий даёт расхождение на конкретном входе — ровно так `quixbugs_check._confirm`
и получает 40/40. Этот инструмент — та же идея, но для ПРОИЗВОЛЬНЫХ двух файлов,
чтобы её мог использовать `audit-delta`.

ЧТО ДЕЛАЕТ. Загружает OLD и NEW как модули, берёт одноимённые публичные функции,
вызывает их на ДЕТЕРМИНИРОВАННОЙ сетке входов (целые -2..10, до двух аргументов)
и печатает `[DIVERGED] <fn>: аргументы (...) -> old=… new=…` на ПЕРВОМ же
расхождении (значение ИЛИ исключение ИЛИ таймаут).

ГРАНИЦЫ (названы, не спрятаны):
  * сетка входов ОГРАНИЧЕНА: «расхождения нет» = «не найдено на этой сетке»;
  * функции с >2 аргументами и keyword-only не пробуются;
  * модуль, который не импортируется (нет зависимости, ввод-вывод, side effects
    на импорте) — НАЗВАННЫЙ пропуск `IMPORT_FAIL`, а не «эквивалентно»;
  * исполнение чужого кода — это то же, что делает `pytest`; вызов идёт под
    `signal.alarm` в ОТДЕЛЬНОМ процессе (его запускает вызывающий), поэтому
    зависание не вешает гейт.

Запуск:  python3 tools/sema_probe.py OLD.py NEW.py
Код возврата: 0 — расхождений не найдено (или сравнивать нечего);
              1 — найдено расхождение (печатается с контрпримером);
              2 — один из файлов не импортируется (названный пропуск).
"""
from __future__ import annotations

import importlib.util
import inspect
import itertools
import signal
import sys
from pathlib import Path

GRID = (-2, -1, 0, 1, 2, 3, 5, 10)
CALL_TIMEOUT_S = 5


class _Timeout(Exception):
    """Тело функции не уложилось в бюджет — это тоже расхождение поведения."""


def _load(path: str, modname: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"нет загрузчика для {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _call(fn, args: tuple):
    """Вызвать под таймером. Возвращает (успех, значение_или_метка)."""
    def _alarm(_sig, _frm):
        raise _Timeout()

    prev = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(CALL_TIMEOUT_S)
    try:
        return True, fn(*args)
    except _Timeout:
        return False, "TIMEOUT"
    except BaseException as e:                     # noqa: BLE001 — ЛЮБОЕ исключение
        # Здесь широкий перехват ОПРАВДАН и назван: исключение — это НАБЛЮДЕНИЕ
        # поведения (оно может отличаться между версиями), а не наша ошибка.
        return False, f"EXC:{type(e).__name__}"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 2:
        print("использование: sema_probe.py OLD.py NEW.py")
        return 2
    old_p, new_p = args
    try:
        mo, mn = _load(old_p, "sema_old"), _load(new_p, "sema_new")
    except BaseException as e:                      # noqa: BLE001 — пропуск назван
        print(f"[SKIP] IMPORT_FAIL: {type(e).__name__}: {e}")
        return 2
    found = 0
    for nm in sorted(dir(mo)):
        if nm.startswith("_"):
            continue
        fo = getattr(mo, nm)
        if not callable(fo) or inspect.isclass(fo):
            continue
        fn_new = getattr(mn, nm, None)
        if not callable(fn_new):
            continue
        try:
            params = list(inspect.signature(fo).parameters.values())
        except (TypeError, ValueError):
            continue
        if not params or len(params) > 2:
            continue
        if any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD, p.KEYWORD_ONLY) for p in params):
            continue
        for call_args in itertools.product(GRID, repeat=len(params)):
            ok_o, r_o = _call(fo, call_args)
            ok_n, r_n = _call(fn_new, call_args)
            if ok_o != ok_n or r_o != r_n:
                print(f"[DIVERGED] {nm}: аргументы {call_args} -> "
                      f"old={r_o!r} new={r_n!r}")
                found += 1
                break
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
