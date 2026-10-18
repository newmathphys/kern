#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
"""ЭШЕЛОН 2, ПУНКТ 9: PROOF-CARRYING .kimg (make pcc-check).

ЧТО ПРОВЕРЯЕМ. Образ .kimg должен нести внутри себя не только контракт
`<stem>.smt2`, но и его машинно-проверяемый сертификат `<stem>.proof`. Тогда
`kernc verify` подтверждает контракт НАШИМ пруф-чекером — БЕЗ решателя.

КРИТЕРИИ ПРИЁМКИ (все три обязательны):
  1. Образ с контрактом + ВАЛИДНЫМ сертификатом, запущенный с ПУСТЫМ PATH
     (внешний z3 физически не может быть вызван), даёт `e=1 (T)` и rc=0.
  2. Позитивный контроль: обычный образ (без .proof) с пустым PATH НЕ должен
     выдавать `[PCC VERIFIED]` — иначе тест был бы вакуумным.
  3. Подделанный сертификат (1 байт) -> `[PCC REJECTED]`, e=0, rc != 0.
     Отката к Z3 нет: подделка обязана закрывать Врата.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
CONTRACT = ROOT / "tests" / "fixtures" / "abs_contract.smt2"
PROOF = ROOT / "tests" / "fixtures" / "abs_proof.txt"

def tmp_root() -> str:
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        d = shm / "kern-pcc"
        d.mkdir(exist_ok=True)
        return str(d)
    return "/tmp"


def write_project(td: Path, proof_text: str) -> Path:
    (td / "abs.smt2").write_text(CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
    (td / "abs.proof").write_text(proof_text, encoding="utf-8")
    kern = td / "pcc.kern"
    kern.write_text(
        'project "pcc" {\n  version "1.0"\n  root "."\n}\n\n'
        'artifact "abs.smt2" {\n  kind "contract"\n  hash "sha256:00"\n}\n\n'
        'artifact "abs.proof" {\n  kind "proof"\n  hash "sha256:00"\n}\n\n'
        'claim "pcc-abs" {\n  status proven\n  evidence "contract:abs.smt2"\n  context "abs.smt2"\n}\n',
        encoding="utf-8")
    return kern


def build_and_verify(td: Path, kern: Path, kimg: Path, empty_path: bool):
    b = subprocess.run([str(KERNC), "build", str(kern), "-o", str(kimg), "--deflate"],
                       capture_output=True, text=True, timeout=180, cwd=str(td))
    if b.returncode != 0:
        return None, "сборка не удалась", b.stdout + b.stderr
    env = dict(os.environ)
    if empty_path:
        env["PATH"] = ""
    r = subprocess.run([str(KERNC), "verify", str(kimg)], capture_output=True,
                       text=True, timeout=180, env=env)
    return r.returncode, r.stdout + r.stderr, ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Proof-Carrying .kimg")
    args = ap.parse_args()
    if not KERNC.exists():
        print(f"[!] нет {KERNC} — соберите: zig build")
        return 2
    for f in (CONTRACT, PROOF):
        if not f.exists():
            print(f"[!] нет фикстуры {f}")
            return 2
    proof = PROOF.read_text(encoding="utf-8")
    fails = []
    td = Path(tmp_root()) / "case"
    shutil.rmtree(td, ignore_errors=True)
    td.mkdir(parents=True)

    # --- 1. ВАЛИДНЫЙ сертификат, ПУСТОЙ PATH ---
    kern = write_project(td, proof)
    rc, out, err = build_and_verify(td, kern, td / "ok.kimg", empty_path=True)
    ok1 = rc == 0 and "PCC VERIFIED" in out
    print("1) валидный сертификат, PATH пустой: rc=" + str(rc) + " -> " + ("OK" if ok1 else "ПРОВАЛ"))
    if not ok1:
        fails.append("валидный сертификат не подтверждён без решателя")
        print("   вывод: " + (out or err)[-300:])

    # --- 3. ПОДДЕЛАННЫЙ сертификат ---
    lines = proof.split("\n")
    tampered = []
    changed = False
    for l in lines:
        if not changed and "(<= " in l:
            tampered.append(l.replace("(<= ", "(< ", 1)); changed = True
        else:
            tampered.append(l)
    if not changed and lines:
        tampered = list(lines)
        tampered[1] = tampered[1] + " "
    kern2 = write_project(td, "\n".join(tampered))
    rc2, out2, err2 = build_and_verify(td, kern2, td / "bad.kimg", empty_path=True)
    ok3 = rc2 != 0 and "PCC REJECTED" in out2
    print(f"3) подделанный сертификат         : rc={rc2} -> " + ("OK" if ok3 else "ПРОВАЛ"))
    if not ok3:
        fails.append("подделанный сертификат НЕ отвергнут")
        print("   вывод: " + (out2 or err2)[-300:])

    # --- 2. ПОЗИТИВНЫЙ КОНТРОЛЬ: без .proof нет PCC ---
    (td / "abs.proof").unlink()
    kern3 = write_project(td, proof)
    (td / "abs.proof").unlink()
    rc3, out3, err3 = build_and_verify(td, kern3, td / "nop.kimg", empty_path=True)
    ok2 = "PCC VERIFIED" not in out3
    print(f"2) образ БЕЗ сертификата          : нет PCC -> " + ("OK" if ok2 else "ПРОВАЛ"))
    if not ok2:
        fails.append("PCC сработал без сертификата (тест вакуумен)")

    print("-" * 74)
    if fails:
        print(f"[!] ПРОВАЛОВ: {len(fails)}")
        for f in fails:
            print("    - " + f)
        return 1
    print("[OK] PROOF-CARRYING .kimg: сертификат проверяется БЕЗ решателя; "
          "подделка закрывает Врата")
    return 0


if __name__ == "__main__":
    sys.exit(main())
