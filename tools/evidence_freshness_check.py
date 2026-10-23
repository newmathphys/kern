#!/usr/bin/env python3
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
"""Гейт свежести свидетельств (шаг F3, дефект #333).

ЗАЧЕМ. `docs/evidence/core_tests.log` был снят 20.10 и утверждал «All 402 tests
passed», а свежий прогон той же команды даёт 436: фазы Ф1–Ф3 добавили тесты, а
свидетельство не переснимали. `evidence-gate` проверяет `RC=` и маркеры провала,
но НЕ сверяет числа с текущим деревом — поэтому витрина занижала главное число на
34, и ни один страж этого не видел.

ДВА КЛАССА, и различие принципиальное:
  NATIVE_LIVE   — снимается на этой машине и ОБЯЗАНО совпадать с текущим деревом.
                  Проверяется ПЕРЕПРОГОНОМ: число в логе сравнивается с живым.
  ENV_DEPENDENT — зависит от среды (кросс-архитектура требует qemu). Перепроверить
                  здесь нельзя, поэтому такой лог ОБЯЗАН нести явную метку
                  базовой линии. Метка — свидетельство о моменте съёмки, а не
                  отговорка: без неё гейт краснеет.

Чего гейт НЕ делает: он не «исправляет» числа. Пересъёмка — отдельная команда
(`ONLY=<имя> bash tools/collect_evidence.sh`), потому что подгонять число руками
означало бы выдумать прогон.

Запуск:  python3 tools/evidence_freshness_check.py [--selftest]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "docs" / "evidence"
ZIG = os.environ.get("ZIG", "zig")

ALL_TESTS = re.compile(r"All\s+(\d+)\s+tests?\s+passed")
PASSED_SKIPPED = re.compile(r"(\d+)\s+passed\s*/\s*(\d+)\s+skipped")

# Класс NATIVE_LIVE: лог -> команда, которой он снимается.
# Команды взяты ИЗ `tools/collect_evidence.sh` дословно: гейт обязан проверять
# ровно тем же способом, каким свидетельство снималось.
LIVE = {
    "core_tests.log": [ZIG, "test", "--dep", "compat",
                       "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig"],
    "core_tests_relsafe.log": [ZIG, "test", "--dep", "compat",
                               "-Mroot=src/test_root.zig", "-Mcompat=src/compat.zig",
                               "-O", "ReleaseSafe"],
}

# Класс ENV_DEPENDENT: лог -> почему не перепроверяется здесь.
ENV_DEPENDENT = {
    "cross_arch.log": "требует qemu-user-static (ARM64/PPC64 big-endian)",
}
BASELINE_MARK = re.compile(r"ENV-DEPENDENT:\s*baseline\s+(\d+)", re.I)


def _count_in_log(path: Path) -> int | None:
    if not path.exists():
        return None
    m = ALL_TESTS.search(path.read_text(encoding="utf-8", errors="replace"))
    return int(m.group(1)) if m else None


def _live_count(cmd: list[str]) -> int | None:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    m = ALL_TESTS.search((p.stdout or "") + (p.stderr or ""))
    return int(m.group(1)) if m else None


def check() -> list[str]:
    errs: list[str] = []
    for name, cmd in LIVE.items():
        log = EV / name
        claimed = _count_in_log(log)
        if claimed is None:
            errs.append(f"{name}: нет числа тестов — свидетельство нечитаемо")
            continue
        live = _live_count(cmd)
        if live is None:
            errs.append(f"{name}: живой прогон не дал числа тестов")
            continue
        mark = "OK" if claimed == live else "FAIL"
        print(f"  [NATIVE_LIVE] {name}: в логе {claimed}, живой прогон {live} — {mark}")
        if claimed != live:
            errs.append(
                f"{name}: лог устарел ({claimed} != {live}). Пересъёмка: "
                f"ONLY={name[:-4]} bash tools/collect_evidence.sh")

    for name, why in ENV_DEPENDENT.items():
        log = EV / name
        if not log.exists():
            errs.append(f"{name}: отсутствует")
            continue
        text = log.read_text(encoding="utf-8", errors="replace")
        m = PASSED_SKIPPED.search(text)
        base = (int(m.group(1)) + int(m.group(2))) if m else None
        has = BASELINE_MARK.search(text)
        if not has:
            errs.append(f"{name}: среда-зависимый лог БЕЗ метки базовой линии "
                        f"({why}). Нужна строка "
                        f"`=== ENV-DEPENDENT: baseline <N> ({why}) ===`")
            continue
        declared = int(has.group(1))
        ok = "OK" if (base is None or declared == base) else "FAIL"
        extra = "" if base is None else f" (passed+skipped={base})"
        print(f"  [ENV_DEPENDENT] {name}: базовая линия {declared}{extra} — {ok}")
        if base is not None and declared != base:
            errs.append(f"{name}: метка базовой линии {declared} не совпадает "
                        f"с содержимым лога ({base})")
    return errs


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in args:
        return selftest()
    print("СВЕЖЕСТЬ СВИДЕТЕЛЬСТВ (#333)")
    errs = check()
    if errs:
        for e in errs:
            print(f"[FAIL] {e}")
        print(f"\n[FAIL] устаревших/непомеченных свидетельств: {len(errs)}")
        return 1
    print("\n[OK] свежесть: NATIVE_LIVE совпадают с деревом, "
          "ENV_DEPENDENT несут метку базовой линии")
    return 0


def selftest() -> int:
    """Мета-тест: занижённое число в копии лога ОБЯЗАНО ловиться.

    Проверяем ровно тот дефект, ради которого гейт создан: если в `src/`
    добавили тесты, а лог остался от старого коммита — гейт краснеет.
    """
    import tempfile
    bad = 0
    src = EV / "core_tests.log"
    if not src.exists():
        print("[FAIL] selftest: нет core_tests.log")
        return 1
    real = src.read_text(encoding="utf-8", errors="replace")
    m = ALL_TESTS.search(real)
    if not m:
        print("[FAIL] selftest: в логе нет числа тестов")
        return 1
    n = int(m.group(1))
    # Ломаем КОПИЮ (оригинал не трогаем) и убеждаемся, что сравнение ловит.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "core_tests.log"
        p.write_text(real.replace(f"All {n} tests passed",
                                  f"All {n - 1} tests passed", 1), encoding="utf-8")
        claimed = _count_in_log(p)
        live = _live_count(LIVE["core_tests.log"])
        if claimed == live:
            print("[FAIL] selftest: занижённое число НЕ отличается от живого")
            bad += 1
        else:
            print(f"[OK] selftest: устаревшее свидетельство ловится "
                  f"({claimed} != {live})")
    # Метка базовой линии: без неё ENV_DEPENDENT обязан считаться дефектом.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cross_arch.log"
        p.write_text("394 passed / 8 skipped\n", encoding="utf-8")
        if BASELINE_MARK.search(p.read_text(encoding="utf-8")):
            print("[FAIL] selftest: отсутствие метки не замечено")
            bad += 1
        else:
            print("[OK] selftest: отсутствие метки базовой линии ловится")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] freshness selftest: ошибок {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
