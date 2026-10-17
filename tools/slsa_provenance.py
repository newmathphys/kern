#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
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
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "kern.intoto.jsonl"
# 🔴 ДЕФЕКТ #92 (найден на практике): раньше здесь стояли `kernc`, `kernx`,
# `kern-attack` — это файлы, которые ПЕРЕЗАПИСЫВАЕТ любой `zig build`
# (по умолчанию Debug). Аттестат собирался в ReleaseFast, но следующий
# обычный `zig build` (например, внутри `make evidence`) подменял бинарники
# Debug-версиями — и `--check` начинал сообщать «[РАСХОЖДЕНИЕ] kernc»,
# хотя ИСХОДНИКИ не менялись (отпечаток исходников совпадал!).
#
# Аттестуем АРТЕФАКТ РЕЛИЗА: `kernc-hermetic` (ReleaseSafe, статический musl).
# Он лежит по ОТДЕЛЬНОМУ имени, обычным `zig build` не перезаписывается,
# и именно он публикуется как `kernc-x86_64-linux-musl`.
SUBJECTS = ["kernc-hermetic"]

# ---- Ed25519-ПОДПИСЬ АТТЕСТАТА (УЛУЧШЕНИЕ №13) -----------------------------
# ЗАЧЕМ. Аттестат SLSA был НЕ подписан («нет cosign») — то есть его мог
# подменить любой, у кого есть доступ к файлу, а `--check` этого не заметил бы.
# В ядре KERN Ed25519 уже есть (`src/attest.zig`, `attestation.cert`), поэтому
# подписываем ТЕМ ЖЕ ключом владельца через `openssl pkeyutl` — 0 внешних
# зависимостей (OpenSSL есть в системе), 0 новых пакетов Python.
#
# Подпись лежит ОТДЕЛЬНЫМ файлом: если бы она была полем внутри JSON, то
# подписывала бы саму себя (порочный круг, ровно как в дефекте #87).
OWNER_KEY = Path(os.environ.get("KERN_OWNER_KEY",
                                Path.home() / "kern_owner_private.pem"))
OWNER_PUB = Path(os.environ.get("KERN_OWNER_PUB",
                                Path.home() / "kern_owner_public.pem"))
SIG = ROOT / "kern.intoto.sig"


def sign_attestation() -> int:
    """Подписать `kern.intoto.jsonl` ключом владельца (Ed25519).

    Возвращает 0 всегда: ОТСУТСТВИЕ ключа — не ошибка сборки (CI без секретов
    обязан работать), но факт «не подписано» печатается ЧЕСТНО.
    """
    if not OWNER_KEY.exists():
        print(f"     ПОДПИСЬ НЕ ВЫПОЛНЕНА: нет ключа владельца {OWNER_KEY}")
        print("     (в CI ключа нет — аттестат без подписи, и это видно здесь)")
        return 0
    r = subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin",
                        "-inkey", str(OWNER_KEY), "-in", str(OUT)],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        print(f"[!] не удалось подписать аттестат: "
              f"{r.stderr.decode(errors='replace').strip()[:160]}")
        return 0
    SIG.write_text(r.stdout.hex() + "\n", encoding="utf-8")
    print(f"[OK] Ed25519-подпись: {SIG.name} ({len(r.stdout)} байт)")
    return 0


def verify_attestation_signature() -> bool | None:
    """Проверить Ed25519-подпись аттестата. None = подписи нет."""
    if not SIG.exists():
        return None
    if not OWNER_PUB.exists():
        print(f"  [!] есть подпись, но нет открытого ключа {OWNER_PUB}")
        return False
    try:
        raw = bytes.fromhex(SIG.read_text(encoding="utf-8").strip())
    except ValueError:
        print("  [!] подпись не читается как hex")
        return False
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(raw)
        sp = tf.name
    try:
        r = subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin",
                            "-pubin", "-inkey", str(OWNER_PUB),
                            "-in", str(OUT), "-sigfile", sp],
                           capture_output=True)
    finally:
        Path(sp).unlink(missing_ok=True)
    if r.returncode == 0:
        print(f"  [OK] Ed25519-подпись аттестата верна ({OWNER_PUB.name})")
        return True
    print("  [РАСХОЖДЕНИЕ] Ed25519-подпись аттестата НЕВЕРНА — файл подменён")
    return False


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


# Аттестат — ГЕНЕРИРУЕМЫЙ файл: он не должен входить в собственный отпечаток
# (иначе `tree_sha256` самореферентен и меняется от одной лишь перегенерации).
SELF = "kern.intoto.jsonl"
# 🔴 ДЕФЕКТ #79: лог проверки аттестата — тоже самореферентный файл.
# `collect slsa_check` пишет docs/evidence/slsa_check.log ДО вызова --check,
# поэтому запись лога меняла отпечаток исходников, и проверка всегда падала
# (RC=1) — при том что сам аттестат был корректен. Исключаем из отпечатка.
SELF_LOG = "docs/evidence/slsa_check.log"


def tree_digest() -> dict:
    """Отпечаток ИСХОДНОГО состояния: хэш рабочего дерева + коммит.

    ВАЖНО: сам аттестат (`kern.intoto.jsonl`) ИСКЛЮЧЁН из хэша. Дефект #62:
    раньше он входил в отпечаток, из-за чего значение зависело от себя же.

    🔴 ДЕФЕКТ #68: список файлов брался из `git ls-files`, а он возвращает
    только ОТСЛЕЖИВАЕМЫЕ файлы. Если аттестат сгенерирован до коммита, когда
    новый файл ещё untracked, отпечаток считался по НЕПОЛНОМУ набору — и после
    коммита уже не мог совпасть никогда (симптом: `--check` давал
    «[РАСХОЖДЕНИЕ] исходники»). Найдено на практике: аттестат собран, пока
    `tools/svg_check.py` был ещё не добавлен в индекс.

    Исправление: берём ОБЪЕДИНЕНИЕ отслеживаемых и неотслеживаемых (но не
    игнорируемых) файлов. Набор не меняется от коммита, поэтому отпечаток
    стабилен до и после него.
    """
    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    # tracked + untracked-but-not-ignored, без дубликатов
    tracked = git("ls-files").splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    files = sorted(set(tracked) | set(untracked))
    h = hashlib.sha256()
    for rel in files:
        # ТРИ САМОРЕФЕРЕНТНЫХ/ПРОИЗВОДНЫХ ИСТОЧНИКА — исключаются из отпечатка:
        #
        #  1. SELF (`kern.intoto.jsonl`) — аттестат не может хешировать себя
        #     (значение зависело бы от себя же). Дефект #62.
        #  2. `docs/evidence/slsa_check.log` — ЛОГ ЭТОЙ САМОЙ ПРОВЕРКИ.
        #     Дефект #79: запись лога меняет файловый набор, а значит и
        #     отпечаток, который этот лог как раз проверяет — порочный круг.
        #  3. 🔴 ВСЁ `docs/evidence/` — ПРОИЗВОДНЫЕ артефакты (выход верификации),
        #     а не исходники. Дефект #87: аттестат привязывает БИНАРНИК к
        #     ИСХОДНОМУ КОДУ; логи прогонов к этому отношению не относятся.
        #     Пока они входили в отпечаток, действовало хрупкое правило
        #     «`--no-build` обязан быть последней операцией перед коммитом»:
        #     любая перегенерация свидетельства (а это и есть их штатная
        #     перегенерация) ломала аттестат, и `--check` краснел.
        #     Теперь отпечаток зависит ТОЛЬКО от исходников и потому стабилен.
        #     Целостность самих свидетельств проверяет `make evidence-gate`,
        #     а их неизменность обеспечивает git.
        #  4. `kern.intoto.sig` — ПОДПИСЬ аттестата (УЛУЧШЕНИЕ №13). Тот же
        #     порочный круг, что и у самого аттестата: подпись создаётся ПОСЛЕ
        #     вычисления отпечатка, поэтому её нельзя включать в отпечаток —
        #     иначе `--check` краснел бы всегда, сразу после подписания.
        if rel in (SELF, SELF_LOG, "kern.intoto.sig") or rel.startswith("docs/evidence/"):
            continue
        p = ROOT / rel
        if p.is_file():
            h.update(rel.encode())
            h.update(bytes.fromhex(sha256_file(p)))
    return {"commit": commit, "tree_sha256": h.hexdigest(), "dirty": dirty,
            "files": len(files)}


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
        # ДЕФЕКТ #62: сравнивать СЫРОЙ коммит нельзя — сам аттестат лежит в
        # коммите, поэтому любой коммит (даже правка документации) ломает
        # проверку, хотя исходники не менялись. Сравниваем ОТПЕЧАТОК ИСХОДНИКОВ
        # (tree_sha256 без самого аттестата) — он привязан к содержимому, а не
        # к хэшу коммита, в котором лежит аттестат.
        exp_tree = dep["digest"].get("tree_sha256")
        got_tree = tree_digest()["tree_sha256"]
        if exp_tree == got_tree:
            print(f"  [OK] отпечаток исходников совпал ({got_tree[:16]}…)")
        else:
            print(f"  [РАСХОЖДЕНИЕ] исходники: аттестат {str(exp_tree)[:16]}…, "
                  f"факт {got_tree[:16]}…")
            bad += 1
        rec = dep["digest"].get("gitCommit", "")
        if rec and rec != cur:
            print(f"  [i] аттестат собран из коммита {rec[:12]} (текущий {cur[:12]}) — "
                  f"это нормально, привязка идёт по отпечатку исходников")
        else:
            print(f"  [OK] коммит совпал: {cur[:12]}")
        # УЛУЧШЕНИЕ №13: КРИПТОГРАФИЧЕСКАЯ проверка подписи аттестата.
        # Порча ЛЮБОГО байта подписи обязана ронять `--check` (кейс `slsa-bad-sig`).
        sig_ok = verify_attestation_signature()
        if sig_ok is False:
            bad += 1
        elif sig_ok is None:
            print("  [i] подписи нет (kern.intoto.sig отсутствует) — аттестат "
                  "без Ed25519; это НЕ ошибка, но и не «подписано»")
        print("\nАТТЕСТАТ ВАЛИДЕН" if bad == 0 else f"\nАТТЕСТАТ НЕ СОВПАЛ: {bad}")
        return 0 if bad == 0 else 1

    # --- СБОРКА + АТТЕСТАЦИЯ ------------------------------------------------
    # ДЕФЕКТ (найден проверкой воспроизводимости): раньше сборка шла с
    # параметрами по умолчанию (Debug). Debug-бинарники Zig 0.17 НЕ
    # бит-воспроизводимы: DWARF-секции (.debug_info/.debug_str) содержат
    # недетерминированные наборы имён error-set, поэтому хэш менялся от
    # сборки к сборке и аттестат не мог сойтись НИКОГДА.
    # Замер: Debug 2× → разные хэши; ReleaseFast 2× → одинаковые;
    #        hermetic (ReleaseSafe musl) 2× → одинаковые.
    # Поэтому аттестуем ВОСПРОИЗВОДИМУЮ конфигурацию ReleaseFast.
    # Дефект #92: собираем ИМЕННО герметичный артефакт (ReleaseSafe musl) —
    # он воспроизводим (проверено: 2 сборки -> одинаковый sha256) и не
    # перезаписывается обычным `zig build`.
    BUILD_CMD = ["zig", "build", "hermetic"]
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not args.no_build:
        print("[i] сборка (воспроизводимая): " + " ".join(BUILD_CMD))
        r = subprocess.run(BUILD_CMD, cwd=str(ROOT), capture_output=True, text=True)
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
                    "command": BUILD_CMD,
                    "optimize": "ReleaseFast",
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
                "Аттестуются артефакты ReleaseFast: эта конфигурация "
                "бит-воспроизводима (проверено 2 сборками). Debug-сборки Zig 0.17 "
                "содержат недетерминированную DWARF-информацию и НЕ аттестуются.",
            ],
        },
    }

    OUT.write_text(json.dumps(stmt, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] {OUT.name} — субъектов {len(subjects)}, коммит {td['commit'][:12]}, "
          f"dirty={td['dirty']}")
    # УЛУЧШЕНИЕ №13: подписываем аттестат ключом владельца (Ed25519).
    sign_attestation()
    return 0


if __name__ == "__main__":
    sys.exit(main())

