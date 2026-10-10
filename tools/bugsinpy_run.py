#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BugsInPy: РЕАЛЬНЫЕ исторические баги без нейросетей.

Для каждого бага:
  * buggy-коммит + тест → должен ПАДАТЬ → KERN: F (баг обнаружен)
  * fixed-коммит + тест → должен ПРОЙТИ  → KERN: T (исправлено)
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

BIP = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/BugsInPy")
PROJ = sys.argv[2] if len(sys.argv) > 2 else "PySnooper"
REPO = sys.argv[3] if len(sys.argv) > 3 else "https://github.com/cool-RR/PySnooper.git"
WORK = Path("/tmp/bip_work")
PYBIN = sys.argv[4] if len(sys.argv) > 4 else sys.executable


def sh(cmd, cwd=None, timeout=180):
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    bugs_dir = BIP / "projects" / PROJ / "bugs"
    bugs = sorted((d for d in bugs_dir.iterdir() if d.is_dir()), key=lambda d: int(d.name))
    print(f"Проект {PROJ}: {len(bugs)} багов | репозиторий {REPO}")
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    rc, out = sh(f"git clone -q {REPO} .", cwd=WORK, timeout=300)
    if rc != 0:
        print("[!] clone failed:", out[-300:]); return
    print(f"{'Баг':<5} | {'buggy тест':<18} | {'fixed тест':<18} | KERN-вердикт")
    print("-" * 78)
    det = okf = tot = 0
    for b in bugs:
        info = (b / "bug.info").read_text(encoding="utf-8", errors="ignore")
        bm = re.search(r'buggy_commit_id="([^"]+)"', info)
        fm = re.search(r'fixed_commit_id="([^"]+)"', info)
        tm = re.search(r'test_file="([^"]+)"', info)
        if not (bm and fm and tm):
            continue
        tot += 1
        test_cmd = (b / "run_test.sh").read_text(encoding="utf-8", errors="ignore").strip()
        test_cmd = test_cmd.replace("pytest", f"{PYBIN} -m pytest")
        sh(f"git checkout -q {bm.group(1)}", cwd=WORK)
        # тест добавляется вместе с фиксом — подтягиваем его (как делает фреймворк)
        sh(f"git checkout -q {fm.group(1)} -- {tm.group(1)}", cwd=WORK)
        sh(f"{PYBIN} -m pip install -q -e . 2>/dev/null || {PYBIN} setup.py -q install 2>/dev/null", cwd=WORK)
        rc_b, _ = sh(test_cmd, cwd=WORK)
        sh(f"git checkout -q {fm.group(1)}", cwd=WORK)
        sh(f"{PYBIN} -m pip install -q -e . 2>/dev/null || {PYBIN} setup.py -q install 2>/dev/null", cwd=WORK)
        rc_f, _ = sh(test_cmd, cwd=WORK)
        buggy_fail = rc_b != 0
        fixed_pass = rc_f == 0
        det += buggy_fail
        okf += fixed_pass
        verdict = ("F (найден)" if buggy_fail else "T (ПРОПУЩЕН!)") + " / " + ("T (исправлен)" if fixed_pass else "F")
        print(f"{b.name:<5} | {'FAIL' if buggy_fail else 'PASS':<18} | {'PASS' if fixed_pass else 'FAIL':<18} | {verdict}", flush=True)
    print("-" * 78)
    if tot:
        print(f"\n📊 {PROJ} (без нейросетей): багов обнаружено {det}/{tot} ({det/tot*100:.0f}%), "
              f"исправленных подтверждено {okf}/{tot} ({okf/tot*100:.0f}%)")


if __name__ == "__main__":
    main()
