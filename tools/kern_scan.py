#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`kern_scan.py` — ОДНА КНОПКА: ПОЛНЫЙ АУДИТ ЛЮБОЙ ПАПКИ (#489).

ЗАЧЕМ. Пять боевых режимов KERN (`--xray`, контракты `@kern:`, `--anti-cheat`,
`--diff-equiv`/`audit-delta`, `pcc-offline-check`) жили в РАЗНЫХ флагах Python-
фронтенда. Владелец проекта видел 195 внутренних гейтов, но не видел одного руля
«проверь вот эту папку со всех сторон». Здесь этот руль.

ЧТО ДЕЛАЕТ (только ЧТЕНИЕ: ничего не пишет в проверяемый проект):
  1. ИНВЕНТАРИЗАЦИЯ: исходники по языкам, тестовые файлы, конфиги агентов MCP;
  2. РЕНТГЕН (`--xray --xray-json`, ABI #483): краши/переполнения/границы/ветви;
  3. КОНТРАКТЫ: файлы с `@kern:` -> формальное доказательство (PROVEN/REFUTED);
  4. АНТИ-ЧИТ (`--anti-cheat`): фальшивые тесты, `skip`, проглоченный `assert`;
  5. ПАСПОРТ на один экран + `--json`.

ЧЕСТНЫЙ ОХВАТ. На большом репозитории полный обход может идти часами, поэтому
`--sample N` берёт ДЕТЕРМИНИРОВАННУЮ выборку (алфавитную) и паспорт ПЕЧАТАЕТ,
сколько файлов реально проверено из скольки — «тихого» сужения нет.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# #494: ЕДИНЫЙ источник путей (dev / PyInstaller / Nuitka).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import env_resolver  # noqa: E402

ROOT = env_resolver.HOST_ROOT  # где лежит бинарник (или корень репо)
PY = sys.executable
EXTRACTOR = ROOT / "tools" / "kern_contracts.py"
SRC_EXT = {".py", ".c", ".h", ".hpp", ".hh", ".cc", ".cpp", ".cu", ".cuh",
           ".rs", ".zig", ".ts", ".tsx", ".js", ".jsx", ".go"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "target",
             ".zig-cache", "zig-out", ".mypy_cache", ".pytest_cache"}
RE_VERDICT = re.compile(r"\[(PASS|FAIL|SKIP|N)\]")


def walk(root: Path) -> tuple:
    """Инвентаризация: исходники, тесты, MCP-конфиги. Ничего не пишет."""
    src, tests, mcp = [], [], []
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue
        name = p.name.lower()
        if p.suffix in SRC_EXT:
            src.append(p)
            if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go"):
                tests.append(p)
        elif name.startswith("mcp") and name.endswith(".json"):
            mcp.append(p)
    return src, tests, mcp


def run(cmd: list, timeout: int) -> tuple:
    """Человеческий вывод: stdout+stderr вместе (для чтения глазами)."""
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[!] ТАЙМАУТ"


def run_abi(cmd: list, timeout: int) -> tuple:
    """ABI: ТОЛЬКО stdout. Диагностика инструмента идёт в stderr и НЕ должна
    ломать разбор — иначе любой проект с `arr[i]` в условии рушит паспорт
    (дефект #490: склейка потоков в самом сканере)."""
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "[!] ТАЙМАУТ"


def main() -> int:
    ap = argparse.ArgumentParser(description="KERN scan: полный аудит папки")
    ap.add_argument("path")
    ap.add_argument("--sample", type=int, default=60, help="сколько файлов сканировать (алфавитно)")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    # #494 ДОКТОР ПЕРЕД РАБОТОЙ: отсутствие z3/kernc — НАЗВАННЫЙ отказ rc=2,
    # а не «находок 0, unreadable 1» (измерено на спайке упаковки).
    import kerna_doctor  # noqa: PLC0415
    _rc = kerna_doctor.preflight(require_solver=True, require_kernc=False)
    if _rc != 0:
        return _rc

    root = Path(a.path).expanduser().resolve()
    if not root.is_dir():
        print(f"[!] не каталог: {root}")
        return 2
    src, tests, mcp = walk(root)
    sample = src[: a.sample]

    # РЕНТГЕН на выборке (через ABI #483), во временной копии — проект не трогаем
    tmp = Path(tempfile.mkdtemp(prefix="kern_scan_"))
    try:
        for f in sample:
            rel = f.relative_to(root)
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
        rc_x, out_x, err_x = run_abi([PY, str(EXTRACTOR), "--xray", str(tmp), "--xray-json"], a.timeout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    summary, findings, skipped = {}, [], []
    if rc_x in (0, 1):
        try:
            doc = json.loads(out_x)
            summary = doc.get("summary", {})
            findings = doc.get("findings", [])
            skipped = doc.get("skipped", [])
            # ДЕФЕКТ #489a: отчёт печатал ПУТИ ВРЕМЕННОГО каталога — для читателя
            # это мусор («/tmp/kern_scan_ab12/…»). Возвращаем исходный корень:
            # анализ идёт на копии (проект не трогаем), но ЧИТАТЬ отчёт должен
            # про ЕГО файлы.
            for f in findings:
                fp = str(f.get("file", ""))
                if fp.startswith(str(tmp)):
                    f["file"] = str(root / fp[len(str(tmp)):].lstrip("/"))
        except json.JSONDecodeError:
            print("[!] ABI-JSON не разобран — рентген не учтён (НАЗВАННЫЙ сбой)")
    else:
        print(f"[!] рентген rc={rc_x} — не учтён (НАЗВАННЫЙ исход: {out_x.strip()[:80]})")

    # КОНТРАКТЫ @kern: (только файлы с директивами)
    prov = ref = cskip = 0
    kern_files = [f for f in sample if "@kern:" in f.read_text(encoding="utf-8", errors="replace")]
    for f in kern_files[:20]:
        rc_c, out_c = run([PY, str(EXTRACTOR), str(f)], a.timeout)
        prov += len(re.findall(r"\[PASS\]", out_c))
        ref += len(re.findall(r"\[FAIL\]", out_c))
        cskip += len(re.findall(r"\[SKIP\]", out_c))

    # АНТИ-ЧИТ по тестовым файлам
    cheats = 0
    cheat_files = []
    for f in tests[:10]:
        rc_a, out_a = run([PY, str(EXTRACTOR), "--anti-cheat", str(f)], a.timeout)
        n = len(re.findall(r"\[CHEAT|\[SMELL\]", out_a))
        if n:
            cheats += n
            cheat_files.append(f"{f.relative_to(root)} ({n})")

    doc = {
        "schema_version": "1.0",
        "target": str(root),
        "inventory": {"sources": len(src), "tests": len(tests), "mcp_configs": len(mcp),
                      "scanned": len(sample)},
        "xray": {"summary": summary, "findings": findings, "skipped_reasons": skipped,
                 "diagnostics_to_stderr": len(err_x.splitlines())},
        "contracts": {"files": len(kern_files), "proven": prov, "refuted": ref, "skipped": cskip},
        "anti_cheat": {"files_checked": min(10, len(tests)), "signals": cheats,
                       "where": cheat_files},
    }
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0

    print("=" * 74)
    print(f"KERN SCAN: {root}")
    print("=" * 74)
    inv = doc["inventory"]
    print(f"  инвентарь : исходников {inv['sources']} | тестов {inv['tests']} | "
          f"MCP-конфигов {inv['mcp_configs']}")
    print(f"  охват     : просканировано {inv['scanned']} из {inv['sources']} "
          f"({'ПОЛНЫЙ' if inv['scanned'] == inv['sources'] else 'ВЫБОРКА (алфавитная)'})")
    if summary:
        print(f"  рентген   : функций {summary.get('total', 0)} | проверено "
              f"{summary.get('checked', 0)} | тривиальных {summary.get('trivial', 0)} | "
              f"пропущено {summary.get('skipped', 0)} | находок {summary.get('findings', 0)}")
    print(f"  контракты : файлов с @kern: {doc['contracts']['files']} | доказано "
          f"{prov} | опровергнуто {ref} | пропущено {cskip}")
    print(f"  анти-чит  : проверено тестов {doc['anti_cheat']['files_checked']} | "
          f"сигналов {cheats}")
    if findings:
        print("\n  НАХОДКИ (первые 12):")
        for f in findings[:12]:
            print(f"    - [{f.get('type')}] {f.get('file')}: {f.get('details', '')[:90]}")
    if skipped:
        print("\n  ПОЧЕМУ ПРОПУЩЕНО (топ-3):")
        for s in skipped[:3]:
            print(f"    - {s.get('reason')} × {s.get('count')}")
    # ДЕФЕКТ #489b: SMELL (стиль: много параметров, высокая CC) — это НЕ угроза.
    # Смешивать их в одном числе — значит назвать отчёт не тем, что произошло.
    threat_types = ("CRASH PATH", "OVERFLOW PATH", "BOUNDS PATH", "DEAD BRANCH")
    threats = [f for f in findings if (f.get("type") or "").strip() in threat_types]
    smells = [f for f in findings if (f.get("type") or "").strip() not in threat_types]
    print("\n  ПАСПОРТ: УГРОЗ (краш/переполнение/границы/ветвь) {0} | стиль (SMELL) {1} "
          "| читов в тестах {2} | доказано контрактов {3}".format(
              len(threats), len(smells), cheats, prov))
    if threats:
        print("  из них угроз — требуют триажа (дефолт-параметр 0 достижим вызывающим):")
        for f in threats[:6]:
            print("    > [{0}] {1}: {2}".format(f.get("type"), f.get("file"),
                                             (f.get("details") or "")[:80]))
    # ── ЗАКОН ПРОЕКТА `KERN.md` (#568): файл в корне папки -> проверяем по нему
    # и учитываем в коде возврата (иначе «закон нарушен» выглядел бы успехом).
    if (root / "KERN.md").is_file():
        import project_spec          # noqa: PLC0415 — вшит в бинарь тем же путём
        print()
        print("── ЗАКОН ПРОЕКТА (KERN.md) ──────────────────────────────────")
        if project_spec.main(["project_spec.py", str(root)]) != 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
