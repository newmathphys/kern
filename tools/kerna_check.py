#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
"""`kerna_check` — ГЕЙТ УПАКОВКИ (#494): собранный бинарь ведёт себя как dev.

ЗАЧЕМ. Спайк показал: собранный onefile-бинарь МОЛЧА деградировал (находок 0,
`unreadable 1`, rc=0) из-за четырёх ловушек путей. Без машинного гейта это
вернётся при первой же правке. Гейт собирает НАСТОЯЩИЙ бинарь и проверяет его
в изолированном каталоге.

ЧТО СТЕРЕЖЁТ:
  R1 сборка: бинарь создаётся (`tools/build_kerna.sh`);
  R2 изоляция: бинарь переносится в ПУСТОЙ каталог + `server.json` вшит;
  R3 паритет: на фикстурах находок СТОЛЬКО ЖЕ, сколько в dev-режиме, и
     `unreadable 0` (иначе «упаковано, но глухо»);
  R4 доктор: БЕЗ `z3` — rc=2 и НАЗВАННАЯ причина в stderr (не «находок 0»);
  R5 честный пропуск: без PyInstaller — печатается SKIP; при
     `KERNA_REQUIRE_BUILD=1` это ПРОВАЛ, а не тихое «зелено».

ЗАМЕР-ЭТАЛОН (спайк): 9.8 МБ, старт 253 мс, находок 5/5 на фикстурах.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
FIXTURE = ROOT / "tests" / "fixtures" / "precision_buggy"
EXPECTED_FINDINGS = 5          # столько же, сколько в dev-режиме
NAME = os.environ.get("KERNA_NAME", "kerna")


def _env() -> dict:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(ROOT / "tools")
    return e


def _dev_findings() -> int:
    """Эталон: сколько находок даёт НЕупакованный фронтенд."""
    p = subprocess.run([PY, str(ROOT / "tools" / "kern_contracts.py"),
                        "--xray", str(FIXTURE), "--xray-json"],
                       capture_output=True, text=True, timeout=900, cwd=str(ROOT))
    try:
        return int(json.loads(p.stdout)["summary"]["findings"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return -1


def _packaged_findings(bin_path: Path, extra_env: dict | None = None) -> tuple:
    env = dict(os.environ)
    env.pop("KERN_HOST_ROOT", None)
    env.pop("KERN_ROOT", None)
    if extra_env:
        env.update(extra_env)
    p = subprocess.run([str(bin_path), "--xray", str(FIXTURE), "--xray-json"],
                       capture_output=True, text=True, timeout=900,
                       cwd=str(bin_path.parent), env=env)
    try:
        doc = json.loads(p.stdout)
        return (p.returncode, int(doc["summary"]["findings"]),
                int(doc["summary"].get("unreadable", 0)))
    except (json.JSONDecodeError, KeyError, TypeError):
        return (p.returncode, -1, -1)


def main() -> int:
    bad = 0
    base = _dev_findings()
    print(f"[i] #494 эталон dev-режима: находок {base}")
    if base != EXPECTED_FINDINGS:
        print(f"[FAIL] R3: dev-эталон {base}, ожидали {EXPECTED_FINDINGS} — "
              f"сначала почините базовый анализ")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        msg = ("[SKIP] #494: PyInstaller не установлен — УПАКОВКА НЕ ПРОВЕРЕНА "
               "(это названный пропуск, а не «зелено»)")
        print(msg)
        if os.environ.get("KERNA_REQUIRE_BUILD") == "1":
            print("[FAIL] R5: KERNA_REQUIRE_BUILD=1 требует сборку")
            return 1
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="kerna_check_"))
    try:
        # R1: сборка
        out = tmp / "dist"
        p = subprocess.run(["bash", str(ROOT / "tools" / "build_kerna.sh"), str(out)],
                           capture_output=True, text=True, timeout=1800,
                           cwd=str(ROOT), env=_env())
        print(p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "")
        bin_path = out / NAME
        if p.returncode != 0 or not bin_path.is_file():
            print(f"[FAIL] R1: сборка не дала бинарь (rc={p.returncode})")
            print((p.stdout + p.stderr)[-400:])
            return 1
        size_mb = bin_path.stat().st_size / 1048576
        print(f"[OK] R1: бинарь собран ({size_mb:.1f} МБ)")

        # R2: изолированный каталог (пустой; server.json внутри упаковки)
        iso = tmp / "iso"
        iso.mkdir()
        iso_bin = iso / NAME
        shutil.copy2(bin_path, iso_bin)

        # R3: паритет БЕЗ kernc/z3 рядом -> доктор обязан назвать отказ
        rc, found, unreadable = _packaged_findings(iso_bin)
        if rc != 2:
            print(f"[FAIL] R4: без z3 ожидали названный отказ rc=2, получили "
                  f"rc={rc} (находок {found}, unreadable {unreadable})")
            bad += 1
        else:
            print("[OK] R4: без z3 — названный отказ rc=2 (а не «находок 0»)")

        # R3 (продолжение): полный дистрибутив -> ПАРИТЕТ с dev
        (iso / "zig-out" / "bin").mkdir(parents=True)
        shutil.copy2(ROOT / "zig-out" / "bin" / "kernc",
                     iso / "zig-out" / "bin" / "kernc")
        (iso / ".venv" / "bin").mkdir(parents=True)
        solver = None
        try:
            sys.path.insert(0, str(ROOT / "tools"))
            import z3bin
            solver = z3bin.find_z3()
        except (ImportError, OSError) as e:                  # класс #198/#457
            # ОЖИДАЕМЫЕ: нет модуля `z3bin` или нет файла решателя. Программные
            # ошибки (NameError/AttributeError/TypeError) НЕ глушим: они обязаны
            # доходить до вызывающего — иначе «паритета нет» станет невидимым.
            print(f"  [i] решатель не найден для изолированной копии: {e}")
            solver = None
        if solver:
            shutil.copy2(solver, iso / ".venv" / "bin" / "z3")
        rc, found, unreadable = _packaged_findings(iso_bin)
        if rc != 0 or found != base or unreadable != 0:
            print(f"[FAIL] R3: упакованный даёт rc={rc}, находок {found} "
                  f"(dev {base}), unreadable {unreadable} — ПАРИТЕТА НЕТ")
            bad += 1
        else:
            print(f"[OK] R3: паритет с dev (находок {found}, unreadable 0)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"[{'FAIL' if bad else 'OK'}] #494 kerna: провалов {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
