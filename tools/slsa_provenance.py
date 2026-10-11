#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""slsa_provenance.py — аттестат цепочки сборки (SLSA Provenance v1).

**Что делает.** Формирует `kern.intoto.jsonl` в формате in-toto Statement v1 /
SLSA Provenance v1: он связывает ХЭШ ГОТОВОГО БИНАРНИКА с ТОЧНЫМ состоянием
репозитория (git-коммит + хэш дерева) и командой сборки.

**Зачем.** Аудитор берёт бинарник и проверяет: собран ли он из этого коммита
этой командой — без доверия к сборщику.

**ЧЕСТНО О ГРАНИЦАХ:**
  • файл **НЕ ПОДПИСАН** — для SLSA L3/L4 нужна подпись (Sigstore/cosign),
    которой в окружении нет. Здесь корректный по структуре неподписанный
    attestation; подпись — внешний шаг.
  • `builder.id` = локальная сборка, а не доверенный CI (для L3 нужен хостируемый).
  • воспроизводимость подтверждается отдельно (`make hermetic`).

Запуск:
  python3 tools/slsa_provenance.py            # собрать и аттестовать
  python3 tools/slsa_provenance.py --check    # проверить соответствие
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "kern.intoto.jsonl"
SUBJECTS = ["kernc", "kernx", "kern-attack"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                              text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def tree_digest() -> dict:
    """Хэш содержимого репозитория: git-коммит + хэш рабочего дерева."""
    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    h = hashlib.sha256()
    for rel in sorted(git("ls-files").splitlines()):
        p = ROOT / rel
        if p.is_file():
            h.update(rel.encode())
            h.update(bytes.fromhex(sha256_file(p)))
    return {"commit": commit, "tree_sha256": h.hexdigest(), "dirty": dirty}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="проверить существующий аттестат")
    ap.add_argument("--no-build", action="store_true", help="не пересобирать")
    args = ap.parse_args()

    # --- ПРОВЕРКА -----------------------------------------------------------
    if args.check:
        if not OUT.exists():
            print(f"[!] нет {OUT} — сначала запустите без --check")
            return 1
        st = json.loads(OUT.read_text(encoding="utf-8").splitlines()[0])
        bad = 0
        for s in st["subject"]:
            p = ROOT / "zig-out" / "bin" / s["name"]
            if not p.exists():
                print(f"  [—] {s['name']}: бинарник отсутствует")
                bad += 1
                continue
            got = sha256_file(p)
            exp = s["digest"]["sha256"]
            if got == exp:
                print(f"  [OK] {s['name']}: sha256 совпал ({got[:16]}…)")
            else:
                print(f"  [РАСХОЖДЕНИЕ] {s['name']}: аттестат {exp[:16]}…, факт {got[:16]}…")
                bad += 1
        dep = st["predicate"]["buildDefinition"]["resolvedDependencies"][0]
        cur = git("rev-parse", "HEAD")
        if dep["digest"].get("gitCommit") == cur:
            print(f"  [OK] коммит совпал: {cur[:12]}")
        else:
            print(f"  [РАСХОЖДЕНИЕ] коммит: аттестат "
                  f"{dep['digest'].get('gitCommit','')[:12]}, факт {cur[:12]}")
            bad += 1
        print("\nАТТЕСТАТ ВАЛИДЕН" if bad == 0 else f"\nАТТЕСТАТ НЕ СОВПАЛ: {bad}")
        return 0 if bad == 0 else 1

    # --- СБОРКА + АТТЕСТАЦИЯ ------------------------------------------------
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not args.no_build:
        print("[i] сборка: zig build")
        r = subprocess.run(["zig", "build"], cwd=str(ROOT), capture_output=True, text=True)
        if r.returncode != 0:
            print("[!] сборка не удалась:", r.stderr[-300:])
            return 1
    finished = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    subjects = []
    for name in SUBJECTS:
        p = ROOT / "zig-out" / "bin" / name
        if p.exists():
            subjects.append({"name": name, "digest": {"sha256": sha256_file(p)}})
    if not subjects:
        print("[!] нет бинарников в zig-out/bin — соберите (zig build)")
        return 1

    td = tree_digest()
    stmt = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subjects,
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://kern.dev/buildtypes/zig-v1",
                "externalParameters": {
                    "command": ["zig", "build"],
                    "zig_version": (subprocess.run(["zig", "version"], capture_output=True,
                                                   text=True).stdout.strip() or "unknown"),
                    "targets": SUBJECTS,
                },
                "resolvedDependencies": [{
                    "uri": "git+https://github.com/newmathphys/kern",
                    "digest": {"gitCommit": td["commit"], "tree_sha256": td["tree_sha256"]},
                }],
            },
            "runDetails": {
                "builder": {"id": "local://kern-build"},
                "metadata": {
                    "invocationId": str(uuid.uuid4()),
                    "startedOn": started,
                    "finishedOn": finished,
                    "dirtyTree": td["dirty"],
                },
            },
            "kern:notes": [
                "ATTESTATION NOT SIGNED: cosign/sigstore недоступны в окружении.",
                "builder.id = local (для SLSA L3 требуется хостируемый билдер).",
                "Воспроизводимость: make hermetic (сборка бит-в-бит).",
            ],
        },
    }

    OUT.write_text(json.dumps(stmt, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] {OUT.name} — субъектов {len(subjects)}, коммит {td['commit'][:12]}, "
          f"dirty={td['dirty']}")
    print("     ПОДПИСЬ НЕ ВЫПОЛНЕНА (нет cosign) — честно записано в kern:notes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

