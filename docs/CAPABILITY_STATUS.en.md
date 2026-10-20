# HONEST CAPABILITY STATUS — KERN

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
**279/279 OK** (Debug AND ReleaseSafe); without `z3` in `PATH` — 393 passed + 8 skipped
(solver-dependent tests skip by design).
Reference `valid_v1_3.kimg` → the Merkle root matches Python↔Zig (confirmed both ways).
Decision coverage → **100.0 %** (30/30). Mutation score → **95.0 %** (38/40; 2 provably
equivalent → 100 % effective).

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
| QuixBugs (real execution) | **31/31 (100 %)** |
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
| 1 | `KimgHeader.parse` did not validate `major` and `hash_algo` (the spec requires it) | correctness |
| 2 | `checker_id` mask: `@truncate` wrapped 32→0 (**the bug exists in the spec too**) | security |
| 3 | Field 20..24 was named `schema_version` instead of `hash_algo` | spec conformance |
| 4 | `Eq2.encode(p,n)` was missing (public spec API) | API completeness |
| 5 | 2 Lean theorems were **tautologies** (`∃ res, f = res`) | proof honesty |
| 6 | "51 GB/s" was presented as read speed (it is RAW addressing) | metric honesty |
| 7 | The mutator edited sources **in place** (wiped edits, broke parallelism) | tooling |
| 8 | The mutator mutated **inside comments** → false "survivors" | tooling |
| 9 | C-ABI `kern_localize` was **uncallable** (one line served as both declaration and formula) | interface |
| 10 | `kernx build` crashed with a **raw traceback** instead of a clear error | UX |

---

## 6b. Registry of defects from the audit of 2026-10-14 (#48–#55)

| # | Defect | Class |
|:--:|:--|:--|
| 48 | The line `theorem CANFAIL_PROBE := by sorry` was left over from an interrupted run | tooling/honesty |
| 49 | The CI Lean stage used `./formal/check.sh \| tail -3` — the RC came from `tail`, not from the check | tooling/CI |
| 50 | A stale `.mutation.lock` (dead PID) blocked the mutator forever | tooling |
| 51 | `humaneval_api.py` did not understand reasoning models: `content = null` → `TypeError` | tooling/benchmark |
| 52 | `tools/mutate_zig.py` was BROKEN in HEAD | tooling (critical) |
| 53 | `audit_manifest.sh` used Zig 0.13 syntax (`zig test src/test_root.zig`) | migration |
| 54 | `slugify` lower-cased ASCII only | correctness |
| 55 | `payloadSlice` and `objectPayloadRaw` chose the SIZE in opposite ways | correctness (latent) |

---

## 6c. Registry of defects from the audit of 2026-10-15 (#56–#58)

| # | Defect | Class |
|:--:|:--|:--|
| 56 | The SLSA tool attested Debug binaries | tooling/attestation |
| 57 | Stale numbers in the documentation after the migration | documentation |
| 58 | `tools/audit_manifest.sh` read the wrong log name | tooling/CI |

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
> — a real documentation gap found by the line-by-line audit of 2026-10-20. They are listed here so that the range `#1–#217`
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
> one-line summary each, so that the range `#1–#217` has **no holes in either language**. The third column reproduces the
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

## 6e. Registry of defects from the pre-release session of 2026-10-19 (#153-#177)

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

**Honest caveat.** The full run of these 139 targets ended with `RC=0` and
`TOTAL: 141 non-vacuous | 0 VACUOUS | 0 case errors`, but the guard itself
declared it invalid — for reasons (a)+(b) of #173, i.e. **because of a guard
defect, not the run** (final tree: clean, no injection markers).

---


## 7. Summary

**MEASURED/TESTED:** the KIMG core (parser, builder, Merkle, KERNFS, the Gate, KERN-X,
cache, 5 SMT theories, C-ABI) and KERN-Next (parser, validator, SQLite, snapshot, diff,
packet, report, cache) — **401 + 53 tests, all green** (with `z3` in `PATH`; without it —
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

