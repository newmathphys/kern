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
    # ДЕФЕКТ #288: это НЕ CHECK. `artifact-check*` сверяет релизный артефакт с
    # объявленным в README хешем; объявление существует только в релизе (#250
    # убрал хардкод, который дрейфовал). Ломать его в canfail нечем: без
    # объявления цель выходит с 1 всегда, и «доказательство невакуумности»
    # доказывало бы отсутствие ворот. Класс BUILD — честное имя.
    "artifact-check": "BUILD", "artifact-check-offline": "BUILD",
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
    "kimg-cli-check": "CHECK",
    "quixbugs-replay": "CHECK",
    "codecheck": "CHECK",
    "anti-self-deception-check": "CHECK",
    "conformance-check": "CHECK",
    "advisory-check": "CHECK",
    "llms-check": "CHECK",
    "status-check": "CHECK",             # шаг C: снимок состояния == facts+реестр+журнал
    "charter-check": "CHECK",            # шаг E: законы устава доказаны + сверены с ядром
    "evidence-freshness": "CHECK",       # шаг F3 (#333): лог не отстал от дерева
    "temp-isolation-check": "CHECK",     # шаг N2: /tmp изолирован, замок не тронут
    "flake-check": "CHECK",             # F2: цель с разными вердиктами = B(1,1)
    "lang-semantics-check": "CHECK",    # шаг I: таблица семантики полна
    "arith-semantics-check": "CHECK",
    "c-types-check": "CHECK",
    "div-guards-check": "CHECK",
    "claims-audit": "CHECK",
    "arith-zig-ref-check": "CHECK",
    "explain-hypotheses-check": "CHECK",
    "hypotheses-corpus-check": "CHECK",
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
    "llms-selftest": "META",            # мета: генератор llms.txt из facts.json (#311)
    "status-doc": "META",                # мета: генератор docs/STATUS.md (шаг C)
    "status-selftest": "META",           # мета: числа STATUS не захардкожены (шаг C)
    "charter-selftest": "META",          # мета: сломанный закон валит устав (шаг E)
    "junit": "META",                     # мета: отчёт в формате чужого CI (шаг F1)
    "junit-selftest": "META",            # мета: XML валиден и падение попадает в отчёт
    "evidence-freshness-selftest": "META",  # мета: устаревшее свидетельство ловится (#333)
    "temp-isolation-selftest": "META",      # мета: общий путь и замок с $$ ловятся (N2)
    "flake-selftest": "META",               # мета: T и B различаются (F2)
    "lang-semantics-selftest": "META",      # мета: пропажа языка ловится (I)
    "arith-zig-ref-selftest": "META",   # мета: сверка адаптеров деления с эталоном Zig (#317)            # мета: генератор llms.txt из facts.json (#311)
    "sync": "META",                     # синхронизация facts.json + якорей
    "sync-check": "META",               # проверка якорей (CI)
    "docs-parity": "META",              # EN/RU-факты
    # ДЕФЕКТ #335: полнота EN-журнала дефектов. Тот же класс, что docs-parity —
    # проверка ДОКУМЕНТА, а не возможности; сверяет множества номеров записей
    # в RU и EN (в обе стороны), потому что дефект, живущий только по-русски,
    # для внешнего читателя не записан вовсе.
    "journal-parity-check": "META",
    # ДЕФЕКТ #350: текст устава против измерения `charter_check.py`. Тот же класс,
    # что docs-parity/journal-parity — проверка ДОКУМЕНТА, поэтому META.
    "charter-text-check": "META",
    # ДЕФЕКТ #354: README релиза ссылался на `docs/PLAN_v2.7.1.md`, которого
    # никогда не существовало. Проверка ДОКУМЕНТА против файловой системы,
    # поэтому META (тот же класс, что journal-parity и charter-text).
    "readme-link-check": "META",
    # ЭТАП 3: парный бенчмарк NIST Juliet-style (bad vs good) по девяти классам
    # MITRE CWE. Это проверка ВОЗМОЖНОСТИ движков (найти `bad` И не обвинить
    # `good`), поэтому CHECK.
    "cwe-juliet-check": "CHECK",
    # ЭТАП 4А: полигон ИИ-ловушек — проверка ВОЗМОЖНОСТИ перехватить шесть
    # классов обмана точным маркером, поэтому CHECK.
    "ai-traps-check": "CHECK",
    # ЭТАП 4Б: инвариант звучимости QuixBugs (`false_equivalent == 0`) плюс
    # контрольная половина (ложный DIVERGED == 0), поэтому CHECK.
    "quixbugs-diff-check": "CHECK",
    # ЭТАП 5: матрица возможностей на реальных задачах + анатомия.
    "real-cases-check": "CHECK",
    # ШАГ 1: инлайнинг вызовов из того же файла — проверка ВОЗМОЖНОСТИ
    # (доказать через вызов И не соврать на коллизии имён), поэтому CHECK.
    "inline-check": "CHECK",
    # ИНФРАСТРУКТУРНЫЙ ДОЛГ: сверка `:status` официального банка SMT-LIB с
    # ответом решателя. Проверка ВОЗМОЖНОСТИ (решатель умеет решать
    # официальные задачи и не врёт о решении), поэтому CHECK.
    "smtlib-bench-check": "CHECK",
    # ДЕФЕКТ #344: три тождества EVM обязаны иметь ДОВЕРЕННОЕ доказательство
    # (`trusted: 0 | holes: 0`). Это проверка ВОЗМОЖНОСТИ (пруф-чекер умеет
    # раскрывать `define-fun` и считать константы), поэтому CHECK.
    "evm-proof-check": "CHECK",
    # ДЕФЕКТ #342: `@kern:lang evm` — рабочий фронтенд (директива выставляет
    # язык и меняет семантику деления). Проверка возможности, поэтому CHECK.
    "evm-lang-check": "CHECK",
    "ai-traces-check": "META",          # нет ИИ-шаблонов в тексте/коммитах
    "seal": "BUILD",                    # герметичная сборка + аттестат
    "status": "META",                    # git status + легенда generated/manual
    "showcase": "BUILD",                 # пересборка графа витрины из src/
    "showcase-check": "META",            # граф витрины == src/ (+ --selftest)
    "demo-all": "META",                  # генератор русской витрины (make demo-all)
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
    "kimg-cli": "kimg-cli-check",
    "kimg-endianness": "storage-check",
    "kernfs-no-mmap": "storage-check",
    "kernx-shared-fuel": "storage-check",
    "quixbugs-replay-break": "quixbugs-replay",
    "codecheck-fp": "codecheck",
    "anti-self-deception-fixture": "anti-self-deception-check",
    "conformance-break": "conformance-check",
    "advisory-fold": "advisory-check",
    "llms-drift": "llms-check",
    "status-drift": "status-check",
    "charter-law-break": "charter-check",
    "freshness-stale": "evidence-freshness",
    "temp-isolation": "temp-isolation-check",
    "flake": "flake-check",
    "lang-semantics": "lang-semantics-check",
    "arith-semantics": "arith-semantics-check",
    "c-types": "c-types-check",
    "div-guards": "div-guards-check",
    "claims-audit": "claims-audit",
    "arith-zig-ref": "arith-zig-ref-check",
    "hypotheses-write": "explain-hypotheses-check",
    "hypotheses-nonproof": "hypotheses-corpus-check",
    "diff-equiv": "diff-equiv",
    "query-kind-leak": "diff-equiv",
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
    # ДЕФЕКТ #356: здесь стояло `"kern"` — значения с таким именем НЕТ ни среди
    # целей Makefile, ни среди шагов `zig build` (в build.zig `"kern"` — имя
    # библиотеки и бенчмарка, а не шага). Кейс `case_gate_invariant_stress`
    # реально запускает `zig build bench-kern`, а это ровно то, что делает цель
    # `make bench`. Инвариант `casetarget_violations()` нашёл это при первом же
    # прогоне — то есть проверка ловит не только «нет записи», но и «запись ведёт
    # в никуда».
    "kern-invariant": "bench",
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
    # ДЕФЕКТ #356: кейсы, добавленные в цикле v2.7.2, НЕ были внесены в эту
    # таблицу, поэтому покрытие считалось по-старому: `evm-lang-check` и
    # `evm-proof-check` (обе CHECK) числились БЕЗ доказательства, хотя кейсы
    # существуют и падают. Гейт `scorecard-check` это поймал: «can-fail 158/160»
    # при 160 CHECK. Таблица — единственный источник сопоставления (эвристика по
    # подстроке запрещена выше), значит новый кейс обязан быть внесён ЗДЕСЬ.
    "evm-lang": "evm-lang-check",
    "evm-fundef": "evm-proof-check",
    "allman-style": "codecheck",
    "arith-unary": "arith-semantics-check",
    "lang-fields": "lang-semantics-check",
    # META-цели (в знаменатель CHECK не входят, но сопоставление фиксируем,
    # чтобы «кейс есть, а связи нет» не повторялось):
    "charter-text": "charter-text-check",
    "readme-link": "readme-link-check",
    "journal-parity": "journal-parity-check",
    "artifact-offline": "artifact-check-offline",
    # ДЕФЕКТ #356 (ШАГ 0, системное закрытие класса): семь кейсов существовали и
    # падали, но в таблице их НЕ БЫЛО — и это не ловил никто. Класс #87/#356
    # закрыт двусторонним инвариантом `casetarget_violations()` ниже.
    "bound-guards": "xray-check",
    "codec-dispatch": "test",
    "evidence-gate": "evidence-gate",
    "evidence-untracked": "evidence-gate",
    "model-verify": "test",
    "registry-dup-numbers": "registry",
    # `zig build test` включает тесты `src/core/blake3_simd8.zig` (проверено по
    # `docs/evidence/core_tests.log`: `blake3_simd8.test.SIMD8`), поэтому цель —
    # `test`, а не «сырая команда» без цели.
    "simd8-masking": "test",
    # кейс Шага 0 (класс #356) — сам обязан быть в таблице, иначе инвариант
    # поймает его же: это и есть самоприменение проверки.
    "casetarget-gap": "registry",
    # ЭТАП 3: парный бенчмарк CWE.
    "cwe-juliet": "cwe-juliet-check",
    # ЭТАП 4А: полигон ИИ-ловушек.
    "ai-traps": "ai-traps-check",
    # ЭТАП 4Б: инварианты QuixBugs.
    "quixbugs-diff": "quixbugs-diff-check",
    # ЭТАП 5: матрица реальных возможностей.
    "real-cases": "real-cases-check",
    # ШАГ 1: пять свойств инлайнинга.
    "inline": "inline-check",
    # Банк SMT-LIB: сверка `:status`.
    "smtlib-bench": "smtlib-bench-check",
    # ИНФРАСТРУКТУРНЫЙ ДОЛГ: кейс, направляющий гейт на подделанный `:status`.
    "smtlib-tamper": "smtlib-bench-check",
    # ШАГ 1: кейс, снимающий гигиену имён.
    "inline-hygiene": "inline-check",
    # ШАГ 1 Захода Б: маршрутизация C-like в `--diff-equiv` (дефект #361).
    "clike-diff-routing": "quixbugs-diff-check",
}


# --- ЗНАЧЕНИЯ, КОТОРЫЕ НЕ ЯВЛЯЮТСЯ ЦЕЛЯМИ MAKEFILE ---------------------------
# Нужны, чтобы инвариант «каждое значение обязано существовать» был ПРОВЕРЯЕМ, а
# не отключён. Каждая запись — реальная проверяемая поверхность, и для шагов
# `zig build` существование шага ПРОВЕРЯЕТСЯ по `build.zig` (ниже), поэтому
# список не может сгнить молча.
CASE_TARGET_NON_MAKE = {
    # ключ факта: итог `zig build test` (в Makefile цели с таким именем нет)
    "core_tests": "build-step:test",
    # реальные шаги `zig build` — существование сверяется с build.zig
    "kern": "build-step:kern",
    "test-align": "build-step:test-align",
    "test-pool": "build-step:test-pool",
}

# Кейсы, которые по построению НЕ сопоставляются с целью: они проверяют САМ
# харнесс, а не продукт. Список явный, чтобы «мета» не стала лазейкой.
CASE_TARGET_META = {"sanity-control", "meta-verdict"}


def casetarget_violations() -> list[str]:
    """ДВУСТОРОННИЙ инвариант таблицы `CASE_TARGET` (дефект #356).

    ЗАЧЕМ. `CASE_TARGET` — единственный источник сопоставления «кейс → цель»
    (эвристика по подстроке запрещена выше). Пока её полноту не проверял никто,
    новый кейс мог появиться БЕЗ записи, и покрытие CHECK тихо занижалось:
    ровно так `evm-lang-check`/`evm-proof-check` числились без доказательства
    (измерено `scorecard-check`: «can-fail 158/160» при 160 CHECK).

    ЧТО ПРОВЕРЯЕТСЯ (в обе стороны):
      1. каждый кейс из `CASES` (кроме явных МЕТА) ОБЯЗАН быть ключом таблицы;
      2. каждое значение таблицы ОБЯЗАНО быть целью Makefile ЛИБО записью в
         `CASE_TARGET_NON_MAKE`, причём для `build-step:<step>` шаг обязан
         существовать в `build.zig`.

    Граница названа: инвариант проверяет НАЛИЧИЕ связи, а не её ПРАВИЛЬНОСТЬ
    (что кейс указывает на ту самую цель) — это суждение человека.
    """
    problems: list[str] = []
    cases = canfail_cases()
    targets = makefile_targets()

    for c in sorted(cases):
        if c in CASE_TARGET_META:
            continue
        if c not in CASE_TARGET:
            problems.append(f"кейс `{c}` есть в CASES, но НЕТ в CASE_TARGET "
                            f"(класс #356: покрытие занижено молча)")

    build_zig = (ROOT / "build.zig").read_text(encoding="utf-8")
    for c, tgt in sorted(CASE_TARGET.items()):
        if tgt in targets:
            continue
        if tgt not in CASE_TARGET_NON_MAKE:
            problems.append(f"CASE_TARGET[\"{c}\"] = \"{tgt}\" — такой цели нет "
                            f"ни в Makefile, ни в CASE_TARGET_NON_MAKE")
            continue
        kind = CASE_TARGET_NON_MAKE[tgt]
        if kind.startswith("build-step:"):
            step = kind.split(":", 1)[1]
            if f'b.step("{step}"' in build_zig:
                continue
            # ДЕФЕКТ #356: шаги вида `bench-kern` создаются ДИНАМИЧЕСКИ —
            # `b.step("bench-" ++ it.name, ...)` в цикле по списку бенчмарков.
            # Литерала `b.step("bench-kern"` в файле нет, но шаг РЕАЛЬНО
            # существует. Принимаем префиксную форму, и это не ослабление:
            # проверяется, что цикл-генератор на месте.
            if "-" in step:
                prefix = step.split("-", 1)[0]
                if f'b.step("{prefix}-"' in build_zig:
                    continue
            problems.append(f"CASE_TARGET[\"{c}\"] = \"{tgt}\" объявлен как "
                            f"шаг `zig build {step}`, но его НЕТ в build.zig")
    return problems


def casetarget_selftest() -> int:
    """Мета-тест: инвариант ОБЯЗАН упасть на кейсе без записи (класс #356)."""
    bad = 0
    saved = dict(CASE_TARGET)
    # (1) кейс без записи обязан быть пойман
    victim = next((c for c in sorted(canfail_cases())
                   if c in CASE_TARGET and c not in CASE_TARGET_META), None)
    if victim is None:
        print("[FAIL] selftest: не нашёл ни одного кейса для проверки")
        return 1
    del CASE_TARGET[victim]
    got = casetarget_violations()
    if not any(victim in x for x in got):
        print(f"[FAIL] selftest: кейс `{victim}` без записи НЕ пойман")
        bad += 1
    else:
        print(f"[OK] selftest: кейс `{victim}` без записи ловится")
    CASE_TARGET[victim] = saved[victim]

    # (2) значение, которого нет нигде, обязано быть поймано
    CASE_TARGET["__selftest__"] = "no-such-target-anywhere"
    got = casetarget_violations()
    if not any("no-such-target-anywhere" in x for x in got):
        print("[FAIL] selftest: значение без цели НЕ поймано")
        bad += 1
    else:
        print("[OK] selftest: значение без цели ловится")
    del CASE_TARGET["__selftest__"]

    # (3) согласованная таблица обязана ПРОЙТИ (иначе гейт бесполезен)
    if casetarget_violations():
        print("[FAIL] selftest: восстановленная таблица не проходит")
        bad += 1
    else:
        print("[OK] selftest: восстановленная таблица проходит")
    print(f"[{'OK' if bad == 0 else 'FAIL'}] case-target selftest: ошибок {bad}")
    return 0 if bad == 0 else 1



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

    if "--selftest" in sys.argv:
        return casetarget_selftest()

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

    # --- ДВУСТОРОННИЙ ИНВАРИАНТ CASE_TARGET (дефект #356, ШАГ 0) -------------
    ct_problems = casetarget_violations()
    if ct_problems:
        print("  \033[31m[ПРЕДОХРАНИТЕЛЬ] ТАБЛИЦА CASE_TARGET НЕПОЛНА/БИТАЯ:\033[0m")
        for p in ct_problems:
            print(f"    - {p}")
        print("  Кейс без записи = покрытие CHECK занижено МОЛЧА (класс #87/#356).")
        print("  Внесите кейс в tools/registry.py::CASE_TARGET.")
        return 1
    print(f"  \033[32m[OK] CASE_TARGET полна в обе стороны: "
          f"{len(cases)} кейсов, все значения ведут в существующие цели\033[0m")
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
