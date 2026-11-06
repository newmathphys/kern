#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""ПОЛИГОН 5: сквозной E2E `kernx` на РЕАЛЬНЫХ артефактах полигонов 1 и 4.

ЗАЧЕМ. Ядро `src/next/` задумано ради эпистемического конфликта Белнапа
`B = JOIN_K(T, F)`: доказательство и опровержение НЕ должны затирать друг друга.
До `#423`/`#424` конфликт падал на SQLite CHECK и подменялся в пакете строкой
`refuted`. Этот гейт проверяет всю цепочку на РЕАЛЬНЫХ свидетельствах:

  * T: обычный CI (`pytest`) на файле с 12 читами -> rc=0;
  * F: KERN L5 (`--anti-cheat`) на том же файле   -> rc=1;
  * B: подача обоих на одно утверждение -> `conflicted`;
  * N: утверждение без свидетельств -> Врата ЗАКРЫТЫ.

КЛЮЧЕВОЕ: гейт ПЕРЕМЕРЯЕТ оба кода и требует, чтобы запись в `audits/polygon5.kern`
совпадала с фактом. Число без владельца — дефект класса `#405`; здесь у каждого
записанного `exit_code` есть перемер.

ЛОВУШКА (#453, измерена при составлении): код `2` в kernx — конвенция
SKIP/NO_EVIDENCE (`#96`) и даёт `N`, а НЕ `F`. Проект с `exit_code = 2` дал
`N->B 0` — конфликт не возникал.

ГРАНИЦЫ. Артефакты — фикстуры репозитория (реальные файлы полигонов 1 и 4), но
свидетельства ЗАПИСАНЫ в `.kern` и ПЕРЕМЕРЯЮТСЯ гейтом, а не собираются
kernx автоматически: `kernx` не запускает внешние оракулы сам.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
KERNX = ROOT / "zig-out/bin/kernx"
PROJ = "audits/polygon5.kern"
DEMO = "examples/anti_cheat_demo.py"


def run(args, timeout=300):
    try:
        r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError as exc:
        return 127, str(exc)


def measured():
    """ПЕРЕМЕР двух оракулов полигона 4 (числа получают владельца)."""
    rc_pytest, o = run([PY, "-m", "pytest", DEMO, "-q", "--no-header"])
    rc_ac, o2 = run([PY, "tools/kern_contracts.py", "--anti-cheat", DEMO])
    n_cheats = o2.count("CHEAT DETECTED")
    return {"pytest": rc_pytest, "anti_cheat": rc_ac, "cheats": n_cheats}


def recorded():
    """Коды, ЗАПИСАННЫЕ в фикстуре (по именам исполнений)."""
    src = (ROOT / PROJ).read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'claim "execution: ([^"]+)"\s*\{[^}]*?'
                         r'metric exit_code = (-?\d+)', src, re.S):
        out[m.group(1)] = int(m.group(2))
    return out


def build(proj_path: str):
    outdir = Path(tempfile.mkdtemp(prefix="p5_"))
    rc, o = run([str(KERNX), "build", proj_path, "--out", str(outdir)])
    return rc, o, outdir


def verdict(proj_path: str):
    """Полный вердикт по проекту. Возвращает (ok, notes, data)."""
    notes = []
    if not KERNX.exists():
        return False, [f"[!] нет {KERNX} — соберите: make build"], {}
    rc, o, outdir = build(proj_path)
    if rc != 0:
        return False, [f"[!] kernx build отказал rc={rc}"], {}
    rc_s, o_s = run([str(KERNX), "status", proj_path])
    m = re.search(r"N->B\(конфликт\) (\d+)", o_s)
    n_b = int(m.group(1)) if m else -1
    states = {k: int(v) for k, v in re.findall(
        r"статус (proven|refuted|tested|hypothesis|conflicted): (\d+)", o_s)}
    pkt = outdir / "agent_packet.json"
    data = {}
    if pkt.exists():
        data = json.loads(pkt.read_text(encoding="utf-8"))
    reason = None
    for key in ("contradictions", "conflicted", "proven", "refuted"):
        for x in data.get(key, []) or []:
            if isinstance(x, dict) and "honest" in str(x.get("id", "")):
                reason = x.get("reason")
    rc_d, _ = run([str(KERNX), "diff", proj_path])
    rc_g, _ = run([str(KERNX), "graph", proj_path])
    shutil.rmtree(outdir, ignore_errors=True)
    ok = (n_b == 1 and states.get("conflicted") == 1
          and states.get("proven", 0) >= 1 and states.get("refuted", 0) >= 1
          and states.get("hypothesis", 0) >= 1
          and reason == "conflicted" and rc_d == 0 and rc_g == 0)
    notes.append(f"  конфликт N->B: {n_b} · состояния {states}")
    notes.append(f"  пакет: reason={reason!r} (обязан быть 'conflicted', НЕ 'refuted')")
    notes.append(f"  kernx diff rc={rc_d}, graph rc={rc_g}")
    return ok, notes, data


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        # Подсадка: превратить F-свидетельство в T -> конфликт ИСЧЕЗАЕТ.
        src = (ROOT / PROJ).read_text(encoding="utf-8")
        planted = src.replace("metric exit_code = 1", "metric exit_code = 0", 1)
        if planted == src:
            print("[FAIL] selftest: подсадка не применилась")
            return 1
        tmp = Path(tempfile.mkdtemp(prefix="p5s_")) / "planted.kern"
        tmp.write_text(planted, encoding="utf-8")
        ok, notes, _ = verdict(str(tmp))
        shutil.rmtree(tmp.parent, ignore_errors=True)
        if ok:
            print("[FAIL] selftest: подсадка НЕ поймана — гейт вакуумен")
            return 1
        print("[OK] selftest: снятие F-свидетельства убирает конфликт и гейт краснеет")
        return 0

    print("=" * 74)
    print("  ПОЛИГОН 5: E2E `kernx` — четыре состояния Белнапа из реальных артефактов")
    print("=" * 74)
    m = measured()
    print(f"  ПЕРЕМЕР оракулов: pytest rc={m['pytest']} · "
          f"anti-cheat rc={m['anti_cheat']} ({m['cheats']} читов)")
    rec = recorded()
    print(f"  ЗАПИСЬ в {PROJ}: {rec}")
    ok_owner = (rec.get("pytest on anti_cheat_demo") == m["pytest"]
                and rec.get("kern anti-cheat on anti_cheat_demo") == m["anti_cheat"])
    if not ok_owner:
        print("[FAIL] записанные exit_code РАСХОДЯТСЯ с перемером "
              "(число без владельца, класс #405)")
        return 1
    print("  [OK] записанные коды совпадают с перемером (у числа есть владелец)")
    ok, notes, _ = verdict(PROJ)
    for n in notes:
        print(n)
    if not ok:
        print("\n[FAIL] полигон 5 не полон: конфликт не представлен или пакет схлопнул B в F")
        return 1
    print("\n[OK] полигон 5: T/F/B/N представлены, конфликт сохранён, пакет различает B и F")
    return 0


if __name__ == "__main__":
    sys.exit(main())
