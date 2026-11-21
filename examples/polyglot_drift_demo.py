#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Polyglot drift: Python-валидатор говорит «безопасно», C-парсер переполняется.

Сценарий (класс Request Smuggling / buffer overflow на стыке языков):
  * API-шлюз на Python проверяет `count * stride <= MAX_BUF` в длинной
    арифметике — для него произведение честное и «помещается»;
  * парсер на C считает `int32_t bytes = count * stride;` — 32-битное
    произведение молча переполняется и даёт совсем другое число.

Скрипт находит точку расхождения прямым перебором по формуле (арифметика
точная, никакой эвристики), компилирует C-код через `gcc -O2` и показывает
живой вывод обеих сторон.

Честная рамка: это МОДЕЛЬ стыка, а не эксплойт против конкретного продукта.
Мы не пишем за границу буфера — только сравниваем длины, которые каждая
сторона считает «правильными».

Запуск: python3 examples/polyglot_drift_demo.py   (rc=0 при успехе)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

STRIDE = 4
MAX_BUF = 1 << 40            # сколько шлюз вообще готов пропустить
INT32_MAX = (1 << 31) - 1

C_SOURCE = r"""
#include <stdio.h>
#include <stdint.h>

int main(void) {
    const int64_t count = 536870912LL;    /* 2^29 */
    const int64_t stride = 4;
    int32_t bytes = (int32_t)(count * stride);   /* 32-битное произведение */
    printf("c: count=%lld stride=%lld bytes=%d\n",
           (long long)count, (long long)stride, (int)bytes);
    return 0;
}
"""


def python_validator(count: int, stride: int) -> bool:
    """То, что делает шлюз: длинная арифметика, границы честные."""
    return count * stride <= MAX_BUF


def find_divergence() -> tuple:
    """Первая точка, где Python говорит «безопасно», а int32 не вмещает."""
    count = (INT32_MAX // STRIDE) + 1        # первое count, где произведение > INT32_MAX
    while count * STRIDE <= MAX_BUF:
        product = count * STRIDE
        wrapped = product & 0xFFFFFFFF        # как int32_t в C
        if wrapped >= 1 << 31:
            wrapped -= 1 << 32
        if wrapped != product:
            return count, STRIDE, product, wrapped
        count *= 2
    raise AssertionError("точка расхождения не найдена")


def main() -> int:
    ok = True

    def check(cond: bool, label: str) -> None:
        nonlocal ok
        print(("[OK]   " if cond else "[FAIL] ") + label)
        if not cond:
            ok = False

    count, stride, product, wrapped = find_divergence()
    print(f"точка расхождения: count={count} stride={stride}")
    print(f"  Python: {count} * {stride} = {product} (<= MAX_BUF) -> безопасно")
    print(f"  C int32: {product} -> {wrapped} байт")

    check(python_validator(count, stride), "Python-валидатор пропускает пакет")
    check(wrapped != product, "C-сторона получает другое число байт")
    check(wrapped < product // 2, "C-сторона выделяет кардинально меньше, чем проверено")

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "parser.c"
        exe = Path(tmp) / "parser"
        src.write_text(C_SOURCE, encoding="utf-8")
        build = subprocess.run(["gcc", "-O2", str(src), "-o", str(exe)],
                               capture_output=True, text=True)
        check(build.returncode == 0, "C-парсер собрался через gcc -O2")
        if build.returncode == 0:
            out = subprocess.run([str(exe)], capture_output=True, text=True).stdout.strip()
            print("  " + out)
            check("bytes=-2147483648" in out, "живой бинарник подтверждает переполнение")

    print("\nИТОГ: шлюз проверил длинную арифметику, парсер посчитал в int32 — "
          "одно и то же поле означает разные размеры.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
