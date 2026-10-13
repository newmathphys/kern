#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""
KERN: мигратор Zig 0.13 -> 0.17 (оператор повтора `**`).

В Zig 0.17.0 оператор `**` (повтор массива/строки) УДАЛЁН.
Замена: `[_]T{v} ** N`  ->  `@as([N]T, @splat(v))`
        `"c" ** N`      ->  `@as([N]u8, @splat('c'))`

Правила:
  * правки ТОЛЬКО в коде (комментарии `//`, `//!`, `///` не трогаются);
  * если строка содержит `**` до начала комментария — это код;
  * поддерживаются размеры-выражения: `(128 + 16)`, `N`, числа.

Запуск:
    python3 tools/migrate_017.py --dry-run   # показать план
    python3 tools/migrate_017.py --apply     # применить
"""
import argparse
import os
import re
import sys

# `[_]u8{0x5A} ** 8192`  или  `[_]u8{0} ** (128 + 16)`  (числа с `_`: 10_000)
ARR = re.compile(r"\[_\](\w+)\{([^}]*)\}\s*\*\*\s*(\([^()]*\)|[\d_]+|[A-Za-z_][\w.]*)")
# `"x" ** 200` (односимвольный литерал)
STR = re.compile(r'"([^"\\])"\s*\*\*\s*(\([^()]*\)|[\d_]+)')

SKIP_DIRS = {".git", ".zig-cache", "zig-out", ".venv", ".venv38",
             ".venv-evalplus", "node_modules", "archive", "docs"}


def is_code_part(line: str) -> str:
    """Возвращает часть строки до комментария (если `//` вне литерала)."""
    in_str = False
    in_chr = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif in_chr:
            if c == "\\":
                i += 2
                continue
            if c == "'":
                in_chr = False
        else:
            if c == '"':
                in_str = True
            elif c == "'":
                in_chr = True
            elif c == "/" and i + 1 < len(line) and line[i + 1] == "/":
                return line[:i]
        i += 1
    return line


def convert(code: str):
    """Заменяет `**` в коде. Возвращает (новый_код, счётчик)."""
    n = 0

    def arr_sub(m):
        nonlocal n
        elem, val, size = m.group(1), m.group(2).strip(), m.group(3)
        n += 1
        return f"@as([{size}]{elem}, @splat({val}))"

    def str_sub(m):
        nonlocal n
        ch, size = m.group(1), m.group(2)
        n += 1
        return f"@as([{size}]u8, @splat('{ch}'))"

    code = ARR.sub(arr_sub, code)
    code = STR.sub(str_sub, code)
    return code, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("root", nargs="?", default=".")
    args = ap.parse_args()

    total_files = 0
    total_sites = 0
    for dirpath, dirnames, filenames in os.walk(args.root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".zig"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            changed = False
            for i, line in enumerate(lines):
                code = is_code_part(line)
                if "**" not in code:
                    continue
                new_code, n = convert(code)
                if n:
                    lines[i] = line.replace(code, new_code, 1)
                    changed = True
                    total_sites += n
                    print(f"  {path}:{i + 1}: {n} сайт(ов)")
            if changed:
                total_files += 1
                if args.apply:
                    with open(path, "w", encoding="utf-8") as f:
                        f.writelines(lines)

    mode = "ПРИМЕНЕНО" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] файлов: {total_files}, сайтов: {total_sites}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
