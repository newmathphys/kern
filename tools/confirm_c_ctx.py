#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Ступень №2 подтверждения C: компиляция С КОНТЕКСТОМ исходника.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. В Окне №34 попытка вписать эту логику в
`nightly_hunter.py` текстовой вставкой дважды ломала файл на экранировании
`\\n`. Тот же урок, что с `xray_none.py` в Окне №13: логика живёт в своём
модуле, движок вызывает две строки.

ЗАМОК ЧЕСТНОСТИ. `-Wl,--unresolved-symbols=ignore-in-object-files` оставляет
внешние функции из других `.c` нулевыми указателями, поэтому голый SIGSEGV
ничего не доказывает. Трофей — ТОЛЬКО строка `runtime error:` от UBSan.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HEADERS = ("stdint.h", "stddef.h", "stdbool.h", "limits.h", "stdlib.h", "math.h")


def _run(cmd: list, timeout: int = 300) -> tuple:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def build_wrapper(target: Path, fn: str, args: str) -> str:
    """repro.c: системные хедеры + сам исходник + вызов функции на модели Z3."""
    lines = ["#include <%s>" % h for h in HEADERS]
    lines.append('')
    lines.append('#include "%s"' % str(target.resolve()))
    lines.append('')
    # `-Dmain=__nh_orig_main` нужен, чтобы `main` САМОЙ цели не конфликтовал
    # с нашим. Но макрос действует на весь TU, поэтому возвращаем себе `main`.
    lines.append("#undef main")
    lines.append('')
    lines.append("int main(void) {")
    lines.append("    volatile long long r = (long long)(%s)(%s);" % (fn, args))
    lines.append("    (void)r;")
    lines.append("    return 0;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def repo_root_of(target: Path, manifests=()) -> Path:
    """Корень репозитория: первый предок с .git или с манифестом сборки."""
    for parent in target.resolve().parents:
        if (parent / ".git").exists():
            return parent
        if any((parent / m).exists() for m in manifests):
            return parent
    return target.resolve().parent


def confirm(target: Path, fn: str, args: str, work: Path, manifests=()) -> tuple:
    """Вернуть (строка_ubsan_или_None, причина)."""
    work.mkdir(parents=True, exist_ok=True)
    src = work / "ctx.c"
    src.write_text(build_wrapper(target, fn, args), encoding="utf-8")
    exe = work / "ctx.bin"
    root = repo_root_of(target, manifests)
    incs = []
    for d in (root, root / "include", root / "src", target.resolve().parent):
        incs += ["-I", str(d)]
    rc, out = _run(["gcc", "-O0", "-fsanitize=undefined", "-fno-sanitize-recover=all",
                    "-Dmain=__nh_orig_main", *incs,
                    "-Wl,--unresolved-symbols=ignore-in-object-files",
                    "-Wl,--warn-unresolved-symbols", "-lm",
                    str(src), "-o", str(exe)])
    if rc != 0:
        return None, "ctx: compile failed"
    rc, out = _run([str(exe)], timeout=30)
    if rc != 0 and "runtime error:" in out:
        line = next((l for l in out.splitlines() if "runtime error:" in l), "runtime error:")
        return line.strip()[:140], ""
    if rc != 0:
        return None, "ctx: crash without UBSan (unresolved symbol?)"
    return None, "ctx: no failure"
