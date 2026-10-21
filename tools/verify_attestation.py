#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""KERN: независимая проверка аттестата — ТОЛЬКО публичным ключом из репозитория.

ЗАЧЕМ (шаг 0K.2 плана). До этого проверка подписи жила в
`tools/slsa_provenance.py` и брала публичный ключ из `$HOME`
(`~/kern_owner_public.pem`). Значит проверить аттестат мог только владелец
машины: для внешнего аудитора «attestation ✓ Ed25519» было декорацией —
ключа в репозитории не было, инструкции тоже.

Этот скрипт отвечает на вопрос «чем подтверждается, что артефакт собран из
этого коммита», имея только репозиторий и OpenSSL. Он НИЧЕГО не пишет.

Проверки:
  1. публичный ключ найден (по умолчанию `docs/keys/kern-owner.pub`);
  2. подпись `kern.intoto.sig` найдена и читается как hex;
  3. Ed25519-подпись верна для `kern.intoto.jsonl`;
  4. `kid` в аттестате == SHA-256(DER) ключа из репозитория (0K.1);
  5. `attests_commit` == HEAD или HEAD~1; `dirtyTree == false`;
  6. `subject[].digest.sha256` совпадает с локальным `zig-out/bin/<name>`.

Код возврата: 0 — всё сошлось; 1 — расхождение; 2 — нет входных файлов.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ATT = ROOT / "kern.intoto.jsonl"
DEFAULT_SIG = ROOT / "kern.intoto.sig"
DEFAULT_PUB = ROOT / "docs" / "keys" / "kern-owner.pub"


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=False).stdout.strip()
    except OSError:
        return ""


def key_id(pub: Path) -> str:
    """Отпечаток ключа: SHA-256 от DER SubjectPublicKeyInfo (как в аттестате)."""
    r = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(pub),
                        "-outform", "DER"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return ""
    return "sha256:" + hashlib.sha256(r.stdout).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Проверить аттестат публичным ключом из репозитория.")
    ap.add_argument("--attestation", type=Path, default=DEFAULT_ATT)
    ap.add_argument("--sig", type=Path, default=DEFAULT_SIG)
    ap.add_argument("--pubkey", type=Path, default=DEFAULT_PUB)
    ap.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    ap.add_argument("--strict-binaries", action="store_true",
                    help="требовать локальный артефакт (иначе — предупреждение)")
    args = ap.parse_args()

    bad: list[str] = []
    warn: list[str] = []
    ok: list[str] = []

    # 1. Входные файлы.
    if not args.pubkey.exists():
        bad.append(f"нет публичного ключа {args.pubkey} — проверить нечем")
    if not args.attestation.exists():
        bad.append(f"нет аттестата {args.attestation}")
    if bad:
        print("[FAIL] " + "; ".join(bad))
        return 2

    stmt = json.loads(args.attestation.read_text(encoding="utf-8").splitlines()[0])
    kid_expected = key_id(args.pubkey)
    kid_actual = (stmt.get("predicate", {}).get("runDetails", {})
                  .get("builder", {}).get("kid"))

    # 2. Подпись: наличие и формат.
    sig_bytes = None
    if not args.sig.exists():
        bad.append("нет подписи kern.intoto.sig — аттестат без Ed25519 (0K.3)")
    else:
        try:
            sig_bytes = bytes.fromhex(
                re.sub(r"\s+", "", args.sig.read_text(encoding="utf-8")))
        except ValueError:
            bad.append("подпись не читается как hex")

    # 3. Криптографическая проверка.
    if sig_bytes is not None:
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(sig_bytes)
            sp = tf.name
        try:
            r = subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin",
                                "-pubin", "-inkey", str(args.pubkey),
                                "-in", str(args.attestation), "-sigfile", sp],
                               capture_output=True)
        finally:
            Path(sp).unlink(missing_ok=True)
        if r.returncode == 0:
            ok.append(f"Ed25519-подпись верна ({args.pubkey.name})")
        else:
            bad.append("Ed25519-подпись НЕВЕРНА — файл подменён")

    # 4. Привязка ключа (kid).
    if not kid_actual:
        bad.append("в аттестате нет kid — переподпишите (make seal) [0K.1]")
    elif kid_actual != kid_expected:
        bad.append(f"kid {kid_actual[:24]}… != отпечаток ключа {kid_expected[:24]}…")
    else:
        ok.append(f"kid совпадает с ключом ({kid_actual[:20]}…)")

    # 5. Коммит и чистота дерева.
    meta = stmt.get("predicate", {}).get("runDetails", {}).get("metadata", {})
    att = meta.get("attests_commit")
    head, parent = git("rev-parse", "HEAD"), git("rev-parse", "HEAD~1")
    if not att:
        bad.append("нет attests_commit — аттестат старого формата")
    elif att == head:
        ok.append(f"attests_commit == HEAD ({att[:12]})")
    elif att == parent:
        ok.append(f"attests_commit == HEAD~1 ({att[:12]}) — двухшаговая схема")
    else:
        bad.append(f"attests_commit {att[:12]} не совпадает ни с HEAD, ни с HEAD~1")
    if meta.get("dirtyTree") is True:
        bad.append("dirtyTree = true: аттестат собран на грязном дереве")
    elif meta.get("dirtyTree") is False:
        ok.append("dirtyTree = false")

    # 6. Артефакты.
    for subj in stmt.get("subject", []):
        name = subj.get("name", "?")
        want = subj.get("digest", {}).get("sha256", "")
        local = ROOT / "zig-out" / "bin" / name
        if local.exists():
            got = sha256_file(local)
            if got == want:
                ok.append(f"{name}: sha256 совпал")
            else:
                bad.append(f"{name}: sha256 {got[:16]}… != {want[:16]}…")
        elif args.strict_binaries:
            bad.append(f"{name}: локального файла нет (--strict-binaries)")
        else:
            warn.append(f"{name}: локального файла нет — артефакт не проверен")

    if args.json:
        print(json.dumps({"ok": ok, "warnings": warn, "failures": bad,
                          "kid": kid_actual, "attests_commit": att,
                          "head": head}, ensure_ascii=False, indent=2))
    else:
        for line in ok:
            print(f"  [OK]   {line}")
        for line in warn:
            print(f"  [i]    {line}")
        for line in bad:
            print(f"  [FAIL] {line}")
        print("\nАТТЕСТАТ ПРОВЕРЕН (внешним ключом)" if not bad
              else f"\nАТТЕСТАТ НЕ ПРОШЁЛ: {len(bad)} расхождений")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
