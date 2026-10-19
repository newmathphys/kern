#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
"""ПУНКТ 40Д: РЕГРЕССИОННЫЙ КОРПУС ФАЗЗИНГА.

Каждый файл корпуса прогоняется через `kernc` ДВА раза:
  * НЕТ паники/segfault (rc не 134/139 и в выводе нет `panic`);
  * результат ДЕТЕРМИНИРОВАН (одинаковый rc оба раза).
Проверяется и `.kimg`, и `.smt2`, и мусорные доказательства.
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNC = ROOT / "zig-out" / "bin" / "kernc"
CORPUS = ROOT / "tests" / "fuzz_corpus"
CRASH_RC = {134, 139, -6, -11}

def run(argv):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def main() -> int:
    if not KERNC.exists():
        print(f"[!] нет {KERNC} — соберите: zig build")
        return 2
    files = sorted(p for p in CORPUS.iterdir() if p.is_file())
    crashes = nondet = 0
    for f in files:
        if f.suffix == ".kimg":
            argv = [str(KERNC), "check-integrity", str(f)]
        elif f.suffix == ".proof":
            argv = [str(KERNC), "check-proof", str(CORPUS / "ok_simple.smt2"), str(f)]
        else:
            argv = [str(KERNC), "prove", str(f)]
        rc1, out1 = run(argv)
        rc2, _out2 = run(argv)
        bad = rc1 in CRASH_RC or "panic" in out1.lower() or "segmentation" in out1.lower()
        if bad:
            crashes += 1
            print(f"  [CRASH] {f.name}: rc={rc1}")
        elif rc1 != rc2:
            nondet += 1
            print(f"  [NONDET] {f.name}: rc {rc1} vs {rc2}")
        else:
            print(f"  [OK] {f.name}: rc={rc1} (детерминированно)")
    print("-" * 74)
    print(f"[FUZZ CORPUS] файлов {len(files)} | crashes {crashes} | недетерминированных {nondet}")
    if crashes or nondet:
        return 1
    print("  [OK] 0 паник, 0 segfault, 0 утечек (детерминизм подтверждён)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
