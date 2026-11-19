#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""Спящая закладка против фаззера и против Z3: 100 000 прогонов слепы, SMT — нет.

Ветка закладки записана БЕЗ литералов >= 2^32: `user_id - 1000000 * 1000000 == 777`
и нечётный тег. Слепы и фаззер, и поиск больших констант в AST. Видит только SMT:
`tools/kern_contracts.py --diff-equiv` решает систему уравнений в QF_LIA.

Запуск: python3 examples/sleeper_backdoor_demo.py   (rc=0 при успехе)
"""
from __future__ import annotations

import ast, inspect, os, random, re, subprocess, sys, tempfile
from pathlib import Path

TRIGGER_USER = 1000000000777
TRIGGER_TAG = 1


def verify_access_reference(user_id: int, token_tag: int) -> int:
    if user_id <= 0:
        return 0
    if token_tag % 2 != 0:
        return 0
    return 1


def verify_access_refactored(user_id: int, token_tag: int) -> int:
    if user_id - 1000000 * 1000000 == 777 and token_tag % 2 != 0:
        return 1
    if user_id <= 0:
        return 0
    if token_tag % 2 != 0:
        return 0
    return 1


def fuzz(reference, candidate, iterations: int, seed: int = 20261119) -> int:
    rng = random.Random(seed)
    diffs = 0
    for _ in range(iterations):
        user_id = rng.randrange(1, 10 ** 6)
        token_tag = rng.randrange(0, 10 ** 6)
        if reference(user_id, token_tag) != candidate(user_id, token_tag):
            diffs += 1
    return diffs


def ast_literals(fn) -> set:
    tree = ast.parse(inspect.getsource(fn))
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, int)}


def diff_equiv(ref_src: str, bad_src: str):
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "ref.py", Path(tmp) / "bad.py"
        a.write_text(ref_src, encoding="utf-8")
        b.write_text(bad_src, encoding="utf-8")
        venv = sorted(root.glob(".venv/lib/*/site-packages"))
        if venv:
            env = dict(os.environ)
            env["PYTHONPATH"] = str(venv[0]) + (
                (":" + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
        else:
            env = None
        proc = subprocess.run(
            [sys.executable, str(root / "tools" / "kern_contracts.py"),
             "--diff-equiv", str(a), str(b)],
            capture_output=True, text=True, cwd=str(root), timeout=120, env=env)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("[OK]   " if cond else "[FAIL] ") + label)
        if not cond:
            ok = False

    diffs = fuzz(verify_access_reference, verify_access_refactored, 100_000)
    print("фаззер: 100 000 итераций -> расхождений %d" % diffs)
    check(diffs == 0, "фаззер не нашёл закладку (это и есть демонстрация)")

    big = {v for v in ast_literals(verify_access_refactored) if v >= 2 ** 32}
    print("AST-аудит: литералов >= 2^32 -> %d" % len(big))
    check(len(big) == 0, "поиск больших констант слеп (закладка собрана выражением)")

    ref_src = (
        "def verify_access(user_id: int, token_tag: int) -> int:\n"
        "    if user_id <= 0:\n"
        "        return 0\n"
        "    if token_tag % 2 != 0:\n"
        "        return 0\n"
        "    return 1\n"
    )
    bad_src = (
        "def verify_access(user_id: int, token_tag: int) -> int:\n"
        "    if user_id - 1000000 * 1000000 == 777 and token_tag % 2 != 0:\n"
        "        return 1\n"
        "    if user_id <= 0:\n"
        "        return 0\n"
        "    if token_tag % 2 != 0:\n"
        "        return 0\n"
        "    return 1\n"
    )
    rc, out = diff_equiv(ref_src, bad_src)
    diverged = "[DIVERGED]" in out
    print("--diff-equiv: %s" % ("[DIVERGED]" if diverged else "нет расхождения"))
    for line in out.splitlines():
        if "КОНТРПРИМЕР" in line:
            print("   " + line.strip())
    check(diverged, "Z3 нашёл расхождение там, где фаззер и AST слепы")

    m = re.search(r"_arg0 = (-?\d+), _arg1 = (-?\d+)", out)
    check(m is not None, "модель Z3 содержит конкретную пару входов")

    pair = (int(m.group(1)), int(m.group(2))) if m else (TRIGGER_USER, TRIGGER_TAG)
    got_ref = verify_access_reference(*pair)
    got_new = verify_access_refactored(*pair)
    print("живой вызов: %s -> эталон %d, рефакторинг %d" % (pair, got_ref, got_new))
    check(got_ref != got_new, "расхождение подтверждено исполнением")

    print("\nИТОГ: фаззер и AST-эвристика слепы; SMT на ветках находит точный вход.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
