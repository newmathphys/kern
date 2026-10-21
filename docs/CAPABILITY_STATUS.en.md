# HONEST CAPABILITY STATUS — KERN

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->402 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->462 · CHECK <!-- fact:check_targets -->140 · cases <!-- fact:canfail_cases -->157 · anchors <!-- fact:anchors -->123 · registry <!-- fact:registry_targets -->174 · META <!-- fact:meta_targets -->22 · Lean <!-- fact:lean_theorems -->143 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->33/40 diff.

> English mirror of [`CAPABILITY_STATUS.md`](CAPABILITY_STATUS.md). **Date:** 2026-10-10
> (status sections; the defect registry is kept up to date). **Principle:** a level is
> assigned ONLY from a real run (command → exit code → output). Nothing is "working"
> because it is described as such.
>
> Levels: **MEASURED** (run, there is a number) · **TESTED** (there is a test) ·
> **SMOKE** (it starts, but without a strict check) · **FRAMEWORK** (a skeleton exists,
> not measured) · **NOT IMPL** (absent).

---

## 1. What is MEASURED (core, `kernc` / Zig)

| Capability | Level | Evidence |
|:--|:--|:--|
| Build on Zig 0.17.0 | MEASURED | `zig build` → exit 0 |
| Belnap B4 algebra (join/meet/De Morgan) | TESTED | exhaustive enumeration, tests OK |
| .kimg header (128 B) + safe arithmetic | TESTED | SEC-01 offset bomb |
| .kimg descriptor (96 B) + reserved bytes | TESTED | CONF-15 |
| Merkle root (recompute + substitution) | TESTED | `MERKLE: ... catches substitution` |
| Building a .kimg v1.3 image from .kern | MEASURED | `kernc build examples/project.kern` → 6 objects |
| KERNFS (paths, status, contract, zero-copy) | MEASURED | `kernc cat` → `T`, `{}`, content |
| Path traversal / NUL injection | TESTED | CONF-13, SEC-03 |
| Writing is forbidden (`AccessDenied`) | TESTED | CONF-06 |
| Gate of Truth: verdict is ONLY external | TESTED | 0xAA → e=0 |
| Z3 bridge (SMT-LIB2, child process) | **MEASURED** | `z3-solver` installed; `kernc prove` → **e=1 (PROVEN)** and `e=0` (counterexample). Timeout with a killer thread. Without z3 — graceful `ToolError`→e=0 |
| KERN-X VM (fuel, HALT, opcodes) | TESTED | OutOfFuel at 10k NOP |
| Proof cache (AST→verdict) | TESTED | hits/misses, single-flight, eviction |
| CLI: build/check-integrity/ls/cat/verify/unify/run/handoff/report/audit/prove | MEASURED | all executed |
| 5 SMT theories (UNSAT-core, arrays, CHC, strings, CEGIS) | MEASURED | `kernc audit` → 5/5 worked against real Z3 |
| C-ABI (`libkern.so`, 7 functions) | MEASURED | `zig build lib` + `examples/capi_demo.py` (Python) and C |

**Numbers:** `zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig` →
**402/402 OK** (Debug AND ReleaseSafe); without `z3` in `PATH` — 393 passed + 8 skipped
(solver-dependent tests skip by design).
Reference `valid_v1_3.kimg` → the Merkle root matches Python↔Zig (confirmed both ways).
Decision coverage → **100.0 %** (30/30). Mutation score → **100.0 %** (1345/1345 killed,
0 survivors; canonical gate 40/40).

---

## 1b. Formal proofs (Lean 4) — MEASURED

| File | Theorems | Compilation |
|:--|:--|:--|
| `formal/KernAllMath.lean` | De Morgan ×2, involution, JOIN_K comm/assoc/idem, distributivity, `contradiction_isolation : T⊔F=B`, anti-vacuity, **`fuel_bounds_influence`** | ✅ Lean 4.34.0, **0 errors, 0 sorry** (Pure Core) |
| `formal/KernDfsTermination.lean` | `traversal_terminates`, **`fuel_bounds_influence`** + its own lemma `foldl_congr_list` | ✅ Pure Core |
| `formal/KernTalk.lean` | `ai_hallucination_yields_conflict`, `consistent_yields_truth` | ✅ Mathlib (ℝ) |
| `formal/KernTalkND.lean` | `nd_violation_yields_conflict` (N-dimensional unification) | ✅ Mathlib |
| `formal/KernConvergence.lean` | STRONG `convergence_guaranteed` + `convergence_guaranteed_weak` (a real corollary) | ✅ Mathlib |
| `formal/KernZeroCopy.lean` | `zero_copy_is_lossless`, `slice_subset`, `slice_idempotent` | ✅ Mathlib |
| `formal/KernSemanticGap.lean` | the ℤ ↔ i32 gap (8 theorems) | ✅ Mathlib |
| `formal/FarkasSoundness.lean` | soundness of the proof checker: `int_not_le_iff`, `farkas_2_sound`, `farkas_3_sound`, `three_valued_check_sound`, `vacuous_requires_unsound`, `skip_preserves_belnap_join` | ✅ Lean-core (`omega`), 0 sorry |

**Proof:** `./formal/check.sh` → `ALL LEAN PROOFS OK (0 errors, 0 sorry)` — 8 files, 137 theorems.

**Honesty (fixed 2026-10-11).** Two theorems were **TAUTOLOGIES** and were replaced with
meaningful ones:
* `fuel_bounded_dfs_always_terminates` had the shape `∃ res, f u = res := ⟨_, rfl⟩` — in
  Lean every function is total, so such a "theorem" holds for ANY function and proves
  nothing. Replaced by `fuel_bounds_influence` (fuel bounds the influence zone — real
  induction).
* `convergence_guaranteed_weak` was proved with the witness `human_max` (reflexivity of
  `≤`) and did not depend on `adapt` — it is now a real corollary of the strong theorem.
* `traversal_terminates` is honestly marked as an unfolding of the definition
  (`WellFounded r` ≡ `∀ a, Acc r a`).

Also: in the document the theorem `ai_hallucination_yields_conflict` contained `sorry`
(a stub). Here it is proved for real (via `le_max_right`/`min_le_left`).

---

## 1c. Certification contour (DO-178C / ISO 26262 / EAL7) — MEASURED

| Capability | Level | Evidence |
|:--|:--|:--|
| Decision coverage (self-instrumented) | MEASURED | `make coverage` → **100.0 %** (30/30, threshold 95 %) |
| MC/DC vectors for the Gate decisions | TESTED | `src/tests/mcdc_gates_test.zig` (8 tests) |
| Incremental SMT `push/pop` | MEASURED | 527 ms → 26 ms (**20×**), 0 false `proved` |
| Solver crash (SIGPIPE) | TESTED | `src/tests/z3_crash_test.zig` (4 tests), KERN survives |
| Memory shortage (2 MB) | TESTED | `src/tests/oom_stress.zig` → `error.OutOfMemory` |
| Real SIGBUS on mmap | TESTED | `src/tests/fault_injection_test.zig` (2 tests) |
| Fuzzing, 1 000 000 mutations | MEASURED | 362 ms, **0 panics** |
| C-ABI (`libkern.so` + `kern.h`) | MEASURED | called from Python (`ctypes`) and C (`cc -lkern`) |
| Hermetic build (musl, static) | MEASURED | sha256 **bit-for-bit** identical across 2 builds |
| Tool Qualification Package | DONE | `formal/certification/`: 53 requirements traced |
| Proof Checker (structural + MUS) | TESTED | `src/verifier/proof_check.zig` |

**Limitation (honestly):** the coverage is collected by **our own counters**, not by
LLVM source-based coverage — Zig does not support `--coverage`, and `llvm-cov`/`kcov` are
not present in the environment. The Proof Checker re-checks Z3's output mathematically
(holes, premise binding, `mp`, resolution, Farkas), but it is **not Alethe/LEFSC** — that
build of Z3 does not emit that format.

### External benchmarks (no local models)

| Benchmark | Result |
|:--|:--|
| QuixBugs (real execution) | **33/40 (82.5 %)** |
| CHC loop benchmark (SV-COMP style) | **11/11**, 424 ms |
| SMT (Alive2 / Hacker's Delight) | **8/8** |
| Cross-check Z3 ↔ cvc5 | **9/9 agreement, 0 divergences** |
| SWE-bench Lite (Docker, official) | **3/3 resolved** |
| Refactory (differential, NOT the KERN core) | 1705/1782 (95.7 %), 0 false positives out of 2442 (see #80) |
| HumanEval / HumanEval+ (official EvalPlus) | 0.524 / 0.500 |
| MBPP+ (378 tasks, official EvalPlus) | ✅ base **0.812**, plus **0.698** (drop −11.4 pp) |

**Found and fixed in the MBPP generator:** for MBPP the prompt is only a docstring
(without `def`), and the old extractor cut the signature → the sample became invalid code
and `pass@1` collapsed to **0.000**. That was a defect of the TOOL, not of the model.

**Second tool defect (2026-10-14, #51):** models with "reasoning" spend the whole
`max_tokens` budget on the `reasoning_content` field and return `content` as `null` →
`TypeError` → all samples empty → `pass@1 = 0.000`. Fixed
(`chat_template_kwargs.enable_thinking = false` + a `reasoning_content` fallback), after
which the result above was obtained.

---

## 2. What is MEASURED (KERN-Next, `kernx`)

| Capability | Level | Evidence |
|:--|:--|:--|
| .kern language parser | TESTED | 3 tests |
| Validator (§8, 10 rules) | TESTED | 2 tests |
| SQLite catalogue .kdb | MEASURED | `sqlite3 project.kdb "SELECT ..."` |
| Snapshot + diff | MEASURED | `kernx diff` → `+2/-2` |
| Agent packet (§17) | MEASURED | `agent_packet.json` |
| Human report (§14.1) | MEASURED | `report.md` |
| Incremental cache (skips unchanged) | MEASURED | a second build → "skipped" |
| Stable IDs | TESTED | re-parsing → the same id |

**Numbers:** `zig build test-next` → **38/38 OK** (37 named tests + 1 aggregating `test {}`
in `src/next/test_root.zig`; `docs/TEST_CATALOG.md` lists the named ones, and the catalogue
is generated from the sources).

---

## 3. WRITTEN BUT NOT MEASURED (skeletons)

| Artefact | Level | Why it is not measured |
|:--|:--|:--|
| `Dockerfile` | FRAMEWORK | no `docker` in the environment |
| `Makefile` | SMOKE | the targets are written; they need `zig`/`docker` in `PATH` |
| `src/sdk/kern_sdk.py` | MEASURED | a wrapper over the CLI: calling the real `kernc` succeeds |

---

## 4. NOT IMPLEMENTED (claimed in the specification, no code)

| Claimed | Status |
|:--|:--|
| HTTP/REST daemon (`kern_daemon.zig`) | NOT IMPL |
| WASM/WASI sandbox (`kern-core-wasm`, Rust) | NOT IMPL |
| Lean 4 transpiler (KERN-D → Lean) | NOT IMPL (but the invariants themselves are proved and compile — see §1b) |
| C-ABI plugins (`include/kern_plugin.h`, `plugin_loader.zig`) | NOT IMPL |
| `.kern.bundle` format (Markdown+Binary+ZIP) | NOT IMPL |
| PQC signatures (Dilithium) | NOT IMPL |
| ~~`attest` (break-glass)~~ | **IMPLEMENTED**: `make attest` → the Ed25519 image signature is VALID (see §1c and `docs/ATTESTATION_PASSPORT.md` §0.2) |
| Differential Datalog (Δ) in the graph | NOT IMPL |
| SIMD implementation of Belnap | NOT IMPL |
| `vacuum`/GC, merging .kbin branches | NOT IMPL |
| ECC-RAM scrubbing / Rowhammer mitigation | NOT IMPL (physics outside software) |
| Token-ROI dashboard, Prometheus/Grafana | NOT IMPL |
| LLM orchestrator (`SwarmOrchestrator`) | NOT IMPL (an honest `NotImplementedError`) |

---

## 5. What is NOT verified FOR REAL (risks)

1. ~~**Z3 bridge**~~ — **CLOSED 2026-10-11**: `z3-solver` is installed and the Gate really
   returns `e=1` (PROVEN) and `e=0` (counterexample). Remaining: on machines WITHOUT z3 the
   behaviour is as before (graceful e=0).
2. ~~**Solver timeout**~~ — **CLOSED**: a hard timeout with a killer thread (`Z3Bridge`);
   a solver crash is caught (`z3_crash_test`) and KERN survives.
3. **Docker**: the `Dockerfile` is a working skeleton. **The Docker daemon IS AVAILABLE**
   (verified: Engine 29.8.1; the official SWE-bench Lite was run in containers →
   **3/3 resolved**, 0 infra failures). `docker-compose.yml`, `kern-cluster.yaml` and
   `vscode-kern/` were REMOVED from the repository as unverified skeletons.
4. **BLAKE3 vs SHA-256** — **CLOSED**: `HashAlgo.DEFAULT = .blake3`
   (`src/core/hash_algo.zig`), i.e. the default is **BLAKE3** (8-lane SIMD variant);
   SHA-256 is supported as the second algorithm (2). The `hash_algo` field is
   **validated** (1=BLAKE3, 2=SHA-256, anything else → rejected), and the algorithm name is
   taken FROM THE IMAGE HEADER — so a report label cannot drift from what was actually
   checked (defect #66).
5. **`libsqlite3`** — the only system dependency of KERN-Next.
6. **Read speed**: "76 GB/s" is RAW addressing; a safe read (with SHA-256 verification) is
   **231 MB/s** (330× slower). See METRICS §4.
7. **Compression** — **PARTIALLY CLOSED**: `deflate` (codec `0x02`) is implemented via
   `std.compress.flate` and covered by end-to-end tests; `compression_codec`,
   `compressed_size` and `uncompressed_size` are real fields, not placeholders.
   `zstd` (codec `0x01`) is declared but NOT implemented: Zig std ships only a
   decompressor and no static `libzstd.a` exists here — linking it would break the hermetic
   musl build. Requesting it returns an honest `error.CodecUnsupported` rather than failing
   silently.
8. **The coverage test reads global counters**: under `--test-filter` it reports a false
   0 %. `make coverage` runs the full suite (correctly).

---

## 6. Registry of defects found by the audit of 2026-10-11

| # | Defect | Class |
|:--:|:--|:--|
| **1** | `KimgHeader.parse` did not validate `major` and `hash_algo` (the spec requires it) | correctness |
| **2** | `checker_id` mask: `@truncate` wrapped 32→0 (**the bug exists in the spec too**) | security |
| **3** | Field 20..24 was named `schema_version` instead of `hash_algo` | spec conformance |
| **4** | `Eq2.encode(p,n)` was missing (public spec API) | API completeness |
| **5** | 2 Lean theorems were **tautologies** (`∃ res, f = res`) | proof honesty |
| **6** | "51 GB/s" was presented as read speed (it is RAW addressing) | metric honesty |
| **7** | The mutator edited sources **in place** (wiped edits, broke parallelism) | tooling |
| **8** | The mutator mutated **inside comments** → false "survivors" | tooling |
| **9** | C-ABI `kern_localize` was **uncallable** (one line served as both declaration and formula) | interface |
| **10** | `kernx build` crashed with a **raw traceback** instead of a clear error | UX |

---

## 6a. Early journal entries (#31–#47) — moved in from METRICS

Found by the 2026-10-20 audit (defect **#226**): the journal stopped at **#10** and
continued at **#48**, although entries #31–#47 existed — but only in
`docs/METRICS.md` (§32, §38–§39, K1+K2 and the "Defects found by THIS extension"
table). They are summarised below; the source is METRICS.

| # | What was broken | Class |
|:--:|:--|:--|
| **31** | `tools/diff_disasm.py` broken (class #30: it printed a result but never failed) | tooling |
| **32** | CLI returned **0** on a failed check | gate |
| **33** | `disasm` silently skipped a vanished function | gate |
| **34** | **13 targets were vacuous by construction** (they could not fail) | harness |
| **35** | the attack demonstrator did not fail on regression | harness |
| **36** | thresholds were **decorative** (printed, never enforced) | harness |
| **37** | `smt_bench` printed mismatches but did not count them | gate |
| **38** | the harness **committed its own injected fault** | process |
| **39** | the ABSINT test checked `lo >= 10` on an **empty** interval | test |
| **40** | `kernc prove` printed "not proven" yet returned **0**; without z3 — also 0 | gate |
| **41** | `make coverage` only printed a report — stayed green at 0 % | gate |
| **42** | `smt-stress` printed "X/Y matched" but the exit code never changed | gate |
| **43** | `cert`: the `@` prefix **swallowed** the error — a missing file left the target green | gate |
| **44** | `fuzz_ast` printed "PANICS: 0" as a **literal**, not a measured value | test |
| **45** | `audit_manifest.sh` printed FAIL but **always** returned 0 (and the counter inside a subshell never worked) | gate |
| **46** | `cert` called `unlink()`, while `verify_restored` only checked existing files → deletion of `TRACEABILITY_MATRIX.md` **landed in commit 92bf484** | process |
| **47** | `chc_bench.zig` printed "X/Y matched", exit code never changed (class #36/#42) | gate |

**Explicit gaps** (verified by `grep` across the whole repository): numbers
**#11–#30** and **#169** have no entry in any document — they were never used.
This is recorded here so the showcase range is not read as "225 consecutive
entries".

## 6b. Registry of defects from the audit of 2026-10-14 (#48–#55)

| # | Defect | Class |
|:--:|:--|:--|
| **48** | The line `theorem CANFAIL_PROBE := by sorry` was left over from an interrupted run | tooling/honesty |
| **49** | The CI Lean stage used `./formal/check.sh \| tail -3` — the RC came from `tail`, not from the check | tooling/CI |
| **50** | A stale `.mutation.lock` (dead PID) blocked the mutator forever | tooling |
| **51** | `humaneval_api.py` did not understand reasoning models: `content = null` → `TypeError` | tooling/benchmark |
| 52 | `tools/mutate_zig.py` was BROKEN in HEAD | tooling (critical) |
| **53** | `audit_manifest.sh` used Zig 0.13 syntax (`zig test src/test_root.zig`) | migration |
| **54** | `slugify` lower-cased ASCII only | correctness |
| 55 | `payloadSlice` and `objectPayloadRaw` chose the SIZE in opposite ways | correctness (latent) |

---

## 6c. Registry of defects from the audit of 2026-10-15 (#56–#58)

| # | Defect | Class |
|:--:|:--|:--|
| 56 | The SLSA tool attested Debug binaries | tooling/attestation |
| **57** | Stale numbers in the documentation after the migration | documentation |
| **58** | `tools/audit_manifest.sh` read the wrong log name | tooling/CI |

---

## 6d. Registry of defects from the audits of 2026-10-16/17 (#59–#119)

| # | Defect | Class |
|:--:|:--|:--|
| 59 | `.github/workflows/ci.yml` was INVALID YAML | CI (critical for DX) |
| 60 | `kernc cat`/`ls` printed DATA to stderr | CLI/pipeline (critical for automation) |
| 61 | The order of rules in `.gitignore` | repository/attestation |
| 62 | The SLSA attestation was SELF-REFERENTIAL | attestation (false failure) |
| 63 | `canfail` SILENTLY destroyed uncommitted edits | tooling (loss of work) |
| 64 | A spinlock on the hot path of `compat.io()` | performance/concurrency |
| 65 | `canfail` restored SOURCES but not ARTEFACTS | tooling (false results after a run) |
| 66 | Reports printed the WRONG hash algorithm | documentation/reporting |
| 67 | `canfail` mixed failure classes in the summary line | tooling (wrong reporting) |
| 68 | `tree_digest()` did not see UNTRACKED files | attestation (false failure) |
| 69 | Editing a FAULTABLE file DURING a canfail run was silently destroyed | tooling (loss of work) |
| 70 | The evidence collector itself broke the attestation and captured probe state | attestation (false failure) |
| 71 | Rollback restored ALL files in the list, not only the changed ones | tooling (loss of work) |
| 72 | Atomic-rollback temp files leaked into the source fingerprint | attestation (false failure) |
| 73 | The zombie check in telemetry counted ALL zombies on the system | tooling (wrong metric) |
| 74 | QEMU hung FOREVER on the Z3-bridge tests | tooling (infinite deadlock) |
| 75 | Cloud CI failed in 0 seconds: a hard-coded toolchain path | infrastructure (red CI) |
| 76 | `CAN-FAIL` failed in the cloud: a build artefact leaked into the integrity snapshot | infrastructure (red CI) |
| 77 | The evidence gate missed a failure masked by `RC=0` | tooling (blind gate) |
| 78 | A solver timeout was reported as a "DIVERGENCE" in `kernc smtlib` output | documentation (false alarm) |
| 79 | A self-referential LOG broke the attestation: a vicious circle | attestation (vicious circle) |
| 80 | The Refactory metric did not distinguish classes | methodology (the metric measured the wrong thing) |
| 81 | An evidence log could contain TWO runs (concurrent write) | tooling (the log was not a single run) |
| 82 | The release binary went STALE after proof-checker changes | process (artefact lagged behind the code) |
| 83 | `integer overflow` panic in the decompressor | memory/safety |
| 84 | The "zip bomb" test failed on CORRECT behaviour | test (wrong expectation) |
| 85 | The "substitution" test passed VACUOUSLY | test (vacuous check) |
| 86 | 2 tests from #55 failed after the compression integration | test (stale assumption) |
| 87 | The attestation hashed ITS OWN evidence (vicious circle) | tooling (circular dependency) |
| 88 | Editing a FAULTABLE file DURING a harness run breaks its integrity check | process (edit during a run) |
| 89 | A stale patch template turned a can-fail case into a SILENTLY "skipped" one | tooling (the check stopped checking) |
| 90 | An mtime heuristic in `artifact_check.py` produced a FALSE failure | tooling (false positive) |
| 91 | Different locking mechanisms in `canfail` and the mutator → they could overlap | tooling (tool race) |
| 92 | The attestation covered binaries that a normal `zig build` REWRITES | tooling (the attestation did not survive) |
| 98 | Deep Nesting Bomb: unbounded parser recursion → SIGSEGV | memory/safety (stack overflow) |
| 99 | NULL pointers in the C-ABI → SIGSEGV | security (DoS from a foreign process) |
| 100 | Type mismatch in the public C-ABI header | interface (incompatible types) |
| 101 | MEMORY LEAK in `extractAsserts` (found by allocator fault injection) | memory (leak on a partial OOM) |
| 102 | The mutation tester covered only the OLD core | tooling (the check did not cover the new core) |
| 103 | The C-ABI was OUTSIDE mutation coverage | tooling (interface outside coverage) |
| 104 | `witness_model` was ALWAYS `null` | logic (the witness field was always empty) |
| 105 | A memory leak OPENED by the fix for #104 | memory (leak in production) |
| 106 | The mutator mutated INSIDE string literals | tooling (noise instead of signal) |
| 107 | SAMPLING BIAS: 64 % of mutants came from ONE file | methodology (the metric measured the wrong thing) |
| 108 | A pipe regression test HUNG instead of failing | test (a hang instead of a refusal) |
| 109 | `child.wait()` was called with the read end of the pipe still OPEN | core (potential pipe deadlock) |
| 110 | THE MUTATION SCORE WAS MEASURED WITHOUT A SOLVER (found by measurement, not by guessing) | methodology (false survivors, unreproducible score) |
| 111 | The "slow mutator" was treated WRONGLY: 93 % of the cost is execution, not compilation | tooling (optimising the wrong bottleneck) |
| 112 | Environment variables SILENTLY had no effect IN TESTS | tooling (configuration that never applied) |
| 113 | CI #68/#69 went RED because of a HARD-CODED HASH in a test (root cause found via the cloud API) | tooling (a test broke on a legitimate data change) |
| 114 | `canfail` POLLUTED COMMITTED EVIDENCE (found by a FULL run) | tooling (a run spoils the artefacts it protects) |
| 115 | A VACUOUS `slsa` case: the injection went into a NON-attested binary | tooling (the case proved something else) |
| 117 | The SKIP reason for a Zig builtin was a FOREIGN parser error (`invalid syntax`) instead of a language-level reason | tooling (misleading diagnostic) |
| 118 | The proof checker rejected a valid Z3 certificate -> verdict degraded to SKIP: the gate is conservative, never silently optimistic. Diagnosis on the ACTUAL Z3 proof (`:produce-proofs true`): it needs `def-axiom` (the `ite` axiom, i.e. the `@max(1, …)` unfolding), `trans*` and `th-lemma arith triangle-eq` (17 steps, 3 unverifiable rewrites, 0 holes); in QF_BV the proof is not even parseable. Deliberately NOT "fixed": trusting those steps would fake `holes: 0` and a false `verified`. Open: sound `ite`-axiom + `trans*` support | tooling (proof-checker coverage) |
| 119 | A **deflated** image silently disabled the Truth Gate: `/raw/` returns a zero-copy slice, and for a compressed object that is the compressed bytes, so `verify` found no contract at all and every claim fell back to `e=0` (even the 2-contract toy). Fixed in the CLI `verify` (direct object lookup + `decompressObject`); regression step added to `make kimg-deflate` | core/CLI (gate silently disabled) |
| 116 | "Edit during a run" was closed INCOMPLETELY: a file the case ITSELF edited was restored from the case-start backup | tooling (silent loss of work) |
| 117 | **SKIP diagnostics leaked a foreign parser's error** (found by a shadow contract on REAL third-party code): checking the real `isAligned` from `andrewrk/zig-general-purpose-allocator` gave a correct `SKIP — binary operator`, but a Zig builtin (`@mod`) produced `SKIP — invalid syntax (<unknown>, line 1)` — a Python parser message inside a Zig diagnostic, violating the rule that a SKIP must name its reason. Fixed with `_clike_parse(text, lang)` (5 call sites) which reports `zig-expression outside the subset: 'addr - @mod(addr, alignment)'`; locked in by an edge case and verified by `canfail --only edge-cases` | tooling (misleading diagnostics) |

| 120 | The **`N` (UNKNOWN) verdict was printed as "CONTRACT VIOLATED"** (found by a shadow contract on zlib): the solver's three-valued verdict was collapsed into two. For `zcallocSizeBounded` (multiplication of two variables in BV32 — non-linear, Z3 returned `unknown` on timeout) the tool reported `[FAIL] CONTRACT VIOLATED` although there was NEITHER a proof NOR a counterexample — a false alarm in the most dangerous direction (the user would go and "fix" correct code). Fixed: the `N` branch is parsed SEPARATELY and prints `[N] NOT SOLVED (solver returned unknown)`, the summary has a `NOT SOLVED` counter, and `--emit-pytest`/`--json`/SARIF receive `UNKNOWN` instead of `VIOLATED` | tooling (false alarm) |
| 121 | **FALSE REJECTION BY THE PROOF CHECKER: a numeric literal as an ATOM vs a LIST** (found by a shadow contract on Rust `saturating_add`): in the source `.smt2` a negative number is an ATOM (`(>= a -2147483648)`), while Z3 prints it in the proof as a LIST (`(>= a (- 2147483648))`). Comparing an `asserted` premise with a contract clause therefore failed, `premises_unbound` grew, and the checker REJECTED A VALID PROOF ("premises not bound"). It only affected proofs that actually lean on the negative bound (not `divCeil`, which is why it went unnoticed). Fixed by normalising during premise binding (`sexpEqNum`: atom `-N` == list `(- N)`); inside a Z3 proof literals are uniform, so no other check changed. SOUNDNESS: `-N` and `(- N)` are the same number, so an invalid proof cannot become valid. Effect: Rust `saturatingAdd` is `PROVEN`, `[PROOF VERIFIED]` | proof checker (false rejection) |
| 122 | **COMPARING `Int` WITH `Bool` IN A FUNCTION BODY** (found by a shadow contract on C): a function whose body is a "bare" comparison (`return len <= size - offset;`) was translated into `(assert (= result (<= len (- size offset))))` — an equality between `Int` and `Bool`. Z3 accepted this ONLY by lenient coercion, and the proof checker could not bind such a premise (`premises_unbound`), so a valid proof was rejected. Visible only for functions RETURNING a comparison: with an `if/else` body the extractor already built an `ite` with numeric branches. Fixed by an explicit coercion (`value_of`: a comparison/connective becomes `(ite X 1 0)` for `Int` and `(ite X (_ bv1 w) (_ bv0 w))` for BV) in `build_smt`, `build_overflow_smt` and `build_smt_bv`. In C/C++/Rust/Zig a boolean in integer position IS 0/1, so the coercion is the exact semantics; the dependency on undocumented Z3 coercion is gone | extractor (ill-sorted formula) |
| 123 | **`unit-resolution` OVER TRUSTED LEMMAS: an honest SKIP, NOT fixed** (found by a shadow contract on musl `abs`): the Z3 proof contains `(unit-resolution @x210 (unit-resolution @x150 ((_ th-lemma arith) ...) $x160) ((_ th-lemma arith) ...) false)` — the premises of `unit-resolution` are `(_ th-lemma arith)` steps, not clauses. The checker cannot parse such premises and marks the step `unitres_bad` -> `[SKIP] invalid unit-resolution step`. The temptation to "take `th-lemma` on faith" was rejected deliberately: that would turn `holes: 0` into fiction (exactly defect #81). Left as OPEN work: distinguish "the step is DEFINITELY wrong" from "the step is UNVERIFIABLE because a premise is trusted" (the latter should count as `trusted`, not as an error). Meanwhile the gate stays conservative: the control mutation `kern_absBroken` (`return a;`) is REFUTED with the counterexample `a = -2147483647`, while the original is honestly not confirmed | proof checker (conservative refusal, open work) |
| 124 | **Mutator "moving target"** — `sample_stratified` used ONE sequential PRNG over files, so any change in the number of sites in one file re-drew the sample in ALL other files: the score read 95.0 % → 82.5 % → 80.0 % on the SAME code and seed (a re-draw, not a regression) | **FIXED**: an independent per-site score `sha256(seed:file:line_text:mutation:dup)` with a TEXT key (not a line number), plus a `--full-file` flag (Option B). PROVEN: removing 187 sites in `proof_check.zig` left the sample in the other 14 files unchanged (27/27). Result: the score is now REPRODUCIBLE (85.0 %, 34/40) |


> **Scope of this index.** The table above is a complete index of **all 63 numbered
> entries** (#52, #55–#56, #59–#92, #98–#124). The FULL text of every entry — the
> mechanism, the evidence and the fix — is in the Russian original
> [`CAPABILITY_STATUS.md`](CAPABILITY_STATUS.md) §6–§6d.

---

## 6d-1. Registry gap closed: #125–#152

> **Why this section exists.** Defects **#125–#152** were recorded in `METRICS.md` (RU) but were **missing from this registry table**
> — a real documentation gap found by the line-by-line audit of 2026-10-20. They are listed here so that the range `#1–#235`
> has no holes. Verdicts are the same as in the Russian original.

| # | Defect | Status |
|:--|:--|:--|
| **125** | **`checksPass()` returned `true` for an EMPTY verdict** (0 steps, `is_unsat=false`): only error counters were checked. Added `proof_steps == 0 -> false`. | FIXED |
| **126** | **Race of two tree-patching instances**: a run killed by `SIGTERM` left the rollback undone. `tools/tree_lock.py` + SIGTERM/SIGINT/SIGHUP handlers + refusal to start on a dirty `src/`. | FIXED |
| **127** | **`check-integrity` did not recompute object-body digests**: 11 of 20 bit-flip injections passed silently (only stored descriptors were compared). | FIXED |
| **128** | **Object names were not part of the Merkle root**: replacing a PRINTABLE letter in a name went unnoticed. The root is computed over the FINISHED buffer (`sealImageRoot`), so writer and reader cannot diverge. | FIXED |
| **129** | **`kernc verify` returned `rc=0` with a refuted contract** — CI never saw the closed Gate. Now `refuted > 0 -> rc=1`. | FIXED |
| **130** | **Vacuous `pcc-check` case**: the fault was injected, the target stayed green (forgery was caught by `proof_concludes_false`, not by `checksPass`). | FIXED |
| **131** | **`src/next/*.zig` were in the mutator but `test_root.zig` never imported them**: 51 sites were counted as "survived" although they were never compiled. For `src/next/` the mutator now runs `zig build test-next`. | FIXED |
| **132** | **Vacuous `gen-tests-check` case**: the reference function was broken while the generator computed the expectation by executing it — the tests stayed green. | FIXED |
| **133** | **Vacuous `simplify-check` case** (fourth in a row): the fault did not touch the transformation under test. | FIXED |
| **134** | **False accusation of a safe function**: after an early `if cond: return` the path was not narrowed by `NOT cond`, so a guard clause produced a false `[CRASH PATH]` (`get_safe`). | FIXED |
| **135** | **`@kern:len` was read from the whole file**: the second function overwrote the length of the first. Now only the comment block directly above `def` is read. | FIXED |
| **136** | **`bounds-check` had no target of its own in the `Makefile`**: the registry showed a CHECK target without a case. `tools/bounds_check.sh` was split out. | FIXED |
| **137** | **`_smt_counterexample` returned `None` for both `UNSAT` and `N`** (solver did not decide): an undecided formula was counted as PROVEN. | FIXED |
| **138** | **Local variables were never declared in SMT**: Z3 answered with an error -> `N` -> false PASS. All variables of a formula are declared now. | FIXED |
| **139** | **`_subst` wrapped an already-built s-expression in parentheses** (`((+ i 1))`) -> unparsable formula -> `N` -> false PASS. | FIXED |
| **140** | **Cases patched files via literal anchors**: after a refactor `--check-anchors` reported "anchors not applicable" — the case had silently stopped checking anything. | FIXED |
| **141** | **`--xray` required the `# @kern:len(arr) = N` crutch**, violating Zero-Annotation. Length now comes from list literals and from `len(arr)` in conditions. | FIXED |
| **142** | **Vacuous `state-inv-check` case**: the wrong mechanism was broken (`_smt_counterexample` instead of `_smt_verdict`). | FIXED |
| **143** | **The checker rejected a CORRECT Z3 proof**: a negative Farkas weight (literal polarity) was treated as an error. It is now `.structural_only`, not `.bad`. | FIXED |
| **144** | **Vacuous `ffi-bridge-check` case**: the fault went into `_smt_verdict` while presets call `_prove_checked`. | FIXED |
| **145** | **`rls_safe` stayed `[UNKNOWN]`**: the invariant was checked as ONE compound formula (Tseitin atoms). Now checked per component (De Morgan) -> `[PASS] PROVEN trusted: 0`. | FIXED |
| **146** | **`SPURIOUS MODEL` reported for a CORRECT model**: `=` between boolean subformulas was not evaluated, so a valid counterexample was hidden. "Cannot compute" now yields `unsupported`, not `spurious`. | FIXED |
| **147** | **Vacuous `action-firewall-check` and `rag-conflict-check` cases**: grep matched strings that survive a broken verdict. | FIXED |
| **148** | **Vacuous `fuzz-corpus-check` case**: the "0 panics" grep did not change when the gate was broken. | FIXED |
| **149** | **`--xray`: consecutive `if ...: return` did not narrow the path** — `[DEAD BRANCH]` was searched only inside `if/elif`. Now the path is narrowed by `NOT cond` after an early exit (as in #134). | FIXED |
| **150** | **`wasm-check` case crashed**: `src/wasm_api.zig` was missing from `FAULTABLE`, so the injection was never rolled back. | FIXED |
| **151** | **`kimg-grep-check` case was VACUOUS**: it did not rebuild the binary, so the `exit(1)->exit(0)` patch never affected the gate. | FIXED |
| **152** | **The `model_extract` test expected `spurious` where the correct answer is `unsupported`** ("did not lie" != "cannot evaluate"). | FIXED |

---

## 6d-2. Compact index of entries that exist only in the Russian original

> **Why this section exists.** The line-by-line audit of 2026-10-20 found that **65 numbers were missing from this English table**
> (`#52, #55, #56, #59–#92, #98–#124, #205`) although they are present in `CAPABILITY_STATUS.md`. They are indexed here with a
> one-line summary each, so that the range `#1–#235` has **no holes in either language**. The third column reproduces the
> **classification** used in the Russian original for those sections (it is a defect class there, not a status word).

| # | Defect (one line) | Class (as in RU) |
|:--|:--|:--|
| **52** | **The mutator itself was BROKEN in HEAD**: `return "SURVIVED" # ЛОМАЕМ` — every mutant was declared surviving, making the tool useless. It had reached commit `3915e76`. | tool (critical) |
| **55** | **`payloadSlice` and `objectPayloadRaw` chose the SIZE in opposite ways**, so the safe read path and the raw path could return different slices when `compressed_size != uncompressed_size`. | correctness (latent) |
| **56** | **The SLSA tool attested Debug binaries**, which Zig 0.17 builds **non-bit-reproducibly** (non-deterministic DWARF), so `--check` failed after **every** rebuild. | tooling / attestation |
| **59** | **`.github/workflows/ci.yml` was INVALID YAML**: an unquoted `- name: … (быстрый: без Lean/canfail)` contains `": "` inside a scalar. | CI (critical for DX) |
| **60** | **`kernc cat`/`ls` printed DATA to stderr** (`std.debug.print`), so `kernc cat img /raw/f > out.txt` produced an EMPTY file. | CLI / pipeline |
| **61** | **Rule order in `.gitignore`**: `*.log` came AFTER `!docs/evidence/*.log`, so the pattern overrode the exception and **all evidence files were ignored**. | repository / attestation |
| **62** | **The SLSA attestation was SELF-REFERENTIAL**: `tree_sha256` included `kern.intoto.jsonl` itself, and `--check` compared it with the file being verified. | attestation (false failure) |
| **63** | **`canfail` SILENTLY DESTROYED uncommitted edits**: the harness restores FAULTABLE files via `git checkout --`. | tool (loss of work) |
| **64** | **Spinlock on the hot path of `compat.io()`** in library mode: with `g_io == null` (C-ABI) every call from every thread took a global fallback mutex. | performance / concurrency |
| **65** | **`canfail` restored SOURCES but not ARTIFACTS**: after rollback of `src/*.zig` the built binary/library stayed **PATCHED**. | tool (false results after a run) |
| **66** | **Reports printed the WRONG hash algorithm**: after the default switched to BLAKE3 (`0x0001`) the labels in `src/perf_bench.zig` stayed hard-coded. | docs / reporting |
| **67** | **`canfail` mixed failure classes in the summary line**: a harness false alarm (`META_FALSE_ALARM`) was printed in the case-failure column. | tool (wrong reporting) |
| **68** | **`tree_digest()` did not see UNTRACKED files**: the list came from `git ls-files`, so an attestation built before a commit missed new files. | attestation (false failure) |
| **69** | **Editing a FAULTABLE file DURING a canfail run is destroyed silently**: the `guard_dirty_faultable()` fuse checks the tree only at START. | tool (loss of work) |
| **70** | **The evidence collector itself broke the attestation** and captured probe state (`slsa_check` ran after the first writes). | attestation (false failure) |
| **71** | **Rollback restored ALL files of the list, not only the modified ones**: `Fault.__exit__` rewrote every FAULTABLE file, so an edit made during a case was lost. | tool (loss of work) |
| **72** | **Temporary files of the atomic rollback landed in the source fingerprint**: `write_atomic` creates `<file>.canfail_tmp` with no `.gitignore` rule. | attestation (false failure) |
| **73** | **The zombie check in telemetry counted ALL zombies of the system** (`ps -eo stat=`), not the children of the run. | tool (false failure) |
| **74** | **QEMU HUNG on Z3-bridge tests**: `z3` is a native x86_64 binary, and when present in PATH the emulated ARM64/PPC64 test tried to execute it. | tool (permanent deadlock) |
| **75** | **Cloud CI failed in 0 seconds**: a hard-coded toolchain path `ZIG_DIR="${ZIG_DIR:-$HOME/opt/zig-x86_64-linux-0.17.0}"` in `tools/ci.sh`. | infrastructure (red CI) |
| **76** | **`CAN-FAIL` failed in the cloud**: a build artifact got into the integrity snapshot (the `slsa` case appends 8 zero bytes to `zig-out/bin/kernc`). | infrastructure (red CI) |

| **77** | **The evidence gate missed a failure masked by `RC=0`**: the body said «ATTESTATION MISMATCH: 1» while the last line was `RC=0`. | tool (blind gate) |
| **78** | **A solver timeout was labelled a MISMATCH** in `kernc smtlib` output (`expected sat, got timeout`). | docs (false alarm) |
| **79** | **A self-referential LOG broke the attestation**: `docs/evidence/slsa_check.log` is the log of checking the very fingerprint it is part of. | attestation (vicious circle) |
| **80** | **The Refactory metric did not distinguish classes**: `tools/refactory_diff.py` is **differential** testing, not a correctness score. | methodology (metric did not measure the claim) |
| **81** | **An evidence log could contain TWO runs** (concurrent write): two headers with different dates in one `slsa_check.log`. | tool (a log was not a single run) |
| **82** | **The release binary became STALE** after proof-checker changes: the published asset predated the CLI integration. | process (artifact lagged behind code) |
| **83** | **`integer overflow` panic in the decompressor**: an empty window `&.{}` was passed, and `rebase()` computes `capacity <= buffer.len - history_len`. | memory / safety |
| **84** | **The "zip bomb" test failed on CORRECT behaviour**: it expected an error for an understated length, while the real guard is an overstated one. | test (wrong expectation) |
| **85** | **The "tampering" test passed for nothing**: the corruption hit `data_payload_offset + 1`, which is the string pool, not the payload. | test (vacuous) |
| **86** | **Two tests of #55 failed after compression was integrated**: they used `codec = 1` as a synthetic marker, and `1` became a real codec. | test (stale marker) |
| **87** | **The attestation hashed its OWN evidence**: `tree_digest()` included the whole `docs/evidence/` folder (the output of verification). | tool (cyclic fingerprint) |
| **88** | **Editing a FAULTABLE file DURING a harness run breaks its integrity check** (no guard existed at that time). | process (edit during a run) |
| **89** | **A stale patch template made a can-fail case "skipped" SILENTLY**: after the BLAKE3 refactor the `sim-invariant` template stopped matching. | tool (check stopped checking) |
| **90** | **The mtime heuristic in `artifact_check.py` gave a FALSE failure**: `canfail` restores files with atomic write, so `mtime` is UPDATED. | tool (false positive) |
| **91** | **Different locking mechanisms in `canfail` and the mutator** (`flock` vs a PID file) allowed overlap. | tool (race between tools) |
| **92** | **The attestation covered binaries that a plain `zig build` OVERWRITES** (Debug subjects `kernc`, `kernx`, `kern-attack`). | tool (attestation did not survive rebuild) |

| **98** | **Deep Nesting Bomb: unbounded parser recursion -> SIGSEGV**: `SexprParser.parseList` recursed with no depth limit. | memory / security (stack overflow) |
| **99** | **NULL pointers in the C-ABI -> SIGSEGV**: a C caller may pass NULL where the Zig type `[*]const u8` forbids it; checks were missing. | security (DoS from a foreign process) |
| **100** | **Type mismatch in the public C-ABI header**: `kern_localize` was declared as `char *out_buf` while other functions use another convention. | interface (type incompatibility) |
| **101** | **MEMORY LEAK in `extractAsserts`** (found by allocation-failure injection): `try out.append(try allocator.dupe(...))` leaks on partial OOM. | memory (leak under partial OOM) |
| **102** | **The mutation tester covered only the OLD kernel**: `TARGETS` in `tools/mutate_zig.py` was a hard-coded list of 6 files. | tool (coverage missed new code) |
| **103** | **The C-ABI was OUTSIDE mutation coverage**: the mutator ran only `zig build test`, never `tests/c_abi_test.c`. | tool (interface outside coverage) |
| **104** | **`witness_model` was ALWAYS `null`**: the bridge looked for the prefix `"(model"`, while Z3 5.1.0 prints a bare list for `(get-model)`. | logic (witness field always empty) |
| **105** | **Memory leak OPENED by the #104 fix**: 61 calls like `b.executeQuery(q).status` discarded the owned model. | memory (production leak) |
| **106** | **The mutator mutated INSIDE string literals**: `and -> or` was applied to test strings `const src = "(assert (and …))"`. | tool (noise instead of signal) |
| **107** | **SAMPLING BIAS: 64% of mutants came from ONE file** (`proof_check.zig`: 266 of 420 sites), so a 40-mutant sample was mostly that file. | methodology (metric measured the wrong thing) |
| **108** | **The pipe regression test HUNG instead of failing**: a writer thread plus `t.join()` with no timeout. | test (hang instead of failure) |
| **109** | **`child.wait()` was called with the read end of the pipe still OPEN**: undrained solver output blocks Z3. | kernel (potential pipe deadlock) |
| **110** | **THE MUTATION SCORE WAS MEASURED WITHOUT THE SOLVER** (found by measurement, not guessing): 8 solver tests skip when `z3` is not in PATH, so bridge mutants were "false survivors". | methodology (false survivors, non-reproducible score) |
| **111** | **The "slow mutator" was treated WRONGLY: 93% of the cost is execution, not compilation** (found by PROFILING): compile 879 ms vs full test run 11 390 ms. | tool (optimised the wrong bottleneck) |
| **112** | **Environment variables SILENTLY did not work in TESTS**: `compat.envVar()` relied on libc `environ`, but the test binary does not link libc. | tool (configuration that never applied) |
| **113** | **CI #68/#69 were RED because of a HARD-CODED HASH in a test** (root cause found via the cloud API): the `CAN-FAIL` step broke on a legitimate release rebuild. | tool (test broke on a legitimate data change) |
| **114** | **`canfail` POLLUTED COMMITTED EVIDENCE** (found by a full run): the `evidence-propagates` case writes `sorry` into `formal/KernAllMath.lean`. | tool (a run pollutes the artifacts it protects) |
| **115** | **VACUOUS `slsa` case: the injection went into a binary that is not attested** (`kernc` instead of `kernc-hermetic`). | tool (the case proved something other than claimed) |
| **116** | **"Edit during a run" was closed INCOMPLETELY**: a file that the case itself edited was rolled back from the backup taken at case START. | tool (silent loss of work) |
| **117** | **The SKIP diagnostic showed ANOTHER PARSER'S ERROR** (found by a shadow contract on REAL third-party code): Zig `@mod` reported as `invalid syntax`. | tool (misleading diagnostics) |
| **118** | **The proof checker REJECTED A CORRECT Z3 CERTIFICATE** (Ghostty `gridColumns`): the checker did not cover `unit-resolution`/`def-axiom` steps. | tool (incomplete proof-checker coverage) |
| **119** | **A COMPRESSED IMAGE DISABLED THE TRUTH GATE** (found while building the audit corpus): `/raw/<path>` served compressed bytes, so every claim degraded to `e=0`. | kernel / CLI (silent gate shutdown) |
| **120** | **Verdict `N` (UNKNOWN) was PRINTED AS "CONTRACT VIOLATED"** (zlib shadow contract): a three-valued verdict was collapsed into two. | tool (false alarm) |
| **121** | **False rejection by the proof checker: numeric literal ATOM vs LIST** (Rust `saturating_add`): `-2147483648` vs `(- 2147483648)`. | proof checker (false rejection) |
| **122** | **`Int` compared with `Bool` inside a function body** (C shadow contract): a "bare" comparison as the result was translated ill-typed. | extractor (ill-typed formula) |
| **123** | **`unit-resolution` over TRUSTED lemmas: honest SKIP, NOT fixed** (musl `abs`): soundness kept over completeness. | proof checker (conservative refusal, open work) |
| **124** | **Mutator "moving target"**: `sample_stratified` used ONE global PRNG, so any change of the site count in one file reshuffled the sample in all others. Fixed by a per-site `sha256(seed:file:text:mutation)` key; proven: deleting 187 sites in `proof_check.zig` left 27/27 picks in the other 14 files unchanged. | methodology (metric was not reproducible) |
| **205** | **Contract-parser funnel**: refusal on an unknown AST node replaced by symbolic abstraction (AnnAssign, nested `def`, `try/except`, tuple unpacking, `len/int/bool`, `havoc` for other calls). Measured: accepted bodies **7 (1.14%) -> 162 (27.23%)**, ×23. | methodology (measured) |

---

## 6e. Registry of defects from the pre-release session of 2026-10-19 (#153–#230)

> **Historical numbering gaps — 21 numbers:** #11–#30 and #169.
> Those defects were recorded before continuous numbering was introduced (some lived only in `docs/METRICS.md`).
> Numbers are **NOT renumbered** — code, tests and reports reference them — so the journal range reads as "#1–#235 with gaps", not as "231 entries".

Every entry below was found by **measuring**, not by reading: a full run of the
can-fail harness, field runs of `--xray` on real code (Python stdlib, Zig
`std/math`), checking `kernc.wasm` outside the kernel, and auditing our own
evidence collector. Full write-ups with dumps are in `docs/METRICS.md`.

| # | Defect | Class | Status |
|:--:|:--|:--|:--|
| **153** | **WASM: a valid proof was rejected.** The 256 KB static buffer in `wasm_api.zig` could not hold the arena of the 51-step `abs.c` proof, so the allocator failed and `verifyProof` returned `0` on a CORRECT derivation. Raised to 4 MB (BSS, module size unchanged) | correctness | FIXED |
| **154** | **`make mcp-selftest` failed 10 times when `z3` was not in `PATH`** (class #110). The script now enriches `PATH` itself (venv, `~/.local/bin`, `/usr/*`) and **names** the missing binary instead of reporting "10 failures". Verified under `env -i` | tooling | FIXED |
| **155** | **The proof checker ACCEPTED a forgery.** In `verifyThLemmaArith` an unresolved `@xN` reference fell through to `.structural_only`, which is not counted as a trusted step, so `checksPass()` passed: renaming a step definition silently dropped a Farkas premise while the verdict stayed `trusted: 0`. Now `.bad` | soundness | FIXED |
| **156** | **SIGTERM during a run left an injection in the tree**: `finally` does not run on SIGTERM. SIGTERM/SIGINT/SIGHUP handlers (rollback from a snapshot) and a refusal to start on a dirty `src/` were added. Verified with a live `kill -TERM` | process | FIXED |
| **157** | **`write_atomic` did not preserve the file mode**: `os.replace` carried the temp file's 0644 over, so after an interrupted run **29 executable scripts lost `+x`** | tooling | FIXED |
| **158** | **`'%s' % x` was parsed as a modulo operation** -> FALSE `[CRASH PATH]` in `urllib/error.py`, `http/cookiejar.py`. `_is_str_expr()` added to all three divisor collectors | false positive | FIXED |
| **159** | **C-like: `if (...) return; if (...) return;` did not narrow the path** -> FALSE `[DEAD BRANCH]` on `std/math`. Narrowing now happens only on `return`/`else` | false positive | FIXED |
| **160** | **C-like: `[REDUNDANT GUARD]` ("always true") without a type or domain** — an unprovable claim for Zig/C. Only `[DEAD BRANCH]` is emitted for C-like now | claim boundary | FIXED |
| **161** | **Zig std: 57 FALSE `[CRASH PATH]`** — the divisor `q` was a local `f64` (float division by zero is `inf`, not a panic). Locals and float names excluded from divisors -> 0 findings | false positive | FIXED |
| **162** | **`--xray <dir>` on Zig reported `checked 0` on a re-run** (silently). Explicit `cwd` plus an honest unreadable-file counter (now 0) | tooling | FIXED |
| **163** | **`--audit-repo <github-url>` -> `NameError: _shm_dir`**: the call was copied from the mutator but the function was never defined -> `rc=2` | tooling | FIXED |
| **164** | **`import shutil` was missing** -> cleanup in `finally`/`atexit` crashed and **2 `/dev/shm/kern_audit_*` directories stayed in RAM** — exactly the leak the code was meant to prevent | tooling | FIXED |
| **166** | **`builtin_lia`: `pickVar` chose a variable with a ZERO coefficient** -> the Fourier-Motzkin elimination step made no progress -> the counter hit `MAX_VARS` -> **a false `unknown` in `kernc.wasm` where the CLI reports `SAT`**. Found with a diagnostic tag, not by guessing | correctness | FIXED |
| **167** | **`registry`: two targets had no classification** (`bench-simd8`, `clean-cache`) -> registry FAIL at 123/123 CHECK | tooling | FIXED |
| **168** | **An `chc.zig` injection reached a COMMIT**: a killed `canfail` run did not roll the file back and `git add -A` picked it up | process | REVERTED; `injection_guard.py` added |
| **170** | **An `unsat_core.zig` injection survived in a commit**: a live `canfail` (18 min) planted the file AFTER my check -> 10 false `kernfs_router` failures | process | REVERTED |
| **171** | **`make bench-semantic` -> `MerkleRootMismatch`**: `semantic_probe.zig` assembled the image by hand and computed the root the OLD way (pre-#128). Moved to `sealImageRoot` (single source of truth); digest is deterministic | single source | FIXED |
| **172** | **A sabotage line in `tools/kern_contracts.py`** (`if True: # SABOTAGE`) from a killed run; the guard only watched `src/` | process | REVERTED; guard extended to `tools/` |
| **173** | **The evidence guard falsely accused the harness itself**: (a) the baseline included `zig-out` artifacts that `canfail` rebuilds at the end, so every honest run was declared invalid; (b) a snapshot overwrote a write-once basis | tooling | FIXED |
| **174** | **51 names were defined TWICE (2024 lines of dead code) in `tools/kern_contracts.py`**: Python executes the LAST definition, so edits to the first (dead) copy **silently do nothing**. A ratchet (`dup_defs_guard.py`) now blocks growth | tooling | RATCHETED |
| **175** | **A nested evidence collector erased the outer run's basis**: the can-fail case `evidence-fast` runs `make evidence-fast` -> the nested `collect_evidence.sh` took the SAME `GUARD`, and after write-once it deleted the outer basis -> "EXTERNAL CHANGE" on every step | process | FIXED |
| **176** | **A timeout was mistaken for process completion**: the automation waited `for i in $(seq 1 60); sleep 10` = 10 min for a ~20 min collector, and exhausting the loop was read as success, so edits, a commit and a signature happened DURING the run | process | FIXED |
| **177** | **The telemetry parser did not match the new mutator output**: `measure_all_kern.py` waited for `MUTATION SCORE:` while the output became `MUTATION SCORE (raw):` after the dual score was introduced -> `score=None`, the "Mutation" block 0/12, harness 88/100 | tooling | FIXED |
| **178** | **The public registry count and the MCP tool names on the site were stale**: the site listed 5 tools with two names that do not exist (`kern_check_contracts`, `kern_prove_contract`) while the server exports 8, and the defect range was `#1-#123 / 63 entries` instead of `#1-#177 / 105 entries` | documentation | FIXED |

**Honest caveat.** A previous run of 139 targets ended with `RC=0` and `TOTAL: 141 non-vacuous | 0 VACUOUS | 0 case errors`, but the guard itself declared it invalid — for reasons (a)+(b) of #173, i.e. **because of a guard defect, not the run** (tree: clean, no injection markers).

---


## 6g. Closed journal gaps (#93–#97, #165) and entry #226

The same entries existed only in `docs/METRICS.md` (§63–§65, §113.1) and were
missing from the journal: the range #98–#164 was present, while #93–#97 and
#165 fell out.

| # | What was broken | Class |
|:--:|:--|:--|
| **93** | A **stale binary** was tested: the target depended only on `build`, the fixture was built from old code → false failure | gate |
| **94** | The release version was **hard-coded**: `default="v2.2.0"` while the README announced v2.3.0 | gate |
| **95** | `unit-resolution` **rejected a correct proof**: `withdraw_fixed` (two `if` → `ite`) produced `[SKIP]` — Z3 proved it, the checker refused | core |
| **96** | `ofExit`: **any non-zero code** produced `n = true` → `exit 2` (SKIP, the check never ran) looked like a failure | core |
| **97** | The **banner** version was duplicated separately from `--version` and drifted | gate |
| **165** | `i64` in the browser needs `BigInt` — the **WASM widget did not work** in a browser | showcase |
| **226** | **THE JOURNAL WAS INCOMPLETE**: the showcase claimed the range "#1–#225" while only **181** entries existed; #31–#47, #93–#97, #165 lived only in METRICS, and **#11–#30 and #169 are absent from the whole repository**. Fix: entries moved in (sections 6a and 6g), showcase numbers rewritten to the measured facts ("205 entries, numbers up to #226", gaps listed explicitly) | documentation |
| **227** | **THE COMMITTED MUTATION EVIDENCE WAS STALE**: `docs/evidence/mutate.log` was dated 2026-10-19 and captured on a DIFFERENT tree (pool of 1225 sites, without `dst_sim.zig`), and the claimed full 1225/1225 sweep was never stored in the repository. Re-run on the current tree: `docs/evidence/mutate_full.log` — **1345/1345, 0 survivors** (1408 lines), `mutate.log` — 40/40. The 'log not committed' caveat was removed | FIXED |
| **228** | **25 STALE NUMBERS ON THE SHOWCASE** after the mutation pool grew 1225→**1345** and 20→**21** files: README, README.ru, index.html, PASSPORT(+en), RELEASE_NOTES, ROADMAP.en. Plus a **guard false positive**: the 'N files' rule fired on 'Lean 4 8 files / 137 theorems' because the line contains the word *mutation*. Lean files excluded; the rule now checks both the pool and the file count | FIXED |
| **229** | **THE NUMBER GUARD COVERED 8 OF ~20 FILES, AND THE LEAN RULE FOR THE SITE NEVER FIRED**: the pattern `(\d+)\s+Lean` never matched (on the site the number precedes the word 'theorems' while 'Lean 4' comes earlier), so **82 and 120 theorems survived several commits**. Extended to 20 files; `(?<!Lean )` rejects the version; added `tools/check_lean_counter.py` | FIXED |
| **230** | **THREE GUARD FALSE POSITIVES AND ONE FICTITIOUS CHECK** (found by injection, not by review): (1) `&nbsp;` in 'Lean&nbsp;4 theorems' produced a bogus '4 theorems' — the version was read as a counter; (2) in `RELEASE_NOTES` the rule caught the HISTORICAL baseline '82/82 CHECK' from the v2.4.0 column — only the last cell is checked now; (3) the catalogue rule looked for 'N declarations' and **never saw** 'test declarations: **N**' — a '424' injection passed with a clean rc=0. All three fixed and verified by injection (rc=1) | FIXED |

| **231** | **A TAUTOLOGY WAS PRESENTED AS A KERN ACHIEVEMENT**: the benchmark table on the showcase carried the row 'QuixBugs **31/31** bugs detected by execution; 24/31 correct ones confirmed' (README.md, README.ru.md — two sections). It measures the **dataset wiring**, not KERN: 'a buggy program fails its own official tests' is the DEFINITION of the QuixBugs dataset, not a detection result, so 31/31 could never be lower. The row was removed from both tables and from the `tools/` listing; a footnote explains why and points at KERN's own result — `6/40 DIVERGED`, every hit confirmed by replaying the real function (`audits/QUIXBUGS_BASELINE.md`). The log `docs/evidence/quixbugs_full.log` is kept as evidence of the dataset wiring | showcase |
| **232** | **THE `scorecard-check` GATE EXISTED BUT CI NEVER RAN IT**: `make scorecard-check` compares the published `docs/evidence/scorecard.json` against a recomputation (137 theorems, 127 CHECK, 8/8 MCP, `sorry=0`), and the canfail case `scorecard-check` proved the gate **can** fail (tampered passport → `rc=1`). But `tools/ci.sh` had no stage: what was verified was 'the gate is sensitive', not 'the passport on the site is fresh'. A stale passport (125 theorems, 125 CHECK) therefore lived on the showcase while CI stayed green. Added the stage `Trust Scorecard passport == facts (#232)`. Lesson: canfail proves a gate's sensitivity, **not** an artifact's freshness — two different checks | FIXED |
| **233** | **PARAMETER TYPES WERE NOT READ → EVIDENCE ON INPUTS OUTSIDE THE DOCUMENTED DOMAIN**: the domain was derived from the AST only (how the value is USED in the body), so for `is_valid_parenthesization` the enumeration included `["("]` (a list) instead of the string `"("`, and the "bug" was confirmed on an input its own docstring forbids. Added `declared_kind()`: the type is read from the `Input:` section, and a documented `Precondition:` filters combinations outside the domain (lesson #200) |
| **234** | **A `NameError` WAS SWALLOWED BY THE PRECONDITION FILTER**: in `tools/trace_explorer.py` a generator expression inside `all(...)` resolves names in `globals`, while the values were passed in `locals` → `NameError` → the filter silently kept ALL combinations, so the docstring precondition never applied. Found by comparing "how many inputs were dropped" (0 with a non-empty `Precondition:`). The same file was missing `import re` — caught by `py_compile` |
| **235** | **FALSE DIVERGENCE REPORT ON GENERATORS**: `flatten` and `kheapsort` were printed as `buggy=[] correct=[]`, i.e. as a found difference, although the values matched: the generator was consumed by the first `_norm` and the message used a second call. Object addresses in memory also produced a phantom difference. Normalisation is now recursive (generators are materialised once) and comparison no longer depends on addresses |

| **243** | **`--diff-equiv` ACCUSED AN IDENTICAL FILE OF DIVERGENCE**: the command treated EVERYTHING except the string “PROVED” as a divergence, while `kernc prove` returns `rc=2` both for “proved but the proof checker rejected it” (`premises_unbound`) and for “refuted with a counterexample”. Hence `--diff-equiv file file` printed `[DIVERGED]` and `make diff-equiv` passed VACUOUSLY: the bad pair was caught for the same reason any pair would be. Classification moved to the solver output (`classify_prove`: equivalent / unverified / diverged / unknown / tool_error) plus a POSITIVE control “an identical file is not accused”. Now: diverging pair → `DIVERGED` + counterexample (`rc=1`), identical → `EQUIVALENT?` (`rc=2`, no accusation) | FIXED |
| **244** | **THE SHOWCASE PROMISED WHAT DID NOT EXIST AND CARRIED UNMEASURABLE NUMBERS**: the landing page had no proof-flow map, no Ego-Lens and no `[+][~][-][=]` filter matrix (checked with `git log -S`), while the `kern-architecture.svg` banner carried “200 T / 422 F,N / 409 B” — a number that exists in NO source and cannot be recomputed. The Belnap arrows were drawn from `B` downwards, i.e. against the direction of accumulation. Done: the numbers are replaced by the law `join_K(T,F)=B`, arrows reversed (`N→F`, `N→T`, `F→B`, `T→B`), added the map `docs/kern-proof-flow.svg` (edges `import` / `asserted` / `proof-step` + CEGIS return), an Ego-Lens of radius 1–2 and filters over the REAL `@import` graph of `src/`. The graph is regenerated (`make showcase`) and `make showcase-check` with `--selftest` (3 tamperings) keeps it from drifting; equivalence is marked “CLI only” instead of being simulated in the browser | FIXED |

| **245** | **AN ANCHOR COMMENT HID A NUMBER FROM THE GUARD**: after anchors were introduced the line became `#1–#<anchor>244`, and the registry-range rule (`#1[–-]#(\d{2,3})`) stopped matching — the check became VACUOUS, i.e. it switched itself off exactly where it had to work. Numbers are stripped of comments (`<!-- ... -->`) before parsing, and the rule fires again | FIXED |
| **246** | **FOUR FILES WITH ANCHORS THAT `sync` NEVER UPDATED**: `docs/PROJECT_SPECIFICATION.md`, `docs/README.md`, `docs/RELEASE_NOTES_v2.5.1.md` and its EN mirror carried `<!-- fact:registry_targets -->` but were absent from `SURFACES`. The number LOOKED synchronised and went stale silently (154 against the fact 162). The files were added; `sync_state.py --check` now detects orphans, and `--selftest` creates a temporary anchored file and demands that the guard catch it | FIXED |
| **247** | **A SYNTAX EXAMPLE WAS TAKEN FOR AN ANCHOR**: the release notes document the format `` `<!-- fact:key -->N` ``, and the check declared the file broken (“anchor without a number”). Inline code spans and fenced blocks are now stripped before parsing: an example in backticks is not a statement about a fact | FIXED |

| **248** | **THE RELEASE DRAFTER DRAFT OCCUPIED THE TAG NAME AND SWALLOWED THE RELEASE**: `tag-template: 'v$NEXT_PATCH_VERSION'` created a draft named `v2.5.1` — exactly the tag managed by the `Release` workflow. `gh release view` found that draft, uploaded assets into it and never published it: the tag stayed without a release and `releases/download/v2.5.1/...` returned 404 while a “release” page existed. The draft is now named `next`, and the pipeline runs `--draft → upload → --draft=false`, so “published” always means “assets are present” | FIXED |
| **249** | **A MISSING PyYAML WAS REPORTED AS MANIFEST DRIFT, AND THE ACTION'S DOWNLOAD TAG WAS UNCHECKED**: `ecosystem-check` imported `yaml` inside a heredoc; without the library it printed “No module named yaml” and declared the manifests out of sync — the tool was missing, but the file looked guilty. On top of that `action.yml` carried `default: 'v2.5.1'` (the tag the Action downloads), which `version_check` never looked at: after a version bump the Action would silently fetch a different release. Parsing moved to `tools/check_action_yml.py` (PyYAML when available, the same four assertions from text when not), and `action.yml` is now covered by `version_check.sh`; planting a stale tag yields `rc=1` | FIXED |
| **250** | **THE SHOWCASE CLAIMED “README == build == asset” WHILE ALL THREE HASHES DIFFER**: the README named sha256 `804bb8d7…` and size 6733336 B, and the site repeated it with the label “hermetic release binary, sha256 verified (README == build == asset)”. In reality: README `804bb8d7…`, local hermetic build `c765511d…`, release asset `f7ffe473…` (6733328 B) — three DIFFERENT objects. The hash and size are gone from the README (verification goes through the release `SHA256SUMS`), and the site now separates the claims honestly: `SHA256SUMS` binds the artefact, the Ed25519 attestation binds the SOURCE (commit + `tree_sha256`), and a CI build need not be byte-identical to a local one. The passport (EN/RU) says the same. The site's `393/8/0` QEMU numbers were replaced by anchored `394 / 8 / 0` | FIXED |
| **251** | **THE ATTESTATION COULD NOT BE VERIFIED OUTSIDE THE OWNER’S MACHINE**: the public key was read only from `$HOME/kern_owner_public.pem` (`tools/slsa_provenance.py:65`); no key and no instructions lived in the repository, and with `kern.intoto.sig` missing `--check` printed “ATTESTATION VALID”, i.e. confirmed validity by the ABSENCE of evidence. Now the key is published at `docs/keys/kern-owner.pub`, `kid` (SHA-256 of the DER key) is embedded in the attestation, and `make verify-attestation` checks signature / `kid` / `attests_commit` / `dirtyTree` / artefact sha256 using ONLY the repository key; a missing signature is a failure, and the `attest-sig-missing` can-fail case proves the check can go red. | FIXED |
| **252** | **SECRETS WERE NOT SCANNED**: provider keys twice ended up in the chat transcript, while the repository had neither `gitleaks` nor an in-tree scanner nor a can-fail case — a leak into a tracked file would have passed silently. Now `tools/secrets_check.py` scans EVERY tracked file (provider keys + PEM private keys), prints matches REDACTED, has a self-test (7 injections / 4 clean) and the `secret-in-tree` can-fail case; a CI stage was added. | FIXED |
| **253** | **THE SOLVER WAS NOT PINNED**: `requirements.txt` allowed `z3-solver>=5.1.0.0`, and CI ran `pip install z3-solver` without using requirements at all — verdicts could be produced by different Z3 versions, and a before/after comparison silently compared different solvers. The version was not recorded in reports either. Now `z3-solver==5.1.0.0`, CI installs via `-r requirements.txt`, and `--json` carries a `solver` block (version, path, timeout, call count). | FIXED |
| **254** | **VERDICT DETERMINISM WAS NOT CHECKED**: the verdict depends on the wall-clock timeout and the solver version, so on a slow host “T” could silently become “N”, and `--check` would compare that as a code regression. Now `tools/determinism_check.py` (`make determinism-check`): one input, two runs → identical verdict, counterexample and `trusted/holes`; the `nondeterministic` can-fail case flips an expectation. | FIXED |
| **255** | **CHANGELOG LAGGED BEHIND THE VERSION**: `src/main.zig` said `v2.5.2` while the last CHANGELOG section was `2.5.1` — a release was published with no description. Now `tools/changelog_check.py` requires a `## [x.y.z]` section for the code version; CI stage and the `changelog-drift` can-fail case. | FIXED |
| **256** | **LEAN/MATHLIB WERE NOT PINNED**: no `lean-toolchain` file existed and the Mathlib revision was recorded nowhere, so 137 theorems with “0 sorry” were reproduced by luck — another revision can change tactics. Now `lean-toolchain` (v4.34.0) + `formal/mathlib.lock` (Mathlib revision and 9 package versions) + `tools/lean_pin_check.py` (compares the installed Lean and the Mathlib project with the lock; WARN when Mathlib is absent) + the `lean-pin-drift` can-fail case. | FIXED |
| **257** | **CROSS-PLATFORM BUILD WAS NEVER CHECKED**: the C ABI used `unsigned long` (32 bits on LLP64 Windows instead of 64), no workflow built the project for another platform, and `kernc`/`kernx` rely on POSIX APIs. The check showed: Windows does not build (3 blockers: `src/compat.zig:143`, `src/verifier/z3_bridge.zig:227`, `src/core/kimg_writer.zig:219`, plus `-lsqlite3` for `kernx`), and macOS yields only the library (`libkern.dylib`) because the kernel pulls sqlite3. Now: `size_t`/`int64_t` in the header, `docs/PLATFORMS.md` with an honest matrix and exact blockers, and the `cross-compile` CI job (libkern for aarch64-macos). | FIXED |
| **258** | **NO TRUST DOCUMENTS EXISTED**: there was no threat model, no key management (generation/backup/rotation/revocation) and no incident procedure, while the whole attestation rests on a single key in `$HOME`. Now `docs/THREAT_MODEL.md` (assets, adversaries, TCB boundaries, “what KERN does NOT protect”), `docs/KEY_MANAGEMENT.md` (fingerprint, backup, rotation, revoked `kid` list) and `docs/INCIDENT_RESPONSE.md` (incident classes, first 24 hours, post-mortem); the `make trust-docs-check` gate verifies the required sections AND that the fingerprint in the document matches `docs/keys/kern-owner.pub`; the `trust-docs-missing` can-fail case. | FIXED |
| **259** | **NO PERFORMANCE THRESHOLD EXISTED**: `make bench` printed numbers, but no gate ever compared them — a hot-path regression (cache, extra checks) would pass unnoticed with green tests. Now `tools/perf_check.py`: median of 15 `kernc prove` runs against a baseline (`docs/evidence/bench_baseline.json`), a 1.5× ratio AND an absolute 5 ms slack (so noise on fast runs cannot raise false alarms); the `perf-regression` can-fail case. The gate is local: the baseline is machine-specific, so it is not wired into CI. | FIXED |
| **260** | **THE BIBLIOGRAPHY LIVED IN PROSE**: sources were cited in text with no identifiers, and the “checked” list contained a non-existent JANCL issue, a wrong author (Aoyama instead of Niki), a wrong year (Rivieccio 2024 instead of 2011) and a DOI with a different last digit. Now `docs/references.bib` (25 entries), `docs/references.lock.json` (field snapshot), `docs/BELNAP_SOURCES.md` + `.en.md` (theory → code mapping via `src/path:line` and `formal/*.lean:theorem`, §6 “what is missing”, §7 discrepancies) and `tools/citations_check.py`: keys resolve, `unverified` is forbidden outside §7, code/theorem references exist, RU/EN key sets match, 5 sabotages must go red; the `citations-unknown-key` can-fail case. | FIXED |
| **261** | **INCOMPLETE B4 ALGEBRA: NO CONFLATION**: `∧,∨,⊗,⊕,¬` existed but `~` did not, while the docs called the signature “complete”. Now `conflate()` in `src/core/eq2.zig:89` (`~N=B, ~B=N, ~T=T, ~F=F`, involution, commutes with `¬`) plus Lean lemmas `conflate_involutive`, `notB_conflate_comm` and tests over all four values. | FIXED |
| **262** | **VERDICTS WERE CONFLATED**: `Bit {p,n}` and `ast.Status` did not distinguish timeout, fuel exhaustion, an invalid certificate and a tool error — all looked like “not proved”, and the request kind was not bound to the certificate at all. Now `src/next/state_axes.zig` (seven axes, one mapping table, `timeout≠F`, `out_of_fuel≠B`, `invalid_certificate≠F`, `B` never produced by a verdict) + `QueryKind` in `ProofCertificate`/`VerificationPolicy` with `QueryKindMismatch`; `make axes-check` (28 tests) and the `axes-law-break` can-fail case. | FIXED |
| **263** | **THE CONTRACT LOCK WAS VACUOUS**: `docs/contracts.lock.json` held ONE demo file, so the “weakened `ensures`” can-fail case proved sensitivity on the very file in the lock; worse, `contract_fingerprints` called `ast.parse` on `.zig` files and crashed on the first non-Python file. Now `--lock-repo` covers the whole repository (37 files, 47 contracts), `--verify-lock-repo` also checks coverage (a new `@kern:` file without rebuilding the lock → rc=2), and non-Python fingerprints bind to the nearest `fn NAME`. | FIXED |
| **264** | **EVIDENCE COULD NOT BE RETRACTED**: the AST held only a list of `evidence_ids`, and the state was a monotone `⊔` — a wrong piece of evidence left `B`/`F` forever. A lattice has no inverse, so retraction is implemented as a RECOMPUTE of the active set. Now `src/next/evidence_ledger.zig`: `add` (idempotent) / `retract` (full recompute) / `epoch` (atomic publication, grows only on a real change); contribution order does not matter; the `ledger-retract-break` can-fail case. | FIXED |
| **265** | **NO PROVENANCE GRAPHS AND NO SCC CHECK**: `G_src`/`G_build`/`G_prov` did not exist and negative recursive cycles (`f -> g -> not f`) were not rejected — such a graph describes a contradictory definition yet passed silently. Now `src/next/provenance.zig`: three projections, Kosaraju (iterative, no recursion) and `check()` → `NegativeRecursiveCycle`; 7 tests including the `f = not f` self-loop and a negation between different SCCs (not a cycle). | FIXED |
| **266** | **THE GRAPH WAS BUILT ONLY ON THE SHOWCASE**: `docs/showcase-graph.json` came from a Python scanner while the kernel knew nothing about the graph — two scanners of the same thing are guaranteed to diverge (the first run gave 84 nodes/67 edges against 78/65 in the stale artefact). Now `kernx graph [--root DIR]` (`src/next/graph_dump.zig`) builds `G_src` in the kernel, and `tools/graph_parity.py` requires the node set, edge set and metrics (`loc`, `imports_out`) to match the showcase exactly; the `graph-parity-break` can-fail case. Found on the way: the walker `entry.path` buffer is reused (hash_map panic), and the node id must be a path, not a basename. | FIXED |
| **267** | **THE LEDGER AND `resolve()` LIVED APART**: state was a monotone join in `truth.zig` while the recompute lived in the new ledger; nothing checked they agree. Now `truth.bitFromLedger()` plus a test “ledger and join give the same state” (T⊔F=B; after `retract` — T), so a divergence is caught immediately. | FIXED |
| **268** | **NO KIMG UNKNOWN-FLAG POLICY**: `flags` were read and ignored, so an image requiring an unknown extension was parsed by the old rules SILENTLY, and a big-endian file was indistinguishable from “another version”. Now `OPTIONAL` (low 16 bits — skip) and `REQUIRED` (high 16 — `UnsupportedRequiredFeature`) masks, plus `WrongEndianness` when the same version bytes read as BE yield 1; 3 tests. | FIXED |
| **269** | **A 3-FIELD CACHE KEY**: `keyOf(ast, contract, proof)` ignored the checker version, the policy, the schema and the whole agent contour — changing the model or prompt would return a verdict computed for a DIFFERENT request. Now `CacheKey` has 13 fields plus a `v2` schema prefix; a test walks all 13 fields and requires each one to change the key. | FIXED |
| **270** | **KERN-X: FUEL BY VALUE AND NO QUOTAS**: `fuel: u32` would be copied with branching (exponential budget), `CALL`/`RET` did not exist, and there were no quotas for memory/output/depth/host calls. Now `Budget` holds pointers (one counter for all branches), `CALL`/`RET` opcodes and `OutOfQuota` for four resources; 9 tests including “two machines share one budget” and “recursion spends ONE fuel”. | FIXED |
| **271** | **KERNFS KEPT A SLICE OF A FOREIGN BUFFER**: `mountFromBytes` was zero-copy, so mutating the source AFTER the Merkle check changed the answers (for mmap — a foreign write to the file). Now `mountFromBytesOwned` (a copy, `no-mmap` mode) + `OwnedMount` + a test: corrupt the whole source buffer — the answers do not change. | FIXED |

## 7. Summary

**MEASURED/TESTED:** the KIMG core (parser, builder, Merkle, KERNFS, the Gate, KERN-X,
cache, 5 SMT theories, C-ABI) and KERN-Next (parser, validator, SQLite, snapshot, diff,
packet, report, cache) — **402 + 53 tests, all green** (with `z3` in `PATH`; without it —
393 passed + 8 skipped, the solver-dependent ones).

**FRAMEWORK/NOT IMPL:** cloud, the Lean transpiler, plugins, bundle, PQC, dashboard —
that is the next layer, and it is NOT claimed to be working.


## 6f. Field audit of 14 repositories (2026-10-19, #179–#184)

Compact English list; full text and measured before/after tables are in
`docs/FIELD_AUDIT_REPORT.md` and `docs/METRICS.md` §116.

| # | Defect | Class |
|:--|:--|:--|
| **174 (closure)** | *Completion record — the defect itself is #174 above.* 52 top-level names defined twice in `tools/kern_contracts.py` (2024 dead lines). **Closed**: shadowed copies removed bottom-up by AST (**52 -> 0**, -2003 lines); root cause found — two `if __name__ == "__main__"` blocks and an *early* `cmd_xray` copy newer than the live one (C-like routing did nothing). | tooling |
| **179** | Python `--xray`: `assert` was not a path guard (false `[BOUNDS PATH]` in `psf/requests`); a variable reassigned inside a loop kept its pre-loop value (false `[DEAD BRANCH]` in `tiangolo/fastapi`) | measurement |
| **180** | Rust extractor saw 0 of 1292 functions in `ripgrep` (`pub(crate) fn`, `async`, generics, `if cond {`) | measurement |
| **181** | Scorecard under-scored real projects (`LICENSE*`/`COPYING*`, `test/`/`__tests__/`/`*_test.go`, Lean outside `formal/`) | measurement |
| **182** | `assert(...)` with nested parentheses was not a guard (`zls`: false `[CRASH PATH]`) | measurement |
| **183** | C-like X-Ray lacked machine type ranges, let-inlining and `@kern:requires` as part of the domain; a divisor must depend on parameters | measurement |
| **184** | **Soundness**: `_smt_sat` treated `N` (solver did not decide / SMT parse error) as SAT; free names were not declared | **soundness** |
| **185** | Vacuum case from a dead duplicate assignment (`CANVAS_TMPL` declared twice; `canfail` patched the dead copy) | self-check | fixed |
| **186** | 13 dead duplicate module-level assignments in `tools/kern_contracts.py` | dup-guard | fixed |
| **187** | **False `[BOUNDS PATH]` from unmodelled loop guards**: the retro-test on `2cb4a20` produced 3 accusations in `autolink_delim`, where the bound comes from `while (link_end > 0)`. Split into two classes: pointer-backwards offset (`data[-k - i]`) vs `value - 1` (the latter is not claimed when a `while`/`for` controls the variable) | field run | fixed |
| **188** | **`--xray` missed most real C functions**: `RE_FN_C` required a single-word return type without `*` and a `{` on the same line, so `static cmark_node *make_block(…)` and `char *dup(int len)` were not recognised; and `int *buf` produced the parameter name `*buf`, undeclared in SMT-LIB (every check of that function silently became "unknown") | CVE retro-test | fixed |
| **189** | C casts made guards untranslatable (`(size_t)(…)`, `(ptrdiff_t)(…)`), so the path was not narrowed and a false warning survived on the fixed `cmark-gfm` file | CVE retro-test | fixed |
| **190** | Upper bound / off-by-one was not checked (`i <= len` allows `i == len`) | CVE retro-test | fixed |
| **191** | “Backward offset is negative” was trivially true for any `data[-k]` (pure noise); now claimed only when the offset contains a loop counter | CVE retro-test | fixed |
| **192** | Missed B `4682993`: cast on ONE term, rest unsigned → pointer wrap | CVE retro | fixed |
| **193** | Missed C `ac80f7b`: struct field type (`uint16_t n_columns`) not read | CVE retro | fixed |
| **194** | Missed D `198669d`: `<=` vs capacity name unchecked; multi-line signature | CVE retro | fixed |
| **195** | False `[DEAD BRANCH]` in express: reassigned local treated as constant | .js field run | fixed |
| **196** | False `[CRASH PATH]` in axios: `x = x || K` not modelled | .js field run | fixed |
| **197** | False `[DEAD BRANCH]` in gin: `err != nil` pointer compare in Int model | .go field run | fixed |
| **198** | `--full-scan` silently gave 0 for Python (non-existent `_xray_file`) | self-check | fixed |
| **199** | Vulnerability certificates were **dead files**: `audits/*/*.smt2` was checked by no gate at all (grep over `tools/` was empty) — a solver regression would have silently diverged from the published table | field review | **fixed**: `audits_run.py::cert_section()` checks the expectation from the file name and fails `make audits` (**12 certificates, 0 mismatches**) |
| **200** | **False accusation in third-party code**: `--xray` reported a `[CRASH PATH]` in `zigtools/zls` (`initFromTrigram: % len`) although `len == 0` is unreachable — the filter is built only under `if (trigrams.len > 0)`. Inter-procedural invariants are not modelled | re-check on ZLS 0.17.0 | **fixed**: a length-like divisor (`len/size/count/n/cap/capacity/length`) is no longer accused (the caller guarantees non-zero); after the fix `TrigramStore.zig` -> findings 0 |
| **201** | **C-like findings are candidates, not bugs**: on today's `libgit2` HEAD (`src/util`) 14 findings, and hand-verification showed all 14 false (no control-flow modelling: early `return`, `break` inside `while(1)`, loop-carried state, caller invariants) | field check on fresh code | **fixed**: the tool prints the boundary "CANDIDATES, verify by hand"; no external reports are sent from them (0 confirmed of 14) |
| **202** | **False accusation when the postcondition is empty**: `@kern:requires` without `@kern:ensures` produced `[FAIL] CONTRACT VIOLATED` with a meaningless counterexample (`num = 1`) — `build_smt` without `ens` adds no `(assert (not ens))`, the formula is trivially SAT, and the verdict fell into the `else → FAIL` branch | contract audit of real `jinja2.tests.test_divisibleby` and `werkzeug.http.is_byte_range_valid` (595 functions, 6 libraries) | **fixed**: `[SKIP] no @kern:ensures — nothing to prove`; safety obligations (division/overflow) are checked ABOVE and are unaffected |
| **203** | **Chained comparison rejected**: the Python idiom `0 <= start < length` produced `SKIP — chained comparison` | `werkzeug.http.is_byte_range_valid` | **fixed**: `a<b<c` becomes `(and (a<b) (b<c))`; counterexample `length=1, start=0, stop=2` is runtime-confirmed — and **refuted** by caller analysis (`min(end, length)`), so the library has no defect here |
| **204** | **Contract-audit funnel MEASURED**: of 595 functions in 6 top libraries, only **7 (1.14 %)** were accepted as analysable bodies; after the `raise`-guard and opaque-`Expr` adapters — **8 (1.31 %)**. The dominant blocker is **calls** (`len()`, `self.f()`): 117 functions, then `try` (39), nested `def` (30), `AnnAssign` (28) | before/after measurement on the same population via `parse_file` | **measured, not "fixed"**: calls cannot be modelled without real function semantics — an honest frontend boundary, recorded as a limitation |
| **206** | **`--diff-equiv` reported divergence from a havoc abstraction**: when a body contains `_havoc_k` (a call replaced by an unconstrained variable), two different havocs in the old and new body are always "distinct" — `(distinct _havoc_2 _havoc_5)` is trivially SAT — so the tool printed `[DIVERGED]` (a false accusation). On QuixBugs this produced 5 false "caught bugs" out of 40 | running the `jkoppel/QuixBugs` benchmark (40 buggy/correct pairs) | **fixed**: havoc in either body -> `[UNKNOWN] ... not provable` and `rc=2` (in `--diff-equiv` and `--pr-summary`); `--simplify` stays fail-closed. QuixBugs after the fix: **35 SKIP / 5 UNKNOWN / 0 DIVERGED** |
| **207** | **False proof via loop unrolling**: a body produced by K=2-step bound-unrolling (`while`/`for`) was counted as `[PASS] PROVEN`. UNSAT over K steps does NOT mean the loop terminated — it may continue on step K+1 (CBMC/Kani require an *unwinding assertion*). On the demo it produced `11 -> 12` proven | `make contracts` after enabling unroll | **fixed**: `unrolled` flag from `body_smt` -> `PASS` is FORBIDDEN, printed as `[SKIP] [UNBOUNDED] K-step unrolling does not exhaust the loop`; same in `--diff-equiv`/`--pr-summary` (UNSAT under unrolling -> `[UNKNOWN]`), `--simplify` stays fail-closed. Pinned by an edge case: loop -> UNBOUNDED (no false PASS) |
| **208** | **Счётчик охвата `--xray` был вакуумным**: функция без единого SMT-обязательства засчитывалась как «проверенная» (`checked += 1` безусловно). Разделено: `SMT-verified` (решатель вызван) и `no obligations`. | ИСПРАВЛЕНО |
| **209** | **Списочные баги `QuixBugs` отбрасывались в Live Replay**: домен аргументов состоял только из `int`, поэтому `mergesort(0)` падал `TypeError` в ОБЕИХ версиях и расхождение «не находилось». Добавлен списочный домен + фолбэк по `TypeError` (DIVERGED 1 → 3). | ИСПРАВЛЕНО |
| **210** | **`not-or-elim` в чекере не проверялся**: 2 из 6 доверенных шагов на `value % 2` были булевым правилом де Моргана, а не арифметикой. Добавлен `verifyNotOrElim` (trusted 6 → 4). | ИСПРАВЛЕНО |
| **211** | **`(ite C 1 0)` не распознавался в `rewrite`**: добавлены `eqAntisymEq` и `eqZeroIteEq` (trusted 4 → 2). | ИСПРАВЛЕНО |
| **212** | **Перенос слагаемого через сравнение не проверялся**: `(<= A T)` vs `(<= (+ A (* -1 T)) 0)` при непрозрачном `T` (с `ite`) требовал нормализации `parseLin`. Добавлено СТРУКТУРНОЕ правило `cmpSubZeroEq` (без `parseLin`): `value % 2` даёт trusted 2 → 0. | ИСПРАВЛЕНО |
| **213** | **Флаг `--trust-score` был только в документации**: упоминался, но отсутствовал в CLI (проверка `ts` падала бы). Добавлен обработчик, делегирующий в `tools/trust_scorecard.py`. | ИСПРАВЛЕНО |
| **214** | **Списки были вне подмножества**: `arr[i]`, `arr[i] = v`, `arr[i] += v`, `for x in arr`, `if n:`/`while n:` (число в позиции `Bool`) отправляли 10+ задач `QuixBugs` в SKIP ДО решателя. Введено окно `arr__e0..2 : Int` + `len__arr` в чистом `QF_LIA` (без теории массивов), развёртка `for` по списку, приведение истинности. DIVERGED 3 → 5 (`hanoi`, `sieve`), `make contracts` без изменений (11/4/0/0/2/2/19). | ИСПРАВЛЕНО |
| **215** | **Тихое проглатывание программных ошибок**: 29 голых `except Exception:` в `tools/kern_contracts.py` (класс #198) скрывали `NameError`/`AttributeError`. Каждый обёрнут в `_replay_soft` (печатает программные ошибки, глушит только ожидаемые), добавлен ratchet `bare_except_baseline.json` в `dup_defs_guard.py`. | ИСПРАВЛЕНО |
| **216** | **The list was not reconstructed from the Z3 model in Live Replay**: the model carries `arr__e0..2` and `len__arr`, not `arr`, so `max_sublist_sum` was discarded (no fallback list starting with a negative element). The list is now rebuilt from the model; QuixBugs DIVERGED 5 -> 6. | FIXED |
| **217** | **The list window could produce a false proof**: with a non-literal index, or a literal beyond the window, `arr[3]` and `arr[5]` yield the SAME value, so `--diff-equiv` could claim an equivalence that does not exist. Such translations are marked as under-approximating -> `[UNBOUNDED] SKIP`. | FIXED |
| **218** | **DOCUMENTATION INTEGRITY (found by the line-by-line audit of 2026-10-20)**: the EN registry was missing **65 numbers** (#52, #55, #56, #59–#92, #98–#124, #205) while RU had 155 rows; `docs/METRICS.md` had three blocks sharing ONE number (**§100, §101, §102** twice each); EN had two `## 6e` headers; the #174 row was duplicated; `docs/README.md` ranges were stale (`#1–#216`, `§1–§136`). Fixed: a 65-entry EN index, renumbering §100→§137, §101→§138, §102→§139, `6e`→`6f`, #174→closure, ranges updated. | FIXED |
| **219** | **The `kern_next_tests.log` evidence had NO COUNT of executed tests**: on a cached step `zig build test-next --summary all` prints only «4/4 steps succeeded … run test cached», without «All 53 tests passed», so the gate could not see 53/53 while the showcase cited that log. Fixed: the run uses a separate `--cache-dir` (2 s), the step really executes and the log records «53/53 tests passed». | FIXED |
| **220** | **Stale test counts on the showcase**: `README.md` promised `308 core tests`, `README.ru.md` — «308 tests» and «catalog 424», `docs/README.md` — «catalog 424» and «308 tests», while the fact is **401 executed core tests and 425 in the catalog**. Fixed; historical mentions (283 tests of the migration branch, the VERIFICATION_0_17 snapshot) are now explicitly marked. | FIXED |
| **221** | **RECURRENCE of class #178: the registry range on the showcase drifted again** — `README.md`, `README.ru.md` and the site promised `#1–#184`, the EN registry intros said `#1–#217`, while the real maximum is **#220**. Fixed to `#1–#235`; recorded as a recurrence so it is visible that a one-off fix (#178) did not hold the metric. | FIXED |
| **222** | **THE LICENSE ON THE SHOWCASE CONTRADICTED THE `LICENSE` FILE** (exactly the class the external audit warned about): in the repository tree `README.ru.md` labelled `LICENSE` as **MIT**, while `LICENSE` is **PolyForm Noncommercial 1.0.0** (as do `server.json`, `.well-known/mcp.json`, `CITATION.cff`). Plus a stale «Makefile 62 targets» against the real **150**. Fixed; a guard `tools/check_license_consistency.py` was added (check 8 of `ecosystem-check`). | FIXED |
| **223** | **THE LEAN 4 THEOREM COUNTER ON THE SITE WAS STALE**: `docs/index.html` showed «120 Lean 4 theorems» in FOUR places while the fact is **137** (the growth 120→137 was never reflected). Fixed + guard `tools/check_lean_counter.py` (check 9 of `ecosystem-check`). | FIXED |
| **224** | **SHOWCASE COUNTERS CONTRADICTED THE FACTS (and no guard existed)**: after closing #220/#223 the texts still carried `114 proven non-vacuous` / `95 fault-injection cases` (README.md), "103 targets · CHECK 80" and `82/82` (README.ru), `195/195` without a snapshot marker (RU passport), `279` (PROJECT.md, PROJECT_SPECIFICATION.md, CAPABILITY_STATUS.en). Found by comparing every public surface against `core_tests.log`, `kern_next_tests.log`, the catalogue recount and `registry.py --json`. FIXED: numbers set to facts (401 / 53 / 425 / 127 CHECK / 143 cases) plus a new guard `tools/check_metrics_consistency.py` (target `make metrics-guard`, case `metrics-guard`): a promise is checked against MEASURABLE evidence, not against prose |
| **225** | **HARNESS ROLLBACK DID NOT COVER FILES OUTSIDE `FAULTABLE`**: `patch()` refused such a file, while `touch()` silently accepted it. The `metrics-guard` case edited `docs/PROJECT.md` via `touch()` + `write_atomic()`; rollback did not fire, the injection stayed in the tree, and `verify_restored` (which only looks at `FAULTABLE`) reported "tree clean". Second offender: `kern.intoto.sig` (case `slsa-bad-sig`). Same class as #48 (injection in a commit). FIXED: both files added to `FAULTABLE`; `touch()` now has the same guard as `patch()` |


