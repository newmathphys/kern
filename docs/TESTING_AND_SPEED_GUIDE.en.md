# KERN — Testing & Speed Guide (v2.5)

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->436 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->468 · CHECK <!-- fact:check_targets -->159 · cases <!-- fact:canfail_cases -->184 · anchors <!-- fact:anchors -->145 · registry <!-- fact:registry_targets -->208 · META <!-- fact:meta_targets -->35 · Lean <!-- fact:lean_theorems -->143 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

> Canonical document: **what** we test, **how** we measure it, and **what** makes it fast.
> Every number here comes from a run; where a gain was NOT measured, it says so.

## 1. Verification matrix (8 sections)

### Section 1 — Static analysis (before execution)
| Method | Tool | Fact |
|:--|:--|:--|
| AST parsing & types | `tools/kern_contracts.py` | 7 languages: `.py .zig .c .rs .ts .js .go` |
| McCabe cyclomatic complexity | `--xray` | `CC = branches + 1`, smell threshold > 15 |
| Code smells | `--xray` | Deep Nesting > 3, Long Parameter List > 5 |
| Dead branches | `[DEAD BRANCH]` (Z3 `UNSAT`) | `xray_demo.py`: 3/3 findings |
| Redundant guards | `[REDUNDANT GUARD]` | condition always true |
| Array bounds | `[BOUNDS PATH]` | length from a **literal** or `len(arr)` — **no annotations** |
| SAST / anti-cheat | `--anti-cheat`, `--import-lock` | 5 cheat classes + slopsquatting |
| MCP security | `--audit-mcp`, `--mcp-lock` | injections, zero-width Unicode, rug-pull |
| Parser hardening | `make parser-security-check` | comment-in-string, type-alias spoofing |

### Section 2 — Classical testing
| Method | Fact |
|:--|:--|
| Unit / boundary | **400** core tests (393 passed + 8 skipped) + **53** KERN-Next |
| Property-based | `truth.zig`: 500 random inputs × 2 laws (Belnap lattice, Hamming) |
| Min-shrinking | window cascade `10 → 5 → 2 → 1 → 0` (only adds constraints — sound) |
| Metamorphic | `builtin_lia`: 20 systems × 3 transforms = **60/60** |
| Edge cases | `make edge-cases` — 10 checks |

### Section 3 — Formal verification
| Method | Fact |
|:--|:--|
| Lean 4 | **8 files, 143 theorems, 0 errors, 0 sorry** |
| Proof-DAG checker | `trusted: 0 \| holes: 0` on QF_LIA, QF_S, IEEE-754, loops, arrays, automata, RLS |
| Belnap B₄ | `JOIN_K(T,F)=B`, conflict absorption, Evidence Decay, Scoped Epoch |
| Floyd–Hoare | `--loops`: Init + Consecution + Post + Termination |

### Section 4 — Self-verification & evolution
| Method | Fact |
|:--|:--|
| Can-fail discipline | **159 CHECK targets / 126 proven able to fail**, **184 cases, 0 vacuous** |
| Mutation testing | **1376 / 1421 sites killed = 100.0 %** (21 files, no sampling); gate 40/40 |
| SBST | `--gen-tests`: 100 % of reachable branches (dead ones marked) |
| Genetic improvement | `--simplify` + equivalence proof via `--diff-equiv` |
| Auto-repair | `--heal`: F → synthesized guard → **T**, with `.bak` + atomic replace |

### Section 5 — Dynamic & exploratory
| Method | Fact |
|:--|:--|
| Symbolic execution | `kernc prove` + SMT-LIB2 |
| Concolic | `--concolic`: 9 concrete runs, **6/6 branches**, dead 0 |
| Differential | `lia-diff`: 100 systems vs Z3, **0 divergences**; `opt-diff`: Debug == ReleaseSafe == ReleaseSmall |
| Evolutionary fuzzer | `evo_fuzzer.py`: 100 individuals, **0 crashes, 0 false accepts** (found #155) |
| Adversarial fuzzing | `proof-tamper`: **40/40** forgeries rejected |
| Fuzz corpus | `fuzz-corpus`: 8 files, 0 crashes, determinism |

### Section 6 — Coverage & traceability (DO-178C / ISO 26262)
| Method | Fact |
|:--|:--|
| MC/DC | **30/30 = 100.0 %** |
| Traceability | `formal/certification/TOR.md` + `TRACEABILITY_MATRIX.csv` |

### Section 7 — Low-level & hardware
| Method | Fact |
|:--|:--|
| Sanitizers / OOM | ReleaseSafe, `checkAllAllocationFailures`, **0 leaks** |
| Binary audit | **29 694** `%ymm` registers (AVX2), `GNU_STACK RW` without `E` |
| Throughput | `bench-simd8`: **2.42 GB/s** (BLAKE3, 64 MB) |
| Side channels | `timing_safe.eql` ×6; Welch **\|t\| = 0.11** |
| 2-safety | `@kern:secret`: `PROVEN NON-INTERFERENT, trusted: 0` |
| DST (TigerBeetle-style) | `kern-dst`: 10 seeds × 50 steps = **500**, 567 interceptions, 100 % deterministic |
| Cross-architecture | QEMU **ARM64** + **PowerPC64 BE**: **393 passed / 8 skipped / 0 failed** |

### Section 8 — Next horizon
| Method | Fact |
|:--|:--|
| Translation validation (CompCert-style) | `-O2` `objdump -d -M intel` → equivalence: **PROVEN, trusted: 0**; corrupted → REFUTED |
| RLVR oracle | `R ∈ {-2, -1, 0, +1}`; a cheating or refuted candidate **never** gets `R > 0` |
| Action / FinOps firewall | HTTP **200 / 422 / 409** through the B₄ lattice |
| RAG conflict engine | `CONFLICT B(1,1)` + minimal conflict core |
| Hadamard matrices | N=2,4 → SAT + `H·Hᵀ = N·I`; N=3 → **UNSAT** |
| WebAssembly | `kernc.wasm` **85 526 bytes**, 5 exports incl. `verify_proof` |

---

## 2. Speed-ups for 32 GB DDR4 + i7-7700 (8 threads)

| Speed-up | How | Measured |
|:--|:--|:--|
| **`opt-diff` cache** | 3 profiles keyed by `sha256(src/)` in `/dev/shm/kern_opt_diff_cache` | **90 000 ms → 47 ms** (×1900) |
| **Mutator slots in `/dev/shm`** | tree copies + warm `.zig-cache` in RAM, reused between mutants | 0 SSD accesses |
| **Two-stage fail-fast** | Stage 1: `zig test --test-filter <module>` → Stage 2 (full suite) only if survived | Stage1 **2 s** vs Full **10 s** = ×5 on killed mutants |
| **Parallel workers** | `--jobs 6` (each with its own slot and cache) | ×2.15 (59.6 s → 27.7 s) |
| **`KERN_MUTATE_FAST=1`** | fewer iterations of stress loops (no test disabled) | 11 390 → 5 811 ms (×1.96) |
| **SIMD-8 BLAKE3** | `@Vector(8, u32)`, `align(32)` | 2.42 GB/s |
| **`/dev/shm` for `.smt2`** | `lia_diff.py`, `kern_contracts.py` | fsync latency removed |
| **Slot cache cap** | every 25 mutants, drop the whole cache above 800 MB | 41 trims, **ENOSPC = 0** |

**Honest about `align(32)`:** measured **2.42 vs 2.41 GB/s** — no gain (the change is
harmless but is not called a speed-up).

---

## 3. Defect timeline — which test caught which bug (#123–#157)

| # | What was broken | Caught by |
|:--|:--|:--|
| **#123** | weightless `th-lemma` inside `unit-resolution` unchecked | `--full-file` + `get-proof` dump |
| **#124** | single global PRNG in `sample_stratified` → moving target | repeated runs |
| **#125** | empty `ProofVerdict{}` passed `checksPass()` | `--full-file` |
| **#126** | race between instances patching the tree | `tree_lock.py` |
| **#127** | `check-integrity` did not re-hash the data | **`bitrot-chaos`** (11/20 slipped through) |
| **#128** | object names not covered by the Merkle root | `bitrot-chaos` (30/30 after fix) |
| **#129** | `kernc verify` returned `rc=0` on a refuted contract | `pcc-check` |
| **#130** | vacuous `pcc-check` case | `canfail --only` |
| **#131** | `src/next/*` never compiled by the mutator (51 fake sites) | acceptance: `grep 'next' test_root.zig` |
| **#132** | vacuous `gen-tests-check` | `canfail --only` |
| **#133** | presets used `_prove_checked` without `_smt_verdict` | `--full-file` |
| **#134** | `--xray` falsely accused guard-clause functions | `make bounds-check` |
| **#135** | `@kern:len` read from a neighbouring function | `make bounds-check` |
| **#136** | CHECK target with no Makefile entry | `registry.py` |
| **#137–#139** | SMT parse errors were reported as **proven** | `make loop-check` (3 outcomes required) |
| **#140** | stale canfail anchor after refactoring | `--check-anchors` |
| **#141** | `--xray` demanded an annotation in a Zero-Annotation mode | review |
| **#142** | vacuous `state-inv-check` | `canfail --only` |
| **#143** | checker **rejected a correct** Z3 proof (Farkas weight `-1`) | `[dbg-farkas-bad]` dump |
| **#144** | vacuous `ffi-bridge-check` | `canfail --only` |
| **#145** | RLS: invariant as one formula → 4 trusted steps | dump + per-component check |
| **#146** | model validator called `SPURIOUS` what it could not evaluate | `@kern:secret` |
| **#147** | vacuous `action-firewall` / `rag-conflict` | `canfail --only` |
| **#148** | vacuous `fuzz-corpus-check` | `canfail --only` |
| **#149** | `--xray`: `if …: return` did not narrow the path | MCP test |
| **#150** | `wasm-check` did not roll back its patch | `canfail --only` |
| **#151** | vacuous `kimg-grep-check` (gate did not rebuild) | `canfail --only` |
| **#152** | test expected `spurious` instead of `unsupported` | `zig build test` |
| **#153** | 256 KB buffer too small for a 51-step proof | native WASM test |
| **#154** | `mcp_selftest` failed without `z3` in PATH (class #110) | `env -i` run |
| **#155** | unresolved `@xN` let a forged proof be **accepted** | **`evo-fuzzer`** |
| **#156** | SIGTERM did not roll back mutator patches | interrupted run |
| **#157** | `write_atomic` lost the `+x` bit (29 scripts) | **full `canfail` sweep** |

**Pattern:** 35 of 40 defects were found by testing the **checking tools themselves**
(`canfail --only`, mutation, dumps, full sweep) — not the code under test.

---

## 4. Full population mutation sweep

```bash
python3 tools/mutate_zig.py --max 5000 --jobs 6 --require-solver   # all 1421 sites
```
Result (recorded in `docs/METRICS.en.md §33`):
```
MUTATION SCORE (raw):  100.0%  (1421/1421 killed)
REAL_SECONDS=1383      (23 min, 0 survivors)
```

---

## 5. Reproduce everything

```bash
make zig test test-next formal-ci proof-tamper evo-fuzz-check lia-diff \
     opt-diff-check bitrot-chaos pcc-check dst-check xray-check gen-tests-check \
     concolic-check homeostatic-heal-check bounds-check loop-check float-nan-check \
     string-contracts-check state-inv-check polyglot-7-check presets-check \
     arbitrage-check double-spend-check ffi-bridge-check sql-policy-check \
     pricing-matrix-check anti-cheat-check mcp-audit-check noninterference-check \
     belnap-swarm-check parser-security-check action-firewall-check rag-conflict-check \
     rlvr-oracle-check bug-hunt-check translation-val-check hadamard-check \
     wasm-check html-canvas-check kimg-grep-check mcp-selftest fuzz-corpus-check \
     binary-audit tree-lock mutate canfail-anchors registry evidence-gate svg-check
```

Full `canfail` sweep: **184 non-vacuous / 0 vacuous / 0 case errors**.
