#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zig-native мутационное тестирование (аналог cargo-mutants для Zig).

Вносит по ОДНОЙ мутации в исходники ядра, прогоняет `zig test src/test_root.zig`
и классифицирует мутанта:
  KILLED   — тесты/компиляция поймали (хорошо);
  SURVIVED — мутант выжил (ДЫРА в тестах).

Mutation Score = KILLED / TOTAL * 100%.
Пропускает блоки `test { ... }` и строковые литералы (иначе — шум).
"""
import argparse
import os
import random
import re
import subprocess

TARGETS = [
    "src/core/eq2.zig",
    "src/core/object_entry.zig",
    "src/core/kimg_reader.zig",
    "src/core/kernfs_router.zig",
    "src/verifier/admission_gate.zig",
    "src/core/kimg_writer.zig",
]

MUTATIONS = [
    (r" != ", " == ", "!=->=="),
    (r" == ", " != ", "==->!="),
    (r" <= ", " < ", "<=-<"),
    (r" >= ", " > ", ">=->>"),
    (r" \| ", " & ", "|->&"),
    (r" & ", " | ", "&->|"),
    (r"\band\b", "or", "and->or"),
    (r"\bor\b", "and", "or->and"),
    (r"\btrue\b", "false", "true->false"),
    (r"\bfalse\b", "true", "false->true"),
]

BOOL_MUTS = ("true->false", "false->true")


def collect(root):
    """Сайты мутации; пропускаем блоки `test { }` и строковые литералы."""
    sites = []
    for rel in TARGETS:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        lines = open(path, encoding="utf-8").read().split("\n")
        in_test = False
        depth = 0
        seen_brace = False
        for ln, line in enumerate(lines):
            if not in_test and re.match(r"\s*test\s", line):
                in_test = True
                depth = 0
                seen_brace = False
            if in_test:
                depth += line.count("{") - line.count("}")
                if "{" in line:
                    seen_brace = True
                if seen_brace and depth <= 0:
                    in_test = False
                continue
            if line.lstrip().startswith("//"):
                continue
            for pat, rep, name in MUTATIONS:
                if not re.search(pat, line):
                    continue
                if name in BOOL_MUTS and '"' in line:
                    continue
                sites.append((rel, ln, pat, rep, name))
    return sites


def run_tests(root):
    p = subprocess.run(["zig", "test", "src/test_root.zig"], cwd=root,
                       capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        return "SURVIVED", out
    if "error:" in out and "FAIL" not in out and "expected" not in out:
        return "KILLED_COMPILE", out
    return "KILLED_TEST", out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    sites = collect(root)
    print(f"[i] найдено сайтов мутации: {len(sites)}; берём не более {args.max}", flush=True)
    random.seed(args.seed)
    if len(sites) > args.max:
        sites = random.sample(sites, args.max)

    killed = survived = kc = kt = 0
    survivors = []
    for idx, (rel, ln, pat, rep, name) in enumerate(sites, 1):
        path = os.path.join(root, rel)
        orig = open(path, encoding="utf-8").read()
        lines = orig.split("\n")
        lines[ln] = re.sub(pat, rep, lines[ln], count=1)
        try:
            open(path, "w", encoding="utf-8").write("\n".join(lines))
            status, _ = run_tests(root)
        finally:
            open(path, "w", encoding="utf-8").write(orig)
        if status == "SURVIVED":
            survived += 1
            survivors.append(f"{rel}:{ln+1} [{name}]")
            mark = "SURVIVED ❌"
        else:
            killed += 1
            kc += 1 if status == "KILLED_COMPILE" else 0
            kt += 1 if status != "KILLED_COMPILE" else 0
            mark = "killed ✅"
        print(f"  [{idx}/{len(sites)}] {rel}:{ln+1} [{name}] -> {mark}", flush=True)

    total = killed + survived
    score = (killed / total * 100.0) if total else 0.0
    print("\n=== МУТАЦИОННОЕ ТЕСТИРОВАНИЕ KERN ===")
    print(f"Всего мутантов:      {total}")
    print(f"Killed (compile):    {kc}")
    print(f"Killed (test):       {kt}")
    print(f"Survived (ДЫРЫ):     {survived}")
    print(f"MUTATION SCORE:      {score:.1f}%")
    if survivors:
        print("Выжившие мутанты (усилить тесты):")
        for s in survivors:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
