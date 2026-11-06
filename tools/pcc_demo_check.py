#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ГЕЙТ `pcc-demo-check` (#488) — ЭТАП 4: PROOF-CARRYING ARTIFACT У ПОЛУЧАТЕЛЯ БЕЗ Z3.

ЗАЧЕМ. Вся позиция «proof-carrying artifacts» проверяема только одним способом:
получатель, У КОТОРОГО НЕТ РЕШАТЕЛЯ, берёт артефакт и сертификат и получает
вердикт `[PROOF VERIFIED] trusted: 0 | holes: 0`. Пока это не замерено, обещание
остаётся словами. Гейт измеряет его в ЧИСТОЙ среде (`env -i`, `PATH` без каталога
z3) и ДОКАЗЫВАЕТ отсутствие решателя, а не предполагает его.

ЧЕТЫРЕ ПРОВЕРКИ:
  1. решателя НЕТ: в той же среде `command -v z3` печатает NO_Z3 (иначе вся
     витрина — самообман: «без Z3» проверялось бы С Z3);
  2. `kernc check-integrity audits/real_code_corpus.kimg` -> rc=0 (Merkle/bit-rot);
  3. `kernc check-proof <cert.smt2> <cert.proof>` -> rc=0 и `[PROOF VERIFIED]`
     с `trusted: 0` и `holes: 0` (НЕ `PARTIAL`);
  4. НЕВАКУУМНОСТЬ: порченый вывод отвергается (rc!=0) с НАЗВАННОЙ причиной.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
BUNDLE = ROOT / "audits" / "real_code_corpus.kimg"
CERT = ROOT / "audits" / "pcc" / "cwe191_good_sub_good.smt2"
PROOF = ROOT / "audits" / "pcc" / "cwe191_good_sub_good.proof"


def clean_env() -> dict:
    """Среда БЕЗ решателя: `env -i` -> только PATH/HOME, без .venv и без z3."""
    return {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LC_ALL": "C"}


def run(cmd: list, timeout: int = 120) -> tuple:
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       timeout=timeout, env=clean_env())
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    bad = []
    if not KERNC.exists():
        print("[SKIP] kernc не собран (make build) — НАЗВАННЫЙ пропуск")
        return 0
    if not (BUNDLE.exists() and CERT.exists() and PROOF.exists()):
        print("[SKIP] нет артефакта/сертификата — сначала `make audits`")
        return 0

    # 1) ДОКАЗАТЬ отсутствие решателя в среде, где идёт проверка
    rc, out = run(["/bin/sh", "-c", "command -v z3 || echo NO_Z3"])
    no_z3 = "NO_Z3" in out
    print(f"[i] #488: решатель в среде проверки: {'ОТСУТСТВУЕТ' if no_z3 else 'НАЙДЕН'}")
    if not no_z3:
        bad.append("z3 ДОСТУПЕН в среде проверки — замер «без Z3» был бы самообманом")

    # 2) ЦЕЛОСТНОСТЬ образа
    rc_i, out_i = run([str(KERNC), "check-integrity", str(BUNDLE)])
    if rc_i != 0 or "Целостность" not in out_i:
        bad.append(f"check-integrity rc={rc_i}: {out_i.strip()[:160]}")
    print(f"[i] check-integrity: rc={rc_i}")

    # 3) СЕРТИФИКАТ
    rc_p, out_p = run([str(KERNC), "check-proof", str(CERT), str(PROOF)])
    ok_p = (rc_p == 0 and "[PROOF VERIFIED]" in out_p and "trusted: 0" in out_p
            and "holes: 0" in out_p and "PARTIAL" not in out_p)
    print(f"[i] check-proof: rc={rc_p} | trusted 0: {'да' if 'trusted: 0' in out_p else 'НЕТ'}")
    if not ok_p:
        bad.append(f"check-proof не дал [PROOF VERIFIED] trusted: 0 — {out_p.strip()[:200]}")

    # 4) НЕВАКУУМНОСТЬ: порченый вывод обязан быть отвергнут
    forged = ROOT / ".zig-cache" / "pcc-forged.proof"
    forged.parent.mkdir(parents=True, exist_ok=True)
    forged.write_text(PROOF.read_text(encoding="utf-8").replace("false", "true", 1),
                      encoding="utf-8")
    rc_f, out_f = run([str(KERNC), "check-proof", str(CERT), str(forged)])
    print(f"[i] порченый вывод: rc={rc_f}")
    if rc_f == 0:
        bad.append("ПОРЧЕНЫЙ вывод принят (rc=0) — проверка не измеряет то, что заявляет")
    if "ОТВЕРГНУТО" not in out_f:
        bad.append(f"отказ без НАЗВАННОЙ причины: {out_f.strip()[:160]}")

    for b in bad:
        print(f"[!] {b}")
    if bad:
        print(f"[FAIL] #488: нарушений {len(bad)}")
        return 1
    print("[OK] #488: без Z3 — целостность OK, [PROOF VERIFIED] trusted: 0 | holes: 0, "
          "порченый вывод отвергнут")
    return 0


if __name__ == "__main__":
    sys.exit(main())
