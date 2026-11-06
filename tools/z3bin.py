#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""KERN: доступ к БИНАРНОМУ решателю z3 (БЕЗ python-пакета `z3-solver`).

ЗАЧЕМ ЭТОТ МОДУЛЬ. Гейты `arith-semantics-check`, `lang-semantics-check` и
`arith-zig-ref-check` делали `import z3` и падали с `ModuleNotFoundError`,
когда их запускали СИСТЕМНЫМ `python3` (`Makefile`: `PYTHON ?= python3`), хотя
бинарник `.venv/bin/z3` в репозитории ЕСТЬ. Пакет `z3-solver` не является
зависимостью рантайма — зависимостью является БИНАРНИК. Здесь решатель
вызывается КАК ПРОЦЕСС (как в `tools/proof_checker.py`), поэтому `RC=0`
получается и под `python3`, и под `.venv/bin/python`.

ЧЕСТНАЯ ГРАНИЦА. Если бинарника нет ни в `$Z3`, ни в `.venv/bin/z3`, ни в
`PATH` — функции возвращают `None`, и ВЫЗЫВАЮЩИЙ ОБЯЗАН трактовать это как
«проверка НЕ выполнена» (класс #277: N выдан за T), а не как «зелено».
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# #494: единый источник путей (этот файл живёт ВНУТРИ tools/).
import env_resolver
ROOT = env_resolver.HOST_ROOT


def find_z3() -> str | None:
    """Путь к бинарному z3: `$Z3` -> `.venv/bin/z3` -> `PATH` (иначе None)."""
    env = os.environ.get("Z3")
    if env and Path(env).exists():
        return env
    local = ROOT / ".venv" / "bin" / "z3"
    if local.exists():
        return str(local)
    return shutil.which("z3")


def _run(script: str, timeout: int = 60) -> str | None:
    """Прогнать SMT-скрипт через бинарный z3 (`z3 -in`). None — решателя нет."""
    exe = find_z3()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-in"], input=script, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None
    return (r.stdout or "") + (r.stderr or "")


def eval_int(expr: str) -> int | None:
    """Значение ЗАМКНУТОГО SMT-терма `expr` (теория Int). None — не вычислить.

    Формат ответа z3: `((r (- 7)))` для отрицательных и `((r 7))` для прочих.
    """
    out = _run("(set-logic ALL)\n(declare-const r Int)\n"
               f"(assert (= r {expr}))\n(check-sat)\n(get-value (r))\n")
    if out is None:
        return None
    # z3 печатает отрицательные как `(- 7)` (минус и цифра РАЗДЕЛЕНЫ пробелом),
    # неотрицательные — как `7`. Оба вида обязаны разбираться (дефект шага 0).
    m = re.search(r"\(\(r\s+\(?\s*(-?\s*\d+)\s*\)?\)\)", out)
    return int(m.group(1).replace(" ", "")) if m else None


def eval_int_many(exprs: list[str]) -> list[int | None]:
    """ПАКЕТНАЯ оценка термов в ОДНОМ процессе z3 (амортизация запуска).

    ЗАЧЕМ. Запуск решателя — ~15 мс. Сетки гейтов (`arith-semantics-check`,
    `arith-zig-ref-check`) требуют тысячи вычислений, поэтому по-термовый
    процесс давал минуты и таймаут. Здесь ВСЕ термы уходят в один `z3 -in`.

    Возвращает список той же длины: элемент `None` — терм не вычислить
    (нет решателя / ошибка разбора). Честная граница: `None` НЕ «ноль».
    """
    if not exprs:
        return []
    exe = find_z3()
    if not exe:
        return [None] * len(exprs)
    lines = ["(set-logic ALL)"]
    for i, e in enumerate(exprs):
        lines.append(f"(declare-const r{i} Int)")
        lines.append(f"(assert (= r{i} {e}))")
    names = " ".join(f"r{i}" for i in range(len(exprs)))
    lines.append("(check-sat)")
    lines.append(f"(get-value ({names}))")
    try:
        r = subprocess.run([exe, "-in"], input="\n".join(lines) + "\n",
                           capture_output=True, text=True, errors="replace",
                           timeout=120)
    except (subprocess.SubprocessError, OSError):
        return [None] * len(exprs)
    out = (r.stdout or "") + (r.stderr or "")
    res: list[int | None] = [None] * len(exprs)
    # Ответ: `((r0 7) (r1 (- 4)) ...)`; отрицательные — со ПРОБЕЛОМ `(- 4)`.
    for m in re.finditer(r"\br(\d+)\s+(\(\s*-\s*\d+\s*\)|-?\s*\d+)", out):
        idx = int(m.group(1))
        if 0 <= idx < len(res):
            res[idx] = int(m.group(2).replace("(", "").replace(")", "")
                           .replace(" ", ""))
    return res


def is_sat(body: str) -> bool | None:
    """True, если SMT-скрипт `body` (без `check-sat`) ВЫПОЛНИМ. None — не решить."""
    out = _run("(set-logic ALL)\n" + body + "\n(check-sat)\n")
    if out is None:
        return None
    for line in out.splitlines():
        token = line.strip()
        if token == "sat":
            return True
        if token == "unsat":
            return False
    return None


if __name__ == "__main__":  # мини-самопроверка модуля
    import sys
    if find_z3() is None:
        print("[!] бинарный z3 не найден ($Z3 / .venv/bin/z3 / PATH)")
        sys.exit(2)
    assert eval_int("(- 7)") == -7, eval_int("(- 7)")
    assert eval_int("(div (- 7) 2)") == -4      # SMT div — ЕВКЛИДОВА (floor)
    assert is_sat("(declare-const x Int)(assert (> x 5))(assert (< x 2))") is False
    assert is_sat("(declare-const x Int)(assert (> x 5))") is True
    print("[OK] z3bin: eval_int и is_sat работают через бинарный решатель")
