# КАРТА ВОЗМОЖНОСТЕЙ: CHECK-ЦЕЛИ И ЧТО ОНИ ЗАЩИЩАЮТ

**Документ СГЕНЕРИРОВАН** `tools/gen_capability_map.py` из `tools/registry.py` +
`tools/canfail.py`. Руками НЕ правится: `make capability-map-check` краснеет, если
карта разошлась с реестром (добавили цель и забыли пересобрать — это ОШИБКА, а не
мелочь: документ, который врёт, хуже отсутствующего).

Колонки: **цель** — что запускается; **кейс canfail** — доказательство, что цель
СПОСОБНА упасть (класс `#356`: цель без кейса = покрытие занижено молча);
**защищает** — номера дефектов, взятые ИЗ ОПИСАНИЯ САМОГО КЕЙСА; **команда** —
как воспроизвести.

## E1. Формальное ядро L4 и сертификаты доказательств (52)

| Цель (CHECK) | Кейс canfail | Защищает | Команда |
|:--|:--|:--|:--|
| `adversarial` | `adversarial-payload` | — | `make adversarial` |
| `advisory-check` | `advisory-fold` | — | `make advisory-check` |
| `align` | `align-inv` | — | `make align` |
| `arith-semantics-check` | `arith-semantics`, `arith-unary` | — | `make arith-semantics-check` |
| `arith-zig-ref-check` | `arith-zig-ref` | — | `make arith-zig-ref-check` |
| `arrays` | `grep-arrays` | — | `make arrays` |
| `audits` | `audits` | — | `make audits` |
| `audits-mem-check` | `audits-mem-cap` | #470 | `make audits-mem-check` |
| `cegis` | `cegis-theory` | — | `make cegis` |
| `cert` | `cert` | — | `make cert` |
| `conformance-check` | `conformance-break` | — | `make conformance-check` |
| `contracts` | `contracts`, `contracts-branches`, `vacuous-requires` | — | `make contracts` |
| `contracts-json` | `contracts-json` | — | `make contracts-json` |
| `deal` | `deal` | — | `make deal` |
| `diff-equiv` | `diff-equiv`, `query-kind-leak` | — | `make diff-equiv` |
| `dtmc` | `dtmc-theory` | — | `make dtmc` |
| `evidence-trust` | `evidence-trust` | #474 | `make evidence-trust` |
| `evm-lang-check` | `evm-lang` | — | `make evm-lang-check` |
| `evm-proof-check` | `evm-fundef` | — | `make evm-proof-check` |
| `gen-tests-check` | `gen-tests-check` | — | `make gen-tests-check` |
| `hadamard-check` | `hadamard-check` | — | `make hadamard-check` |
| `lang-semantics-check` | `lang-fields`, `lang-semantics` | — | `make lang-semantics-check` |
| `lia-diff` | `lia-soundness` | — | `make lia-diff` |
| `localize` | `localize-core` | — | `make localize` |
| `native-theories-file-check` | `native-theories-file-drop` | — | `make native-theories-file-check` |
| `native-zig-ast-check` | `native-zig-ast-drop` | — | `make native-zig-ast-check` |
| `nra` | `nra-theory` | — | `make nra` |
| `opt-diff-check` | `opt-diff-check` | — | `make opt-diff-check` |
| `oracle-dtmc-check` | `oracle-dtmc-wrong` | — | `make oracle-dtmc-check` |
| `oracle-string-check` | `oracle-string-falseaccept` | — | `make oracle-string-check` |
| `pcc-check` | `pcc-check` | — | `make pcc-check` |
| `pcc-offline-check` | `pcc-demo` | #488 | `make pcc-offline-check` |
| `polyglot-7-check` | `polyglot-7-check` | — | `make polyglot-7-check` |
| `presets-check` | `presets-check` | — | `make presets-check` |
| `proof-check` | `proof-check` | — | `make proof-check` |
| `proof-tamper` | `proof-tamper` | — | `make proof-tamper` |
| `prove` | `prove-cli` | — | `make prove` |
| `quixbugs-diff-check` | `clike-diff-routing`, `quixbugs-diff` | — | `make quixbugs-diff-check` |
| `quixbugs-replay` | `quixbugs-replay-break` | — | `make quixbugs-replay` |
| `real-cases-check` | `real-cases` | — | `make real-cases-check` |
| `semantic-gap` | `semantic-gap` | — | `make semantic-gap` |
| `sim` | `sim-invariant` | — | `make sim` |
| `smt` | `smt-bench` | — | `make smt` |
| `smtlib-bench-check` | `smtlib-bench`, `smtlib-tamper` | — | `make smtlib-bench-check` |
| `smtlib-proof-check` | `smtlib-proof-depth`, `smtlib-proof-exit`, `smtlib-proof-partial`, `smtlib-read-limit` | — | `make smtlib-proof-check` |
| `strings` | `strings-theory` | — | `make strings` |
| `svcomp-witness-check` | `svcomp-witness-drop` | — | `make svcomp-witness-check` |
| `theories` | `theories` | — | `make theories` |
| `translation-val-check` | `translation-val-check` | — | `make translation-val-check` |
| `translator-diff-check` | `translator-diff` | #349 | `make translator-diff-check` |
| `ubsafe` | `ubsafe` | — | `make ubsafe` |
| `verify` | `verify-cli` | — | `make verify` |

## E2. Решётка Белнапа B4 (L3) и KERN-Next (5)

| Цель (CHECK) | Кейс canfail | Защищает | Команда |
|:--|:--|:--|:--|
| `belnap-swarm-check` | `belnap-swarm-check` | — | `make belnap-swarm-check` |
| `kern` | — | — | `make kern` |
| `kernx-polygon5-check` | `kernx-polygon5` | — | `make kernx-polygon5-check` |
| `mcp-selftest` | `mcp-selftest` | — | `make mcp-selftest` |
| `test-next` | `skip-exit-n`, `test-next` | — | `make test-next` |

## E3. Защита от саботажа ИИ (L5) (38)

| Цель (CHECK) | Кейс canfail | Защищает | Команда |
|:--|:--|:--|:--|
| `absint` | `absint-inv` | — | `make absint` |
| `action-firewall-check` | `action-firewall-check` | — | `make action-firewall-check` |
| `ai-demo` | `ai-demo` | — | `make ai-demo` |
| `ai-traps-check` | `ai-traps` | — | `make ai-traps-check` |
| `anti-cheat-check` | `anti-cheat-check` | — | `make anti-cheat-check` |
| `anti-self-deception-check` | `anti-self-deception-fixture` | — | `make anti-self-deception-check` |
| `arbitrage-check` | `arbitrage-check` | — | `make arbitrage-check` |
| `attack` | `attack` | — | `make attack` |
| `axes-check` | `axes-law-break` | — | `make axes-check` |
| `chc` | `chc-theory` | — | `make chc` |
| `chc-bench` | `chc-bench` | — | `make chc-bench` |
| `contracts-lock-check` | `contract-lock`, `contract-lock-coarse` | — | `make contracts-lock-check` |
| `double-spend-check` | `double-spend-check` | — | `make double-spend-check` |
| `dst-check` | `dst-check` | — | `make dst-check` |
| `explain-hypotheses-check` | `hypotheses-write` | — | `make explain-hypotheses-check` |
| `flood` | `flood` | — | `make flood` |
| `guardrail` | `guardrail-verdict` | — | `make guardrail` |
| `hook-check` | `hook-gate` | — | `make hook-check` |
| `hypotheses-corpus-check` | `hypotheses-nonproof` | — | `make hypotheses-corpus-check` |
| `l5-duel-check` | `l5-duel` | — | `make l5-duel-check` |
| `ledger-check` | `ledger-retract-break` | — | `make ledger-check` |
| `litmus` | `grep-litmus` | — | `make litmus` |
| `loop-check` | `loop-check` | — | `make loop-check` |
| `mcp-audit-check` | `mcp-audit-check` | — | `make mcp-audit-check` |
| `noninterference` | `noninterf` | — | `make noninterference` |
| `noninterference-check` | `noninterference-check` | — | `make noninterference-check` |
| `oracle-absint-check` | `oracle-absint-unsound` | — | `make oracle-absint-check` |
| `oracle-chc-check` | `oracle-chc-falseproof` | — | `make oracle-chc-check` |
| `oracle-noninterference-check` | `oracle-noninterference-missed` | — | `make oracle-noninterference-check` |
| `oracle-redos-check` | `oracle-redos-missed` | — | `make oracle-redos-check` |
| `pricing-matrix-check` | `pricing-matrix-check` | — | `make pricing-matrix-check` |
| `pytest-blind-check` | `pytest-blind` | — | `make pytest-blind-check` |
| `rag-conflict-check` | `rag-conflict-check` | — | `make rag-conflict-check` |
| `redos` | `redos-vuln` | — | `make redos` |
| `rlvr-oracle-check` | `rlvr-oracle-check` | — | `make rlvr-oracle-check` |
| `sql-policy-check` | `sql-policy-check` | — | `make sql-policy-check` |
| `state-inv-check` | `state-inv-check` | — | `make state-inv-check` |
| `storage-check` | `cache-key-13`, `kernfs-no-mmap`, `kernx-shared-fuel`, `kimg-endianness`, `kimg-flag-policy` | — | `make storage-check` |

## E4. Рентген кода, CWE, точность и PR-дельта (32)

| Цель (CHECK) | Кейс canfail | Защищает | Команда |
|:--|:--|:--|:--|
| `abi-check` | `abi-json` | #483 | `make abi-check` |
| `action-check` | `action-doctor` | — | `make action-check` |
| `binlevel` | `binlevel` | — | `make binlevel` |
| `bounds-check` | `bounds-check` | — | `make bounds-check` |
| `bug-hunt-check` | `bug-hunt-check` | — | `make bug-hunt-check` |
| `c-abi-test` | `c-abi-null` | — | `make c-abi-test` |
| `c-abi-threads` | `c-abi-hash` | — | `make c-abi-threads` |
| `c-types-check` | `c-types` | — | `make c-types-check` |
| `codecheck` | `allman-style`, `codecheck-fp` | — | `make codecheck` |
| `concolic` | `concolic-victim` | — | `make concolic` |
| `concolic-check` | `concolic-check` | — | `make concolic-check` |
| `cwe-twins-check` | `cwe-twins` | — | `make cwe-twins-check` |
| `div-guards-check` | `div-guards` | — | `make div-guards-check` |
| `edge-cases` | `edge-cases` | — | `make edge-cases` |
| `evo-fuzz-check` | `evo-fuzz-check` | — | `make evo-fuzz-check` |
| `float-nan-check` | `float-nan-check` | — | `make float-nan-check` |
| `fuzz-1m` | `fuzz-1m` | — | `make fuzz-1m` |
| `fuzz-corpus-check` | `fuzz-corpus-check` | — | `make fuzz-corpus-check` |
| `graph-check` | `graph-parity-break` | — | `make graph-check` |
| `html-canvas-check` | `html-canvas-check` | — | `make html-canvas-check` |
| `mbpp-xray-check` | `mbpp-xray-blindspot` | — | `make mbpp-xray-check` |
| `metrics-guard` | `metrics-guard` | — | `make metrics-guard` |
| `mutate` | `mutate` | — | `make mutate` |
| `parser-security-check` | `parser-security-check` | — | `make parser-security-check` |
| `pilot-e2e-check` | `pilot-gate-blind` | — | `make pilot-e2e-check` |
| `string-contracts-check` | `string-contracts-check` | — | `make string-contracts-check` |
| `svg-check` | `svg-overflow` | — | `make svg-check` |
| `xray-asi-check` | `xray-asi` | — | `make xray-asi-check` |
| `xray-check` | `bound-guards`, `xray-assert-guard`, `xray-bounds-note`, `xray-check`, `xray-ext-silent`, `xray-float-skip`, `xray-guard-else`, `xray-nested-branch`, `xray-skip-reasons`, `xray-while-guard` | #400, #401, #469, #471, #472 | `make xray-check` |
| `xray-overflow-check` | `xray-overflow` | — | `make xray-overflow-check` |
| `xray-precision` | `xray-precision` | #475 | `make xray-precision` |
| `zig-guard-check` | `zig-guard` | — | `make zig-guard-check` |

## E5. Контейнер .kimg, крипто-аттестация и WASM (L0–L2) (27)

| Цель (CHECK) | Кейс canfail | Защищает | Команда |
|:--|:--|:--|:--|
| `attest` | `attest-sign` | — | `make attest` |
| `attest-key` | `attest-key` | — | `make attest-key` |
| `audit` | `audit` | — | `make audit` |
| `audit-manifest` | `audit-manifest` | — | `make audit-manifest` |
| `audit-repo-check` | `audit-repo-check` | — | `make audit-repo-check` |
| `binary-audit` | `binary-audit` | — | `make binary-audit` |
| `bitrot-chaos` | `bitrot-chaos` | — | `make bitrot-chaos` |
| `citations-check` | `citations-unknown-key` | — | `make citations-check` |
| `disasm` | `disasm` | — | `make disasm` |
| `evidence` | `evidence-full` | — | `make evidence` |
| `evidence-fast` | `evidence-propagates` | — | `make evidence-fast` |
| `evidence-freshness` | `freshness-stale` | — | `make evidence-freshness` |
| `evidence-gate` | `evidence-gate`, `evidence-guard`, `evidence-untracked` | #88 | `make evidence-gate` |
| `ffi-bridge-check` | `ffi-bridge-check` | — | `make ffi-bridge-check` |
| `foreign-verdicts-check` | `foreign-verdicts` | — | `make foreign-verdicts-check` |
| `kerna-check` | `kerna` | #494 | `make kerna-check` |
| `kimg-cli-check` | `kimg-cli` | — | `make kimg-cli-check` |
| `kimg-deflate` | `kimg-deflate` | — | `make kimg-deflate` |
| `kimg-grep-check` | `kimg-grep-check` | — | `make kimg-grep-check` |
| `portable-bench` | `portable-bench` | — | `make portable-bench` |
| `sarif-check` | `sarif-output` | — | `make sarif-check` |
| `secrets-check` | `secret-in-tree` | — | `make secrets-check` |
| `slsa` | `slsa`, `slsa-bad-sig` | — | `make slsa` |
| `stress-kimg` | `stress-thresh` | — | `make stress-kimg` |
| `tree-lock` | `tree-lock` | — | `make tree-lock` |
| `verify-attestation` | `attest-sig-missing` | — | `make verify-attestation` |
| `wasm-check` | `wasm-check` | — | `make wasm-check` |

## E6. Ресурсная безопасность и самоконтроль контура (48)

| Цель (CHECK) | Кейс canfail | Защищает | Команда |
|:--|:--|:--|:--|
| `avalanche` | `avalanche` | — | `make avalanche` |
| `bench` | `bench`, `kern-invariant` | — | `make bench` |
| `bench-json` | `bench-json` | — | `make bench-json` |
| `build` | `build-syntax` | — | `make build` |
| `canfail` | `meta-verdict`, `sanity-control` | — | `make canfail` |
| `capability-map-check` | `capability-map` | #485 | `make capability-map-check` |
| `changelog-check` | `changelog-drift` | — | `make changelog-check` |
| `charter-check` | `charter-law-break` | — | `make charter-check` |
| `claims-audit` | `claims-audit` | — | `make claims-audit` |
| `cli-help-parity-check` | `cli-help-parity` | — | `make cli-help-parity-check` |
| `coverage` | `coverage` | — | `make coverage` |
| `determinism-check` | `nondeterministic` | — | `make determinism-check` |
| `docs-map-check` | `docs-map-gap` | — | `make docs-map-check` |
| `ecosystem-check` | `ecosystem-check` | — | `make ecosystem-check` |
| `fd-check` | `fd-check` | — | `make fd-check` |
| `flake-check` | `flake` | — | `make flake-check` |
| `golden` | `golden` | — | `make golden` |
| `homeostatic-heal-check` | `homeostatic-heal-check` | — | `make homeostatic-heal-check` |
| `inline-check` | `inline`, `inline-hygiene` | — | `make inline-check` |
| `kern-scan-check` | `kern-scan` | #489 | `make kern-scan-check` |
| `lean` | `lean-sorry` | — | `make lean` |
| `lean-pin-check` | `lean-pin-drift` | — | `make lean-pin-check` |
| `license-header-check` | `license-header` | #493 | `make license-header-check` |
| `llms-check` | `llms-drift` | — | `make llms-check` |
| `memcheck` | `memcheck` | — | `make memcheck` |
| `mutate-log-check` | `mutate-log` | #487 | `make mutate-log-check` |
| `mutation-lock-check` | `mutation-lock` | — | `make mutation-lock-check` |
| `os-stress` | `os-stress` | — | `make os-stress` |
| `perf` | `perf-threshold` | — | `make perf` |
| `perf-check` | `perf-regression` | — | `make perf-check` |
| `pool` | `pool-limit` | — | `make pool` |
| `probe` | `probe` | — | `make probe` |
| `registry` | `casetarget-gap`, `registry-dup-numbers`, `registry-fuse` | — | `make registry` |
| `scorecard-check` | `scorecard-check` | — | `make scorecard-check` |
| `self-verify` | `self-verify` | — | `make self-verify` |
| `simplify-check` | `simplify-check` | — | `make simplify-check` |
| `smt-stress` | `smt-stress` | — | `make smt-stress` |
| `spawn-check` | `spawn-timeout` | #477 | `make spawn-check` |
| `status-check` | `status-drift` | — | `make status-check` |
| `stress` | `stress` | — | `make stress` |
| `telemetry` | `telemetry-full` | — | `make telemetry` |
| `telemetry-quick` | `telemetry-detects` | — | `make telemetry-quick` |
| `temp-isolation-check` | `temp-isolation` | — | `make temp-isolation-check` |
| `test` | `codec-dispatch`, `core-gate`, `model-verify`, `simd8-masking` | — | `make test` |
| `test-fault` | `test-fault` | — | `make test-fault` |
| `trace-check` | `trace-check` | — | `make trace-check` |
| `trust-docs-check` | `trust-docs-missing` | — | `make trust-docs-check` |
| `version-check` | `version-consistency` | — | `make version-check` |

## Паритет с реестром

Целей в карте: **202**; класс CHECK в `registry.py`: **202**;
записей `CASE_TARGET`: **248** (make-исполнимых **244**); без кейса вне `NO_CASE_OK`: **0**.


ядро <!-- fact:core_tests -->460 · next <!-- fact:next_tests -->53 · каталог <!-- fact:catalog -->491 ·
CHECK-цели <!-- fact:check_targets -->200 · can-fail кейсы <!-- fact:canfail_cases -->245 ·
якоря <!-- fact:anchors -->204 · цели реестра <!-- fact:registry_targets -->273 · META <!-- fact:meta_targets -->55 ·
теоремы Lean <!-- fact:lean_theorems -->147 · QuixBugs SMT <!-- fact:quixbugs.smt -->6 · QuixBugs differential <!-- fact:quixbugs.differential -->40
