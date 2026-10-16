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
import hashlib
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

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
            # 🔴 ДЕФЕКТ (исправлен): мутация внутри ХВОСТОВОГО комментария
            # (`PayloadTampered, // SHA-256 != digest`) ничего не меняет в
            # поведении, но раньше попадала в отчёт как «выживший мутант» —
            # ложная «дыра в тестах». Отрезаем часть строки после `//`.
            code = line.split("//", 1)[0]
            for pat, rep, name in MUTATIONS:
                if not re.search(pat, code):
                    continue
                if name in BOOL_MUTS and '"' in code:
                    continue
                sites.append((rel, ln, pat, rep, name))
    return sites


def run_tests(root):
    # Zig 0.17: `compat` — ИМЕНОВАННЫЙ модуль, поэтому прямой `zig test
    # src/test_root.zig` не соберётся («no module named 'compat'»). Передаём
    # зависимость флагами `--dep compat -Mcompat=...`.
    p = subprocess.run(
        ["zig", "test", "--dep", "compat",
         "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig"],
        cwd=root, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        return "SURVIVED", out
    if "error:" in out and "FAIL" not in out and "expected" not in out:
        return "KILLED_COMPILE", out
    return "KILLED_TEST", out


def tree_hash(root):
    """Хэш всех файлов src/ — для проверки, что оригинал НЕ изменён."""
    h = hashlib.sha256()
    for dirpath, _, files in os.walk(os.path.join(root, "src")):
        for f in sorted(files):
            if not f.endswith(".zig"):
                continue
            p = os.path.join(dirpath, f)
            h.update(os.path.relpath(p, root).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


# 🔴 ДЕФЕКТ #88b (исправлен): раньше замок был ФАЙЛОМ с PID (`.mutation.lock`),
# а `tools/canfail.py` использует `fcntl.flock`. Два РАЗНЫХ механизма не мешали
# мутатору и харнессу идти ВНАХЛЁСТ: `measure_all_kern.py` запускает мутатор
# внутри телеметрии, и если в этот момент стартует canfail, оба патчат одни и
# те же исходники — свидетельства становятся ЛОЖНЫМИ.
#
# Теперь ОБА инструмента берут ОДИН И ТОТ ЖЕ flock. Ядро снимает его даже при
# SIGKILL, поэтому класс «мёртвый замок блокирует навсегда» (дефект #50)
# невозможен по построению.
SHARED_LOCK = "/tmp/kern_mutation.lock"
_lock_holder = []  # держим ссылку: иначе GC закроет fd и снимет flock


def acquire_lock(root):
    """Эксклюзивная блокировка прогона (ОБЩАЯ с canfail.py).

    Мутации идут ТОЛЬКО в копии дерева (см. main), а параллельный запуск
    (в том числе из телеметрии) блокируется общим flock.
    """
    import fcntl
    f = open(SHARED_LOCK, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        print("[!] уже идёт мутационный прогон или canfail (общий замок занят).",
              file=sys.stderr)
        print("    Дождитесь завершения — параллельные прогоны искажают исходники.",
              file=sys.stderr)
        sys.exit(2)
    f.write(str(os.getpid()))
    f.flush()
    _lock_holder.append(f)  # без ссылки GC закроет fd и снимет замок
    return f


def release_lock(lock_obj):
    try:
        import fcntl
        fcntl.flock(lock_obj, fcntl.LOCK_UN)
        lock_obj.close()
    except Exception:
        pass


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

    # БЛОКИРОВКА + СНИМОК ХЭША: гарантия, что оригинал не тронут.
    lock_path = acquire_lock(root)
    before = tree_hash(root)

    # РАБОЧАЯ КОПИЯ: мутации вносятся ТОЛЬКО сюда. Оригинальное дерево
    # не открывается на запись ни разу за весь прогон.
    work = tempfile.mkdtemp(prefix="kern-mutants-")
    try:
        shutil.copytree(os.path.join(root, "src"), os.path.join(work, "src"))
        # zig может искать build.zig — копируем, если есть.
        for extra in ("build.zig", "build.zig.zon"):
            src = os.path.join(root, extra)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(work, extra))

        print(f"[i] рабочая копия: {work} (оригинал не изменяется)", flush=True)

        killed = survived = kc = kt = 0
        survivors = []
        for idx, (rel, ln, pat, rep, name) in enumerate(sites, 1):
            path = os.path.join(work, rel)
            orig = open(path, encoding="utf-8").read()
            lines = orig.split("\n")
            lines[ln] = re.sub(pat, rep, lines[ln], count=1)
            try:
                open(path, "w", encoding="utf-8").write("\n".join(lines))
                status, _ = run_tests(work)
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
    finally:
        shutil.rmtree(work, ignore_errors=True)
        release_lock(lock_path)

    # КОНТРОЛЬ ЦЕЛОСТНОСТИ ОРИГИНАЛА.
    after = tree_hash(root)
    if before != after:
        print("\n[!!] КРИТИЧНО: исходники изменились во время прогона! "
              "Проверьте `git status`.", file=sys.stderr)
    else:
        print(f"\n[i] целостность оригинала подтверждена (sha256 {before[:16]}…)")

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
