#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
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
    "artifact-check": "CHECK", "artifact-check-offline": "CHECK",
    "contracts": "CHECK",
    "contracts-json": "CHECK",
    "contracts-lock-check": "CHECK",
    "diff-equiv": "CHECK",
    "self-verify": "CHECK",
    "edge-cases": "CHECK",
    "audits": "CHECK",
    "sarif-check": "CHECK",
    "hook-check": "CHECK",
    "mcp-selftest": "CHECK",
    "kimg-deflate": "CHECK",
    "version-check": "CHECK",
    # 0K.2/0K.3: аттестат проверяется внешним ключом из репозитория;
    # кейс `attest-sig-missing` доказывает, что проверка умеет падать.
    "verify-attestation": "CHECK",
    "secrets-check": "CHECK",
    "determinism-check": "CHECK",
    "changelog-check": "CHECK",
    "lean-pin-check": "CHECK",
    "trust-docs-check": "CHECK",
    "perf-check": "CHECK",
    "citations-check": "CHECK",
    "axes-check": "CHECK",
    "ledger-check": "CHECK",
    "graph-check": "CHECK",
    "storage-check": "CHECK",
    "verify": "CHECK", "attack": "CHECK", "lean": "CHECK", "memcheck": "CHECK",
    "ubsaFe": "CHECK", "ubsafe": "CHECK", "stress-kimg": "CHECK", "smt-stress": "CHECK",
    "align": "CHECK", "avalanche": "CHECK", "bench-json": "CHECK", "pool": "CHECK", "semantic-gap": "CHECK",
    # ИЗМЕРЯЕТ throughput BLAKE3-SIMD-8 (не доказательство): падать «как гейт» не может -> MEASURE
    "bench-simd8": "MEASURE",
    "audit": "CHECK", "localize": "CHECK", "arrays": "CHECK", "chc": "CHECK",
    "strings": "CHECK", "cegis": "CHECK", "theories": "CHECK", "test-fault": "CHECK",
    "attest-key": "CHECK", "attest": "CHECK", "coverage": "CHECK", "fuzz-1m": "CHECK",
    "litmus": "CHECK", "concolic": "CHECK", "dtmc": "CHECK", "absint": "CHECK",
    "nra": "CHECK", "noninterference": "CHECK", "redos": "CHECK", "binlevel": "CHECK",
    "sim": "CHECK", "os-stress": "CHECK", "flood": "CHECK", "proof-check": "CHECK",
    "lia-diff": "CHECK",
    "proof-tamper": "CHECK",
    "tree-lock": "CHECK",
    "binary-audit": "CHECK",
    "bitrot-chaos": "CHECK",
    "pcc-check": "CHECK",
    "xray-check": "CHECK",
    "ecosystem-check": "CHECK",
    "scorecard-check": "CHECK",
    "metrics-guard": "CHECK",
    # Ступень 2 QuixBugs: AST-guided живой прогон. Утверждение — «расхождение
    # ловится, идентичные версии не обвиняются»; негативный контроль внутри
    # цели доказывает, что она способна упасть.
    "trace-check": "CHECK",
    # Сквозной стенд «KERN против ИИ»: утверждение — «обман, который видит
    # KERN, реально ловится, и исправление доказуемо». Негативный контроль —
    # canfail-кейс ломает детектор, стенд ОБЯЗАН покраснеть.
    "ai-demo": "CHECK",
    "gen-tests-check": "CHECK",
    "simplify-check": "CHECK",
    "bounds-check": "CHECK",
    "loop-check": "CHECK",
    "state-inv-check": "CHECK",
    "presets-check": "CHECK",
    "arbitrage-check": "CHECK",
    "double-spend-check": "CHECK",
    "ffi-bridge-check": "CHECK",
    "sql-policy-check": "CHECK",
    "pricing-matrix-check": "CHECK",
    "anti-cheat-check": "CHECK",
    "mcp-audit-check": "CHECK",
    "noninterference-check": "CHECK",
    "belnap-swarm-check": "CHECK",
    "action-firewall-check": "CHECK",
    "rag-conflict-check": "CHECK",
    "rlvr-oracle-check": "CHECK",
    "audit-repo-check": "CHECK",
    "bug-hunt-check": "CHECK",
    "html-canvas-check": "CHECK",
    "fuzz-corpus-check": "CHECK",
    "wasm-check": "CHECK",
    "kimg-grep-check": "CHECK",
    "dst-check": "CHECK",
    "homeostatic-heal-check": "CHECK",
    "opt-diff-check": "CHECK",
    "concolic-check": "CHECK",
    "translation-val-check": "CHECK",
    "evo-fuzz-check": "CHECK",
    "parser-security-check": "CHECK",
    "hadamard-check": "CHECK",
    "polyglot-7-check": "CHECK",
    "float-nan-check": "CHECK",
    "string-contracts-check": "CHECK",
    "disasm": "CHECK", "slsa": "CHECK", "deal": "CHECK", "cert": "CHECK",
    "svg-check": "CHECK", "evidence-gate": "CHECK",
    "audit-manifest": "CHECK", "fd-check": "CHECK", "canfail": "CHECK",
    "adversarial": "CHECK", "telemetry": "CHECK", "evidence": "CHECK",
    "telemetry-quick": "CHECK", "evidence-fast": "CHECK",
    "guardrail": "CHECK",
    "run-example": "META",   # демонстрация (не проверка); свой can-fail не нужен
    "contracts-lock": "META",  # ЗАПИСЬ замка (не проверка); проверяет contracts-lock-check
    "canfail-anchors": "META",  # быстрый пре-флайт якорей (дефект #113)
    "canfail-selftest": "META",
    "metrics-guard-selftest": "META",   # мета: проверяет сам страж чисел
    "sync": "META",                     # синхронизация facts.json + якорей
    "sync-check": "META",               # проверка якорей (CI)
    "docs-parity": "META",              # EN/RU-факты
    "ai-traces-check": "META",          # нет ИИ-шаблонов в тексте/коммитах
    "seal": "BUILD",                    # герметичная сборка + аттестат
    "status": "META",                    # git status + легенда generated/manual
    "showcase": "BUILD",                 # пересборка графа витрины из src/
    "showcase-check": "META",            # граф витрины == src/ (+ --selftest)
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
    "help": "META", "venv": "META", "zig": "META", "clean": "META", "clean-cache": "META",
    "echelons": "META", "research": "META", "formal-ci": "META", "test-all": "META",
    "mutate": "CHECK", "prove": "CHECK", "ci": "META", "ci-fast": "META", "registry": "CHECK",
    # хардкор-аудит C-ABI: ОБЕ обязаны уметь падать (проверено can-fail кейсами)
    "c-abi-test": "CHECK", "c-abi-threads": "CHECK",
}


# --- СОПОСТАВЛЕНИЕ: can-fail кейс -> цель Makefile -------------------------
# Явная таблица (а не эвристика по подстроке): иначе покрытие считается неверно.
CASE_TARGET = {
    "avalanche": "avalanche",
    "bench-json": "bench-json",
    # УЛУЧШЕНИЯ v2.5: can-fail доказательства для новых целей.
    "vacuous-requires": "contracts",
    "contract-lock": "contracts-lock-check",
    "attest-sig-missing": "verify-attestation",
    "secret-in-tree": "secrets-check",
    "nondeterministic": "determinism-check",
    "changelog-drift": "changelog-check",
    "lean-pin-drift": "lean-pin-check",
    "trust-docs-missing": "trust-docs-check",
    "perf-regression": "perf-check",
    "citations-unknown-key": "citations-check",
    "axes-law-break": "axes-check",
    "ledger-retract-break": "ledger-check",
    "graph-parity-break": "graph-check",
    "kimg-flag-policy": "storage-check",
    "cache-key-13": "storage-check",
    "diff-equiv": "diff-equiv",
    "self-verify": "self-verify",
    "edge-cases": "edge-cases",
    "edge-cases": "edge-cases",
    "audits": "audits",
    "sarif-output": "sarif-check",
    "contracts-json": "contracts-json",
    "hook-gate": "hook-check",
    "slsa-bad-sig": "slsa",
    "lean-sorry": "lean",
    "binlevel": "binlevel",
    "svg-overflow": "svg-check",
    "evidence-guard": "evidence-gate",
    "metrics-guard": "metrics-guard",
    # хардкор-аудит C-ABI (дефект #103): публичный интерфейс теперь под покрытием
    "c-abi-null": "c-abi-test",
    "c-abi-hash": "c-abi-threads",
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
    "lia-soundness": "lia-diff",
    "proof-tamper": "proof-tamper",
    "tree-lock": "tree-lock",
    "binary-audit": "binary-audit",
    "bitrot-chaos": "bitrot-chaos",
    "pcc-check": "pcc-check",
    "xray-check": "xray-check",
    "gen-tests-check": "gen-tests-check",
    "simplify-check": "simplify-check",
    "bounds-check": "bounds-check",
    "loop-check": "loop-check",
    "state-inv-check": "state-inv-check",
    "presets-check": "presets-check",
    "arbitrage-check": "arbitrage-check",
    "double-spend-check": "double-spend-check",
    "ffi-bridge-check": "ffi-bridge-check",
    "sql-policy-check": "sql-policy-check",
    "pricing-matrix-check": "pricing-matrix-check",
    "anti-cheat-check": "anti-cheat-check",
    "mcp-audit-check": "mcp-audit-check",
    "noninterference-check": "noninterference-check",
    "belnap-swarm-check": "belnap-swarm-check",
    "action-firewall-check": "action-firewall-check",
    "rag-conflict-check": "rag-conflict-check",
    "rlvr-oracle-check": "rlvr-oracle-check",
    "audit-repo-check": "audit-repo-check",
    "bug-hunt-check": "bug-hunt-check",
    "html-canvas-check": "html-canvas-check",
    "fuzz-corpus-check": "fuzz-corpus-check",
    "wasm-check": "wasm-check",
    "kimg-grep-check": "kimg-grep-check",
    "dst-check": "dst-check",
    "homeostatic-heal-check": "homeostatic-heal-check",
    "opt-diff-check": "opt-diff-check",
    "concolic-check": "concolic-check",
    "translation-val-check": "translation-val-check",
    "evo-fuzz-check": "evo-fuzz-check",
    "parser-security-check": "parser-security-check",
    "hadamard-check": "hadamard-check",
    "polyglot-7-check": "polyglot-7-check",
    "float-nan-check": "float-nan-check",
    "string-contracts-check": "string-contracts-check",
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
    "adversarial-payload": "adversarial",
    "guardrail-verdict": "guardrail",
    "evidence-full": "evidence",
    "telemetry-full": "telemetry",
    "evidence-propagates": "evidence-fast",
    "telemetry-detects": "telemetry-quick",
    "sanity-control": "canfail",   # мета: проверяет сам харнесс
    "meta-verdict": "canfail",     # мета: ломает вердикт харнесса
    "proof-hole": "core_tests",
    "proof-binding": "core_tests",
    # ДЕФЕКТ #87: здесь стояло "evidence-gate" — кейс указывал на ЧУЖУЮ цель,
    # из-за чего счётчик «покрыто» считал evidence-gate покрытым дважды, а
    # artifact-check оставался без доказательства. Указываем РЕАЛЬНУЮ цель.
    "artifact-check": "artifact-check",
    "artifact-check-offline": "artifact-check-offline",
    "ecosystem-check": "ecosystem-check",
    "scorecard-check": "scorecard-check",   # внешние каталоги MCP (манифесты == tools/list)
    "contracts": "contracts",
    # Ступень 2 QuixBugs: кейс ломает сравнение в движке — цель обязана упасть.
    "trace-check": "trace-check",
    "ai-demo": "ai-demo",
    "contracts-branches": "contracts",  # ветвления if -> ite
    "kimg-deflate": "kimg-deflate",   # сжатие 0x02 в CLI
    "skip-exit-n": "test-next",       # SKIP exit 2 -> N (боевой фидбек)
    "version-consistency": "version-check", # версия в баннере/--version/README
    "mcp-selftest": "mcp-selftest",
    "model-negative": "core_tests",   # парсер модели: свёртка (- N)
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

    # --- Реестр дефектов: ДУБЛИКАТЫ НОМЕРОВ ---------------------------------
    # Дефект #88 (найден при добавлении записи): номер #83 оказался занят, и
    # новая строка создала ДУБЛИКАТ — два разных дефекта под одним номером.
    # Ничем не проверялось. Теперь проверяется: номера в таблице
    # `docs/CAPABILITY_STATUS.md` обязаны быть уникальны.
    dup_fail = False
    cap = ROOT / "docs" / "CAPABILITY_STATUS.md"
    if cap.exists():
        nums = re.findall(r"^\| \*\*(\d+)\*\*", cap.read_text(encoding="utf-8"), re.M)
        seen: dict[str, int] = {}
        for n in nums:
            seen[n] = seen.get(n, 0) + 1
        dups = sorted((n for n, c in seen.items() if c > 1), key=int)
        if dups:
            dup_fail = True
            print("  \033[31m[ПРЕДОХРАНИТЕЛЬ] ДУБЛИКАТЫ НОМЕРОВ ДЕФЕКТОВ:\033[0m")
            for n in dups:
                print(f"    - #{n} встречается {seen[n]} раза")
            print("  Перенумеруйте одну из строк (следующий свободный номер).")
        else:
            print(f"  \033[32m[OK] номера дефектов уникальны ({len(nums)} строк)\033[0m")
    if dup_fail:
        return 1

    print("  \033[32m[OK] все цели классифицированы\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
