# KERN — METRICS JOURNAL

> Every number here comes from an actual run. Nothing from memory.
> Updated per iteration. English translation of `docs/METRICS.md`; the Russian
> original remains the source of truth for historical sections.

## Version: v1.3 · Date: 2026-10-10

---

## 1. Tests

| Suite | Debug | ReleaseFast |
|:--|:--:|:--:|
| Core (`src/test_root.zig`) | **279/279** | **279/279** (ReleaseSafe) |
| KERN-Next (`src/next/test_root.zig`) | **38/38** | **38/38** (ReleaseSafe) |
| Lean 4 (`formal/check.sh`) | **8 files, 42 theorems, 0 errors, 0 sorry** | — |
| `kern-attack` | 2/2 attacks blocked | — |

> Debug covers every contour: DoS, NaN, JSON, bounds, memory alignment (Echelon 1),
> thread pool (Echelon 3). ReleaseSafe confirms the absence of UB.
>
> ⚠️ **Historical sections (§12–§19) keep the numbers of their own iteration**
> (you will see 114/142/177/183 there — those are not typos, they are a progress
> journal). Current numbers live only in §1 and in the latest section.
>
> Note on translation: where a number in §1 was stale at translation time, the
> current measured value is used (core suite 198 → 279; `docs/evidence/core_tests.log`).

## 2. Official benchmarks (no local models)

| Benchmark | Tool | Result |
|:--|:--|:--|
| **SWE-bench Lite** | `swebench` + Docker | **3/3 resolved, 0 infra failures** |
| **HumanEval / HumanEval+** | `evalplus` (external API) | **0.524 / 0.500** (see §11) |
| **MBPP+** | `evalplus` | 378 tasks downloaded — ⛔ not generated (API time) |
| **SMT (Alive2 / Hacker's Delight)** | Z3 via our bridge | **8/8** (6 proved, 2 counterexamples) |
| **QuixBugs** | execution (fuel) | **31/31 bugs (100 %)** |
| **Refactory** | differential | **1438/1782 bugs (80.7 %)** |
| **CyberSecEval (Meta)** | AST rules | 28/351 (8.0 %) |
| **Mutation duel** | boundary sweep | Unit 20 % / KERN **90 %** / 10/10 explained |

## 3. Mutation testing (our own Zig code)

| Run | Mutants | Killed | Survived | Score |
|:--|:--:|:--:|:--:|:--:|
| 1st | 40 | 27 | 13 | 67.5 % |
| 2nd | 36 | 34 | 2 | 94.4 % |
| 3rd | 36 | 35 | 1 | 97.2 % |
| **4th (final)** | 36 | 36 | **0** | **100.0 %** |

The single remaining mutant is *equivalent* (`>=` vs `>` when `offset == len`).

## 3b. Logical stress of the Z3 bridge (`src/smt_stress.zig`) — **18/18**

Additionally: **Float (QF_FP)** — `=` (SMT) vs `fp.eq` (IEEE), NaN, ±0.0.

Additionally: **BitVec(1024)** (no truncation to u64), **division by zero** (defined in
SMT), **false BitVec contract** (counterexample).


## 4. Performance (.kimg, 10 000 objects)

| Operation | Time |
|:--|--:|
| Parse 128-byte header | 0.000 ms |
| Merkle root (10 000 leaves) | 5.43 ms |
| Mount | 5.46 ms |
| **Read all objects — RAW (addressing)** | **0.025 ms** |
| **Read all objects — SAFE (+SHA-256)** | **8.27 ms** |
| Write image (3.1 MB) | 31.2 ms |

### ⚠️ CORRECTED: "51 GB/s" referred to RAW addressing only

**What was wrong.** Reports quoted "zero-copy read 30–51 GB/s" as a *read* throughput.
In reality that was the speed of pure **slice addressing** (`objectPayloadRaw` —
pointer arithmetic with no access to the contents). The real **safe** read
(`objectPayload`) compares `SHA-256(payload)` against the descriptor digest
(a security fix: Merkle covers only the descriptor table, and without this check a
payload substitution went unnoticed).

**Measured (`src/perf_bench.zig`, ReleaseFast, 10 000 objects / 2 MB payload):**

| Read path | Throughput | Slowdown |
|:--|--:|--:|
| RAW (addressing, no check) | **76 008 MB/s** (≈ 76 GB/s) | 1× |
| Safe (+ SHA-256) | **231 MB/s** | **330×** |

SHA-256 on this CPU runs at ~1.5 GB/s, so the hash — not "memory speed" — determines
the safe read rate.

**Conclusion (honest):** "memory speed" is reachable only for addressing. Safe reads
with integrity checking run at **hundreds of MB/s**, and that is a deliberate
trade-off: safety beats a peak number.

**Optimisation direction (not implemented):** fold the payload into the Merkle tree
(instead of a separate digest in the descriptor) — then a single root check at mount
time validates *all* contents and reading becomes free again. This is a `.kimg`
format change (v2).

### Stress with 1 000 000 objects (`src/kimg_stress.zig`)

| Operation | Time |
|:--|--:|
| Build 1e6 objects | 114 ms |
| Write image (100 MB) | 1639 ms |
| Merkle (1e6 leaves) | 560 ms |
| Mount | 578 ms |
| **Random access** | **0.0006 ms** (target < 0.005) ✅ |

> Numbers were re-measured after the payload-integrity fix: reads now include the
> SHA-256 comparison, so random access grew from 0.0001 to 0.0006 ms — still
> **8× faster** than the target.

## 5. Stress tests (1 000 000 iterations)

| Test | Result |
|:--|:--|
| `tests/stress_1m.zig` | 50–110 M projects/s, 0 FPR (by construction) |
| `src/stress_real.zig` (real code) | 45–64 M checks/s, **0 law violations, 0 panics, 0 gate openings** |

## 21. Attestation contour v2: SLSA, diff-disasm, proof-checker, concurrency

**Date:** 2026-10-11. Five items from the "what's still missing" list closed.

| Case | Verdict |
|:--|:--|
| Paradox `x>5 ∧ x<2` | vacuous ✅ |
| Overflow `x+1 > x` (i32) | refuted ✅ |
| `x+1 > x` (Int, unbounded) | proved ✅ |
| NIA `x*x >= 0` | proved ✅ |
| Alive2 `x*8 == x<<3` | proved ✅ |
| Alive2 (false) `x/2 == x>>1` signed | refuted ✅ |
| Dead branch `x*x < 0` | vacuous ✅ |
| Contract `x>0 => x+1>1` | proved ✅ |
| Contract (false) `x>0 => x+1>5` | refuted ✅ |

---

## 22. Build-runner notes (Zig 0.17) — read this before "fixing" a red log

**`failed command: ./.zig-cache/o/<hash>/test --cache-dir=./.zig-cache --seed=0x… --listen=-`
is printed even when ALL tests pass.** This was misread once (as a "flake under load") and
is documented here so it is not misread again.

Mechanism: since late 0.13 and in 0.17, `zig build` runs the tests as a SEPARATE child
process that talks to the parent over an IPC protocol (`--listen=-`, `-` = over
stdout/pipe). The parent takes the STEP VERDICT from the PROTOCOL, while the
`failed command:` line is emitted from the child's exit/pipes closing. So "a line in the
log" and "the step verdict" are different things.

Evidence that the run is fine (three independent facts):

1. **Zig never caches a failed step.** Minimal project check: a failing step is re-run on
   every invocation (rc=1 again), a passing step is cached (no output). For KERN a fresh
   `zig build test --summary all` reports **`Build Summary: 3/3 steps succeeded`**,
   **`test success`**, **`run test cached`**.
2. **Running the test binary directly** prints `All 279 tests passed` (and `All 38 tests
   passed` for KERN-Next) with rc=0 and NO `failed command` line at all
   (341 output lines vs 65 via `zig build`).
3. **CI #72 / #73** (same contour: build/test/test-next/test-fault + Lean + CAN-FAIL) —
   `success` on every step.

**Rule:** judge a build by its exit code and `zig build … --summary all` — never by
grepping the log.

**Do not `rm -rf .zig-cache/o`.** That directory holds not only artifacts but also the
`addTranslateC`-GENERATED module `sqlite3_bridge.zig` (the SQLite C header is translated
there). Deleting it breaks the build (`FileNotFound … sqlite3_bridge.zig`) until a full
`rm -rf .zig-cache` + rebuild. Cleaning the whole `.zig-cache` is safe; deleting only
`o/` is not.

---

## §23. v2.5, Echelon 1 (local branch `v2.5-dev`)

**Status: local only** — nothing is pushed; `main` stays frozen at `28e6bb9` (release `v2.4.0`).
Every item below follows the project rule: a **can-fail case** plus a **falsifiable number**.

### 23.1 Wave 0 — inventory (measured, not guessed)

`./zig-out/bin/kernc audit` runs **five SMT theories for real**: UNSAT-core fault
localization, QF_AX arrays, CHC loop invariants, QF_S strings, CEGIS synthesis. The
can-fail cases behind them (`grep-arrays`, `theories`, `redos-vuln`, `guardrail-verdict`,
`semantic-gap`) are **non-vacuous** (1 non-vacuous / 0 vacuous / 0 errors each). The Z3
sandbox (environment whitelist + `-memory:256`) and `examples/guardrail_proxy.py` already
existed too.

**Conclusion that changes the work estimate:** the gap is not "no mathematics" but
**"engines exist — the front-end that feeds them arbitrary code does not"**, because
`kernc audit` runs those theories on hard-coded examples. Of the 40 planned items, 6
already have a core, 3 are partial, 31 are new.

### 23.2 Item 7 — Hamming-coded admission (`src/next/truth.zig`)

Two 64-bit constants that are exact bitwise complements (Hamming distance 64). A
`comptime` block refuses to build if they stop being complements or if `TOLERANCE >= 32`.
`decode()` returns `null` beyond the tolerance (fail-closed) and `decodeOrDeny()` closes
the Gate. The kernel's `e` type (`u1`) is unchanged — the primitive is isolated.
**Honest scope:** this is defensive redundancy, NOT a verified property and NOT a
radiation claim (SEU rates cannot be measured here, and DO-178C does not require this
encoding).

### 23.3 Item 5 — minimal counterexample (`tools/kern_contracts.py`)

When a contract is refuted, a second query adds a window (`-10 <= p <= 10`) before
`(check-sat)`. **Sound by construction:** only constraints are ADDED, so any model of the
narrowed instance is a model of the original — the reported input still violates the
contract, and the verdict comes from the first, unnarrowed run.
Measured: bounds land before `(check-sat)`; the fallback keeps the original counterexample
when the window is empty (the `x >= 1000000` case). Non-vacuity proven by experiment:
breaking the narrowing (dropping the original asserts) turns `tools/edge_cases_check.sh`
RED (9 -> 10 checks).
**Measured limitation:** QF_BV counterexamples are printed in hex (`#x...`), so the
integer parser does not read them and minimisation does not apply to them yet.

### 23.4 Item 2 — `verifyModelAgainstSmt` (`src/verifier/model_extract.zig`)

For `UNSAT` the solver was never trusted (the proof is re-checked). For `SAT` the model
was accepted **as printed**. Now the values from `(get-model)` are substituted back into
the contract's `(assert ...)` and every assert is evaluated by an **independent Zig
evaluator** (recursive descent, `i128` inside, no allocations). One false assert ->
`spurious` -> the model is rejected and the counterexample is NOT presented.
End-to-end: `[MODEL VERIFIED] all contract asserts are true on the model (2)`.
Supported fragment: `+ - * / div mod` (SMT-LIB `div` floors, `mod` takes the divisor's
sign), comparisons, `and/or/not`, `ite`. Bit-vectors return `unsupported` — an honest
refusal, never an "ok". Non-vacuity: the new `model-verify` can-fail case breaks the check
and requires `make test` to go RED (1 non-vacuous / 0 vacuous / 0 errors).

### 23.5 Item 8 — hard file limit for the Z3 process (`src/verifier/z3_bridge.zig`)

Zig 0.17's `std.process.spawn` has **no pre-exec hook**, so `setrlimit` cannot run inside
the child. Linux lets the PARENT limit an already-running process by PID:
`prlimit64(pid, RLIMIT_FSIZE, {0,0}, null)` — applied right after `spawn`.
Verified: no "not applied" warning is printed (the call returned 0), and kernel semantics
are confirmed — with `FSIZE = 0` a writer is killed by SIGXFSZ and no data reaches the
disk (an empty file may be created, but nothing can be written).
**Deliberately NOT added:** Z3's own `-T:<sec>` / `rlimit=<N>` flags. They change solver
semantics (UNSAT may become `unknown`) and could rewrite the verdicts of already published
evidence, while duplicating the timeout the killer thread already enforces.

### 23.6 Numbers after Echelon 1 (part)

Core tests **289/289** (was 283; +6 model-check tests) · KERN-Next **39/39** ·
test-fault OK · test catalogue **329** · defect registry 63 entries (#1-#123) ·
`registry.py`: 104 targets, **81/81 CHECK** with a proven-can-fail case.
