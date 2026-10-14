#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
"""KERN: РЕЕСТР ЦЕЛЕЙ (K5) + ПРЕДОХРАНИТЕЛЬ.

ЗАЧЕМ. Цель Makefile может быть:
  CHECK      — проверка: имеет утверждение и ОБЯЗАНА уметь падать
               (требуется can-fail кейс);
  MEASURE    — измерение: только печатает, упасть НЕ МОЖЕТ
               (это не дефект, но и не доказательство);
  BUILD      — сборка артефакта (уровень L0: компилируется);
  META       — служебная (help/clean/venv);
  EXTERNAL   — требует внешней среды (qemu, docker, API-ключ).

ПРЕДОХРАНИТЕЛЬ (K3.3): если в Makefile появилась цель, которой НЕТ в реестре,
скрипт падает с ненулевым кодом. Так новая проверка не сможет появиться
«молча» — её придётся классифицировать, а значит решить, как её проверять.

Запуск:  python3 tools/registry.py            — отчёт + предохранитель
         python3 tools/registry.py --json     — машинно-читаемый отчёт
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- КЛАССИФИКАЦИЯ (единственный источник правды) --------------------------
# CHECK требует can-fail кейса. Остальные категории — нет.
CLASS = {
    # --- проверки: есть утверждение -----------------------------------------
    "golden": "CHECK", "build": "CHECK", "test": "CHECK", "test-next": "CHECK",
    "verify": "CHECK", "attack": "CHECK", "lean": "CHECK", "memcheck": "CHECK",
    "ubsaFe": "CHECK", "ubsafe": "CHECK", "stress-kimg": "CHECK", "smt-stress": "CHECK",
    "align": "CHECK", "avalanche": "CHECK", "pool": "CHECK", "semantic-gap": "CHECK",
    "audit": "CHECK", "localize": "CHECK", "arrays": "CHECK", "chc": "CHECK",
    "strings": "CHECK", "cegis": "CHECK", "theories": "CHECK", "test-fault": "CHECK",
    "attest-key": "CHECK", "attest": "CHECK", "coverage": "CHECK", "fuzz-1m": "CHECK",
    "litmus": "CHECK", "concolic": "CHECK", "dtmc": "CHECK", "absint": "CHECK",
    "nra": "CHECK", "noninterference": "CHECK", "redos": "CHECK", "binlevel": "CHECK",
    "sim": "CHECK", "os-stress": "CHECK", "flood": "CHECK", "proof-check": "CHECK",
    "disasm": "CHECK", "slsa": "CHECK", "deal": "CHECK", "cert": "CHECK",
    "audit-manifest": "CHECK", "fd-check": "CHECK", "canfail": "CHECK",
    # --- измерения: упасть НЕ могут -----------------------------------------
    "perf": "CHECK", "bench": "CHECK", "stress": "CHECK", "probe": "CHECK",
    "portable-bench": "CHECK", "smt": "CHECK", "chc-bench": "CHECK",
    "stress-real": "CHECK", "kern": "CHECK",
    # --- сборка -------------------------------------------------------------
    "lib": "BUILD", "hermetic": "BUILD", "next": "BUILD", "demo": "BUILD",
    "bridge": "BUILD", "capi-demo": "BUILD", "docker": "EXTERNAL",
    # --- внешние ------------------------------------------------------------
    "cross-arch": "EXTERNAL", "mbpp": "EXTERNAL",
    # --- мета ---------------------------------------------------------------
    "help": "META", "venv": "META", "zig": "META", "clean": "META",
    "echelons": "META", "research": "META", "formal-ci": "META", "test-all": "META",
    "mutate": "CHECK", "prove": "CHECK", "ci": "META", "ci-fast": "META", "registry": "CHECK",
}


# --- СОПОСТАВЛЕНИЕ: can-fail кейс -> цель Makefile -------------------------
# Явная таблица (а не эвристика по подстроке): иначе покрытие считается неверно.
CASE_TARGET = {
    "avalanche": "avalanche",
    "lean-sorry": "lean",
    "binlevel": "binlevel",
    "disasm": "disasm",
    "core-gate": "test",
    "golden": "golden",
    "slsa": "slsa",
    "grep-arrays": "arrays",
    "grep-litmus": "litmus",
    "attack": "attack",
    "smt-bench": "smt",
    "stress-thresh": "stress-kimg",
    "build-syntax": "build",
    "chc-theory": "chc",
    "dtmc-theory": "dtmc",
    "cegis-theory": "cegis",
    "nra-theory": "nra",
    "align-inv": "align",
    "pool-limit": "pool",
    "strings-theory": "strings",
    "noninterf": "noninterference",
    "perf-threshold": "perf",
    "kern-invariant": "kern",
    "redos-vuln": "redos",
    "concolic-victim": "concolic",
    "absint-inv": "absint",
    "attest-sign": "attest",
    "localize-core": "localize",
    "sim-invariant": "sim",
    "proof-check": "proof-check",
    "verify-cli": "verify",
    "prove-cli": "prove",
    "registry-fuse": "registry",
    "semantic-gap": "semantic-gap",
    "test-pool": "test-pool",
    "test-align": "test-align",
    "test-fault": "test-fault",
    "coverage": "coverage",
    "test-next": "test-next",
    "deal": "deal",
    "os-stress": "os-stress",
    "flood": "flood",
    "bench": "bench",
    "stress": "stress",
    "theories": "theories",
    "audit": "audit",
    "smt-stress": "smt-stress",
    "memcheck": "memcheck",
    "fd-check": "fd-check",
    "ubsafe": "ubsafe",
    "mutate": "mutate",
    "fuzz-1m": "fuzz-1m",
    "cert": "cert",
    "attest-key": "attest-key",
    "audit-manifest": "audit-manifest",
    "chc-bench": "chc-bench",
    "probe": "probe",
    "portable-bench": "portable-bench",
    "ubsafe": "ubsafe",
    "sanity-control": "canfail",   # мета: проверяет сам харнесс
    "meta-verdict": "canfail",     # мета: ломает вердикт харнесса
}


def makefile_targets() -> set:
    s = (ROOT / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"^([a-z][a-z0-9-]*):", s, re.M))


def canfail_cases() -> set:
    """Имена целей, для которых есть can-fail кейс."""
    s = (ROOT / "tools" / "canfail.py").read_text(encoding="utf-8")
    # берём только строки внутри CASES = [...]
    m = re.search(r"CASES = \[(.*?)\n\]", s, re.S)
    if not m:
        return set()
    return set(re.findall(r'\("([a-z0-9-]+)"', m.group(1)))


def main() -> int:
    targets = makefile_targets()
    cases = canfail_cases()

    unknown = sorted(t for t in targets if t not in CLASS)
    checks = sorted(t for t in targets if CLASS.get(t) == "CHECK")
    measures = sorted(t for t in targets if CLASS.get(t) == "MEASURE")
    builds = sorted(t for t in targets if CLASS.get(t) == "BUILD")
    ext = sorted(t for t in targets if CLASS.get(t) == "EXTERNAL")
    meta = sorted(t for t in targets if CLASS.get(t) == "META")

    # Какие ПРОВЕРКИ реально покрыты can-fail — по ЯВНОЙ таблице CASE_TARGET.
    # ⚠️ Пересекаем с `checks`: среди целей есть META (`canfail`), которая не
    # входит в знаменатель, поэтому без пересечения счётчик давал «54/53».
    covered = {CASE_TARGET[c] for c in cases if c in CASE_TARGET} & set(checks)

    if "--json" in sys.argv:
        print(json.dumps({
            "targets": len(targets), "checks": checks, "measures": measures,
            "builds": builds, "external": ext, "meta": meta,
            "unknown": unknown, "canfail_cases": sorted(cases),
            "checks_covered": sorted(covered),
        }, ensure_ascii=False, indent=2))
        return 1 if unknown else 0

    print("=" * 68)
    print("KERN: РЕЕСТР ЦЕЛЕЙ")
    print("=" * 68)
    print(f"  всего целей:   {len(targets)}")
    print(f"  CHECK:         {len(checks)}   (обязаны уметь падать)")
    print(f"  MEASURE:       {len(measures)}   (упасть НЕ могут — это не доказательство)")
    print(f"  BUILD:         {len(builds)}   (только L0: компилируется)")
    print(f"  EXTERNAL:      {len(ext)}")
    print(f"  META:          {len(meta)}")
    print()
    print(f"  can-fail кейсов: {len(cases)}")
    print(f"  CHECK с доказательством «может упасть»: {len(covered)}/{len(checks)}")
    print()

    missing = sorted(set(checks) - covered)
    if missing:
        print("  ПРОВЕРКИ БЕЗ can-fail (K1, к закрытию):")
        for m in missing:
            print(f"    - {m}")
        print()

    if unknown:
        print("  \033[31m[ПРЕДОХРАНИТЕЛЬ] НЕКЛАССИФИЦИРОВАННЫЕ ЦЕЛИ:\033[0m")
        for u in unknown:
            print(f"    - {u}")
        print("  Классифицируйте их в tools/registry.py (CHECK/MEASURE/BUILD/META/EXTERNAL).")
        return 1

    print("  \033[32m[OK] все цели классифицированы\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
