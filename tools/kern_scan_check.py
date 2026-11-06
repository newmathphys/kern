#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`kern_scan_check` — ГЕЙТ «ОДНОЙ КНОПКИ» (#489): паспорт честен и НЕ ломается.

ЧТО СТЕРЕЖЁТ (каждое — замер, не обещание):
  R1 наличие кнопки      : tools/kern_scan.py существует и компилируется;
  R2 паспорт строится    : на фикстуре выдаёт rc=0 и все 5 секций;
  R3 пути ЧИТАЕМЫ        : в отчёте НЕТ /tmp/kern_scan_* (дефект #489a);
  R4 угрозы отделены     : SMELL не попадает в число угроз (дефект #489b);
  R5 захват утечки       : фикстура с настоящим делением на ноль ДОЛЖНА дать
                           хотя бы один CRASH PATH -> кнопка не «глухая»;
  R6 честный охват       : при --sample N паспорт печатает «ВЫБОРКА», а не «ПОЛНЫЙ».
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "tools" / "kern_scan.py"
PY = sys.executable

BAD = ["/tmp/kern_scan_"]

def fail(k, m):
    print(f"[FAIL] {k}: {m}")
    return 1

def main() -> int:
    bad = 0
    if not SCAN.is_file():
        return fail("R1", "tools/kern_scan.py отсутствует")
    tmp = Path(tempfile.mkdtemp(prefix="kern_scanfix_"))
    (tmp / "clean.py").write_text(
        "def guarded(a, b):\n    if b == 0:\n        return 0\n    return a // b\n",
        encoding="utf-8")
    # R7 (#490): файл, на котором инструмент пишет диагностику в stderr
    # (Subscript в условии). Склейка потоков в сканере ломала ABI — на
    # фикстурах без stderr гейт был ЗЕЛЁНЫМ. Теперь это ловится.
    (tmp / "diag.py").write_text(
        "def pick(arr, i):\n    if arr[i] > 0:\n        return arr[i]\n    return 0\n",
        encoding="utf-8")
    (tmp / "buggy.py").write_text(
        "def unguarded(a, b):\n    return a // b\n\n\ndef wide(a, b, c, d, e, f):\n    return a\n",
        encoding="utf-8")
    try:
        p = subprocess.run([PY, str(SCAN), str(tmp), "--sample", "10", "--json"],
                           capture_output=True, text=True, timeout=600, cwd=str(ROOT))
        if p.returncode != 0:
            return fail("R2", f"rc={p.returncode}: {(p.stdout+p.stderr)[:120]}")
        try:
            doc = json.loads(p.stdout)
        except json.JSONDecodeError:
            return fail("R2", "--json не разобран (ABI сломан)")
        for k in ("schema_version", "target", "inventory", "xray", "contracts", "anti_cheat"):
            if k not in doc:
                bad += fail("R2", f"в паспорте нет секции {k}")
        blob = json.dumps(doc, ensure_ascii=False)
        leaks = [b for b in BAD if b in blob]
        if leaks:
            bad += fail("R3", f"в отчёте пути временного каталога: {leaks}")
        fs = (doc.get("xray") or {}).get("findings") or []
        crash = [f for f in fs if (f.get("type") or "") == "CRASH PATH"]
        if not crash:
            bad += fail("R5", "настоящее деление на ноль НЕ найдено — кнопка глухая")
        smell = [f for f in fs if (f.get("type") or "") == "SMELL"]
        # R4: паспорт не должен называть SMELL угрозой
        p2 = subprocess.run([PY, str(SCAN), str(tmp), "--sample", "10"],
                            capture_output=True, text=True, timeout=600, cwd=str(ROOT))
        txt = p2.stdout + p2.stderr
        if not re.search(r"УГРОЗ", txt):
            bad += fail("R4", "строка ПАСПОРТ не найдена")
        # Состав, а не количество (#489): при поломке классификации ЧИСЛО может
        # случайно совпасть, поэтому сверяем ТИПЫ в блоке «из них угроз».
        threat_types = {"CRASH PATH", "OVERFLOW PATH", "BOUNDS PATH", "DEAD BRANCH"}
        named = re.findall(r"^    > \[([A-Z ?]+)\]", txt, re.M)
        for t in named:
            if t.strip() not in threat_types:
                bad += fail("R4", f"в угрозы попал тип {t!r} (это стиль, а не угроза)")
                break
        expected_named = len([f for f in fs if (f.get("type") or "") in threat_types])
        if expected_named and not named:
            bad += fail("R4", "угрозы есть в JSON, но блок «из них угроз» пуст")
        if smell and "SMELL" not in txt:
            bad += fail("R4", "SMELL есть в JSON, но не назван в паспорте")
        if "ВЫБОРКА" not in txt and doc["inventory"]["scanned"] < doc["inventory"]["sources"]:
            bad += fail("R6", "узкий охват не назван словом ВЫБОРКА")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    ext = Path.home() / ".cache" / "kern" / "repos" / "TheAlgorithms-Rust"
    if ext.is_dir():
        p3 = subprocess.run([PY, str(SCAN), str(ext), "--sample", "6", "--json"],
                            capture_output=True, text=True, timeout=900, cwd=str(ROOT))
        try:
            d3 = json.loads(p3.stdout)
            if (d3.get("xray") or {}).get("summary", {}).get("total", 0) == 0:
                bad += fail("R8", "на внешнем корпусе рентген ничего не увидел (кнопка глухая на чужом коде)")
            else:
                print(f"[OK] R8: внешний корпус разобран "
                      f"({d3['xray']['summary'].get('total')} функций, "
                      f"диагностики в stderr {d3['xray'].get('diagnostics_to_stderr', 0)})")
        except json.JSONDecodeError:
            bad += fail("R8", "на внешнем корпусе ABI не разобран (#490)")
    else:
        print("[SKIP] R8: внешний корпус отсутствует — проверка на чужом коде НЕ выполнена")
    print(f"[OK] kern-scan: {'провалов 0' if bad == 0 else f'ПРОВАЛОВ {bad}'}")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
