# KERN — METRICS JOURNAL

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->441 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->470 · CHECK <!-- fact:check_targets -->166 · cases <!-- fact:canfail_cases -->198 · anchors <!-- fact:anchors -->159 · registry <!-- fact:registry_targets -->217 · META <!-- fact:meta_targets -->37 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

> **Note on quoted tool output.** KERN's tools print their verdicts in Russian; lines quoted verbatim (e.g. `[dbg-ur] посылок: …`, `0 паник`) are kept byte-for-byte, because the can-fail gates match those exact strings. Everything else in this file is English.


> Every number here comes from an actual run. Nothing from memory.
> Updated per iteration. English translation of `docs/METRICS.md`; the Russian
> original remains the source of truth for historical sections.
>
> **CURRENT STATE (2026-10-20):** v2.5.1 · core <!-- fact:core_tests -->441 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->470 ·
> CHECK <!-- fact:check_targets -->166/<!-- fact:check_targets -->166 · cases <!-- fact:canfail_cases -->198 · anchors <!-- fact:anchors -->159 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 differential.
> **The journal below is append-only history.** The `v1.3` heading refers to 2026-10-10
> and does NOT describe the current state.

## History: v1.3 snapshot · 2026-10-10 (not current)

---

## 1. Tests

| Suite | Debug | ReleaseFast |
|:--|:--:|:--:|
| Core (`src/test_root.zig`) | **279/279** | **279/279** (ReleaseSafe) |
| KERN-Next (`src/next/test_root.zig`) | **38/38** | **38/38** (ReleaseSafe) |
| Lean 4 (`formal/check.sh`) | **8 files, 92 theorems, 0 errors, 0 sorry** | — |
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
| **QuixBugs** | execution + AST trace | **33/40 divergences** |
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

Core tests **299/295** (was 283; +6 model-check tests) · KERN-Next **39/39** ·
test-fault OK · test catalogue **339** · defect registry 63 entries (#1-#123) ·
`registry.py`: 105 targets, **82/82 CHECK** with a proven-can-fail case.

### 23.7 Item 4 — `let` bindings: the gap was NOT the expansion, it was the blowup

Measured first: `proof_check.zig` **already** walks `let` bindings (`collect()` fills
`c.abbrev` / `c.stepexpr`, and `expand()` resolves them with a depth limit of 128). So the
"support `let`" part of the item was done before this sprint.

The REAL gap is the one the operator warned about: a depth limit bounds nesting, not the
**total node count**. Z3 compresses a proof DAG into a tree via `let`, so the same term can
be named many times; expanding every name into its body gives exponential growth (the chain
`$a0 = (+ $a1 $a1)`, `$a1 = (+ $a2 $a2)`, ... needs 2^N nodes).

Implemented: an explicit **expansion budget** (`EXPAND_NODE_BUDGET = 200_000`, counter
`ExpandBudget{left, used}`). When the budget runs out, expansion STOPS and the term is
returned as-is. This is **conservative**: an unexpanded name will not match a contract
clause, so the premise becomes unbound and the proof is REJECTED (`premises_unbound`) —
incompleteness leads to a refusal, never to a false "verified".
Test: a 40-level `let` bomb (2^40 nodes if expanded naively) returns within the budget, and
the test asserts the budget was actually EXHAUSTED (`left == 0`) — so the protection fired,
rather than the input being small by luck.

### 23.8 Items 3 and 1 are the SAME piece of work (measured finding)

Raw proof dump for `audits/musl/abs.c` (3001 bytes, QF_LIA) shows the blocking shape:

```lisp
(unit-resolution @x210 (unit-resolution @x150 ((_ th-lemma arith) @x224 @x141 @x90 $x159) $x160)
                         ((_ th-lemma arith) @x141 @x224 @x90 $x61) false)
```

Note: `(_ th-lemma arith)` here has **NO `farkas` keyword and NO weights**. The checker's
`verifyFarkas()` verifies a certificate only when explicit non-negative weights are present;
without them it returns `structural_only` (counted as trusted), which is exactly why the
`abs` row is SKIP.

A weightless arithmetic lemma can only be verified by **our own linear-arithmetic
procedure**: negate the literals, conjoin them, and prove the system unsatisfiable.
Fourier–Motzkin elimination gives a **sound** UNSAT answer (rationals ⊇ integers, so an
unsatisfiable relaxation implies an unsatisfiable integer system), and is complete enough
for the conjunctive fragment.

So item 3 (#123) and item 1 (`builtin_lia.zig`) are **one piece of work**: build the FM core
first, then use it to verify weightless `(_ th-lemma arith)` steps. Doing item 3 by
"accepting those steps on trust" was rejected on purpose: it would turn `holes: 0` into
fiction (defect #81).

### 23.9 Item 1 — built-in LIA solver (`src/verifier/builtin_lia.zig`)

**Why it exists.** With no `z3` on the machine the Gate stays closed (`e = 0`) for EVERY
input, including a trivial linear contract. This module closes the simple linear fragment by
itself, and — more importantly — it is the only sound way to verify the weightless
`(_ th-lemma arith)` steps that block `#123` (see 23.8).

**Method:** Fourier–Motzkin variable elimination over constraints of the form
`sum(c_i * x_i) + k <= 0`.

**Soundness, stated plainly.** FM decides the system over the RATIONALS. Integers are a
subset of the rationals, so unsatisfiability of the rational relaxation implies
unsatisfiability of the integer system: `.unsat` is **always sound**. The converse does not
hold (a rationally satisfiable system may have no integer solution), therefore `.sat` is
returned ONLY when a concrete INTEGER point was found and **checked by direct evaluation of
every constraint** (`satisfies()`); otherwise the verdict is `.unknown` — an honest
`Belnap N, e = 0`. Strict inequalities need the integer shift `a < b <=> a - b + 1 <= 0`,
otherwise FM (working over Q) cannot see that `x > 5 and x < 6` is unsatisfiable over Z.

**Guards:** `MAX_CONSTRAINTS = 20_000` (FM generates lower×upper combinations — a
combinatorial blow-up otherwise), `MAX_VARS = 32`, an i64 overflow check inside `combine()`,
and a bounded point search (at most 4 variables and 200k candidate tuples) — beyond that the
solver honestly says `.unknown` instead of guessing.

**Differential gate against real Z3 (`make lia-diff`, `tools/lia_diff.py`).** 40 generated
linear systems are solved BOTH by the built-in solver and by Z3, then compared:
`builtin == UNSAT` requires `Z3 == unsat` (0 false accepts) and `builtin == SAT` requires
`Z3 == sat` AND the returned point must satisfy the system. Result: **40 compared, 0 false
accepts, 0 false counterexamples**.

**Non-vacuity proven by experiment.** Breaking the solver (return `.unsat` always) makes the
gate report **25 false accepts** and print "NOT SOUND"; restoring it returns to 0. The case
is registered in the can-fail harness as `lia-soundness` -> `make lia-diff`
(1 non-vacuous / 0 vacuous / 0 errors), and `registry.py` now reports **82/82 CHECK**
targets with a proven-can-fail case.

**CLI:** `kernc lia <file>` — lines of the form `LE c1:name1 c2:name2 ... k`
(meaning `sum + k <= 0`), printing exactly one of `UNSAT` / `SAT name=value ...` /
`UNKNOWN <reason>`.

### 23.10 Variant B, measured first: the premise extraction was NOT the blocker

The proposal for closing `#123` was: make `checkUnitRes` resolve INLINE sub-steps (e.g.
`(unit-resolution ... $x160)`, `((_ th-lemma arith) ... $x61)`) to their conclusion (the
last element), so the outer `unit-resolution` can see the clauses of the inner ones.

**Measured before changing anything** (diagnostics under `KERN_DEBUG_LIA=1` on the real
`abs.c` proof): the premise extraction ALREADY does this. `premiseTerm()` ->
`resolvePremise()` resolves `@xN` through `c.stepexpr`, and for any node that
`isStepExpr()` accepts it returns `expand(proved(step))` — i.e. exactly the last element of
the sub-step. The diagnostic print in `checkUnitRes` confirms it with numbers:

```
[dbg-ur] посылок: units=1 clauses=2 concl_false=true     <- outer unit-resolution
```

The outer step really does see both clauses (`$x168`, `$x160`) and the unit (`$x61`). So the
"~15 lines in the premise helper" fix would change nothing.

**What actually blocks it.** With `units=1` and `clauses=2`, syntactic literal
complementation cannot empty both clauses, so `remaining.len != 0` while the conclusion is
`false`, and the rule `if (concl_is_false) return .bad;` fires. Z3's `unit-resolution` here
is stronger than the checker's model: the premises are jointly contradictory only with the
arithmetic lemmas taken into account.

**Honest options (not applied without a decision).**
* classify as `.unverifiable` (trusted) — rejected: it weakens refusals;
* **extend the model soundly**: for a `false` conclusion, verify the CLAUSE SET is
  unsatisfiable by enumerating one literal per clause (bounded) and requiring every
  combination to be arithmetically UNSAT through `builtin_lia` — sound and complete for
  small sets, `.unverifiable` beyond the enumeration budget;
* leave it as an honest `SKIP`.

The debug output stays in the code, gated behind `KERN_DEBUG_LIA=1`, because it is what
settled the question — and it will settle the next one too.

### 23.11 Item 3 CLOSED — `musl abs.c`: SKIP -> PROVEN (honest, `trusted: 15`)

What was added: `checkFalseBySplitting()` + `unitsPlusPicksUnsat()`. When a
`unit-resolution` concludes `false`, the checker now verifies that the premise CLAUSE SET is
unsatisfiable by **case splitting** (sound by distributivity of `and` over `or`): for every
choice of one literal per clause, `{units} ∪ {l_1..l_k}` must be unsatisfiable — checked
syntactically (`P` / `(not P)`) or arithmetically through `builtin_lia` (Fourier–Motzkin).
A clause falsified entirely by the units already gives the contradiction. Budget
`MAX_CLAUSE_COMBOS = 16`; beyond it — an honest `.unverifiable`.

**A misclassification was fixed, and this is the honest reason `abs.c` moved.** The helper
originally returned a bool, so "could not translate the literals" was reported as
"combination is satisfiable" and the step became `.bad` (rejected). That is a false alarm in
the most dangerous direction. It now returns a three-valued `ComboResult{unsat, sat,
unknown}`: `sat` -> `.bad` (the step really is wrong), `unknown` -> `.unverifiable` (the
step is outside the checker's model, counted as trusted). **No rejection was weakened for
steps that are provably wrong** — but the net effect on this proof is that the step is
tolerated as trusted rather than rejected, so `abs.c` is reported as
`[PROOF VERIFIED] ... farkas: 3 | trusted: 15 | holes: 0`.

**Measured end to end:** `make audits` row changed `SKIP -> PROVEN` for `kern_abs`, while
the control `kern_absBroken` stays `REFUTED` (`a = -10, result = -10`, runtime-confirmed).
Tests added (+2): a satisfiable clause set must return `.bad`; an unsatisfiable one must
return `.verified`.

**What is NOT claimed.** `trusted: 15` is not zero: the remaining trusted steps are mostly
boolean-atom `rewrite`s. `trusted: 0` for this proof is separate work and is NOT claimed.

### 23.12 Closing the gap to `trusted: 0` — measured trajectory 15 -> 8

`abs.c` is accepted as `[PROOF VERIFIED]`, but with trusted steps left. The goal set by the
operator is `trusted: 0`. Work proceeds **one rule at a time**, each step preceded by a dump
(`dumpSexp`) and each step committed separately. Every step below was closed by **proving**
it, never by relaxing `.bad` to `.unverifiable`.

| Step | What was measured first | What was fixed | trusted |
|:--|:--|:--|--:|
| 1 | `[dbg-combo]` printed the exact untranslatable literal: `(not (or (not A) (not B)))` — a CONJUNCTION by De Morgan | `asLeZero`: `(= X Y)` -> TWO inequalities `X-Y<=0` and `Y-X<=0`; `(and …)`; `(not (or …))` -> De Morgan | 14 |
| 2 | splitting was wired only to `concl == false` | `unitsPlusPicksUnsat(..., neg_concl)`; `checkBySplitting(..., concl)`; fallback for arbitrary conclusions | 13 |
| 3 | `[dbg-trusted]` showed `monotonicity` failing | `verifyMonotonicity` used ONLY the first premise; now accumulates substitutions over ALL premises to a fixed point (8 rounds max) | 11 |
| 4 | `[dbg-defax]` printed the expanded clause `(or (or (not A) (not B)) B)` — a PROPOSITIONAL tautology, not an arithmetic one | `isTautologyClause`: `flattenOr` + search for a `l` / `¬l` pair (structural OR canonical comparison) + arithmetic path | 9 |
| 5A | `[dbg-introdef]` printed `(and (or (not (>= a 0)) (= z3name!1 a)) (or (>= a 0) (= z3name!1 (* (- 1) a))))` — the definition `z3name!1 = ite(a>=0, a, -a)` | `verifyIntroDef`: STRUCTURE (two clauses, same name, opposite conditions, `(= z A)` / `(= z B)`) + FRESHNESS (`z` does not occur in `C`, `A`, `B`) | 8 |

### 23.13 A metric that was read wrong: `premises bound: 2/3` is NOT a defect

The counter prints `bound/total` where **`total` includes both `asserted` AND `hypothesis`**
(local assumptions). In `abs.c`: `asserted = 2` (BOTH bound), `hypothesis = 1`. Therefore
`premises_unbound = 0` already, which is exactly what `checksPass()` requires. Proof: the new
`[dbg-unbound]` diagnostic (prints the unbound premise plus every contract clause) **never
fired**. The `3/3` target came from misreading the metric — the third element is a hypothesis,
which by construction is neither bound nor unbound.

### 23.14 Two hypotheses were DISPROVEN by measurement (recorded, not hidden)

* *"`premiseTerm` does not resolve inline sub-steps"* — it does: `[dbg-ur]` printed
  `units=1 clauses=2`, i.e. both clauses and the unit were seen. The real blocker was
  `ComboResult.unknown` being reported as `sat` ("could not translate" treated as "satisfiable"),
  which made the step `.bad` — a false alarm in the most dangerous direction.
* *"`def-axiom` is a linear tautology"* — it is a **propositional** one; the first, purely
  linear attempt changed nothing, and only the dump showed why.

### 23.15 Diagnostic tooling that settled every question (kept in the code)

* `KERN_DEBUG_TRUSTED=1` — prints EVERY trusted step with its rule AND its S-expression;
* `KERN_DEBUG_LIA=1` — prints premise translation, clause combinations and the exact
  untranslatable literal;
* `dumpSexp()` — prints any S-expression (used in the `[dbg-*]` lines above).

### 23.16 What remains (9 -> 8 done; 8 left)

`5 rewrite | 2 unit-resolution | 1 lemma`. Planned as separate micro-steps:
* **5B**: dump the `@x214` subtree, implement `verifyLemma` (walk the subtree over `@xN`
  references with a `visited` set; require `proved(@x214) == false`; every `(hypothesis H)`
  inside must have its negation in `flattenOr($x89)`) + canonical `$x89 = ¬$x121` matching —
  this should also close the 2 dependent `unit-resolution`;
* **5C**: disjunctive `¬concl` in `checkBySplitting` + `(not (= X Y))` as a 2-literal clause
  `(X-Y+1<=0) ∨ (Y-X+1<=0)` -> two-way rewrite equivalence for the boolean-arithmetic case;
* **5D**: the 4 remaining term-level `rewrite`s, by their exact dump.

### 23.17 Micro-step 5B — `lemma` proved (trusted 8 -> 7); a defect found in hypothesis collection

`verifyLemma` implements hypothesis discharge (RAA / disjunction introduction). Two conditions,
both proofs:
1. the subtree referenced by the first argument really derives `false`;
2. EVERY `(hypothesis H)` inside that subtree is refuted by the conclusion: after `flattenOr`
   its disjuncts contain `¬H` — structurally or by canonical comparison form.
The subtree is walked over `@xN` references through `c.stepexpr` with a `seen` set (the proof is
a DAG, not a tree) and a depth cap of 96.

**Defect found by measurement** (`[dbg-lemma]` printed `гипотез 1, дизъюнктов 1; заключение:
(not (>= (+ a z3name!1) 0)) / гипотеза: $x121`): the first version collected hypotheses
UNEXPANDED (`$x121` as an atom) while the conclusion was compared EXPANDED, so nothing matched
and the step stayed trusted. Fixed: hypotheses are collected through `expand`, like the
conclusion. Tests added (+2): a subtree deriving `false` from `(>= a 0)` with conclusion
`(not (>= a 0))` is ACCEPTED; a conclusion `(not (<= a 5))` that does not negate the
assumption is REJECTED.

**Trajectory so far:** 15 -> 14 -> 13 -> 11 -> 9 -> 8 -> **7** (`5 rewrite | 2 unit-resolution`).
**Not yet closed:** the 2 dependent `unit-resolution` need canonical `$x89 = ¬$x121` matching
in `checkUnitRes` — that is the remainder of step 5B.

### 23.18 Micro-step 5C: a claimed report was CHECKED against facts — and it did not hold

Before continuing, an incoming "execution report" (claiming `trusted: 0`, commit `3a1b2c4`,
`premises bound: 2/2`, `rewrite (linear/bool): 15`, and a dump of five rewrites such as
`(= (+ a (* (- 1) a)) 0)`) was verified against the repository. Result:

* commit `3a1b2c4` — **does not exist** (zero matches in the whole git history);
* actual `trusted: 7`, not 0; actual `premises bound: 2/3`, not 2/2;
* actual `rewrite (linear): 10`, not 15;
* **none** of the claimed rewrite forms occurs in the real proof.

Claimed != measured — exactly the failure mode this project exists to prevent. The real
status was `trusted: 7` at that moment.

### 23.19 The REAL expanded dump of the remaining rewrites (measured)

New `[dbg-rw]` output in `checkRewrite` (behind `KERN_DEBUG_LIA=1`):

```lisp
(1) LHS (= P 0)                     RHS (and (<= P 0) (>= P 0))
    P = (+ result (* (- 1) (ite (>= a 0) a (* (- 1) a))))
(2) LHS (= result (ite (>= a 0) a (* (- 1) a)))   RHS (= P 0)
(3) LHS (= result (ite (< a 0) (- a) a))         RHS (= result (ite (<= 0 a) a (* (- 1) a)))
(4) LHS (or (not (>= a 0)) (= z3name!1 a))
    RHS (or (not (>= a 0)) (not (or (not (>= (+ a (* (- 1) z3name!1)) 0))
                                    (not (<= (+ a (* (- 1) z3name!1)) 0)))))
```

**Consequence (by facts, not by guess):** closing these needs THREE different techniques,
not one:
* (1) antisymmetry `X = 0 <=> X <= 0 and X >= 0` with the SAME term `X` — a pure logic law,
  verifiable STRUCTURALLY even when `X` contains `ite`;
* (3) `ite` equivalence: conditions `(< a 0)` and `(<= 0 a)` are complementary and the branches
  are swapped — a STRUCTURAL `ite` check;
* (4) semantic equivalence: `(>= D 0) and (<= D 0) <=> z3name!1 = a` with `D = a - z3name!1` —
  a two-way check through `builtin_lia`, with `(not (= X Y))` split into two strict
  inequalities;
* (2) the term identity `X = Y <=> X - Y = 0`.

### 23.20 Micro-step 5G-1: three STRUCTURAL rewrite identities (trusted 7 -> 4)

The real `[dbg-rw]` dump showed that three of the remaining rewrites contain `ite` INSIDE a
term, so `builtin_lia` cannot touch them — but they do not need a solver at all:

* **(1) antisymmetry of zero**: `(= P 0) <=> (and (<= P 0) (>= P 0))` for ANY term `P`
  (even containing `ite`). It is a pure order law over Z, so nothing inside `P` is inspected:
  `P` must be byte-identical (`sexpEq`) and the two conjuncts must compare `P` with zero in
  OPPOSITE directions (all four spellings handled: `(<= p 0)`, `(>= p 0)`, `(<= 0 p)`, `(>= 0 p)`).
* **(2) transfer across equality**: `(= X Y) <=> (= (+ X (* (- 1) Y)) 0)` for ANY terms `X`, `Y`
  (operands in any order; `(* -1 Y)` and `(- Y)` both accepted).
* **(3) `ite` swap under equality**: `(= X (ite C1 T1 E1)) <=> (= X (ite C2 T2 E2))` with the same
  `X`, complementary conditions (`C1 = ¬C2`) and swapped branches (`T1 ≡ E2`, `E1 ≡ T2`,
  compared structurally OR linearly, so `(- a)` matches `(* (- 1) a)`).

**Measured:** `rewrite (linear): 10 -> 13`, `trusted: 7 -> 4`. Tests added (+3), each with a
NEGATIVE counterpart: identical directions (`(and (<= x 0) (<= x 0))`) rejected; a different
right-hand term rejected; non-complementary `ite` conditions rejected.

**Trajectory:** 15 -> 14 -> 13 -> 11 -> 9 -> 8 -> 7 -> **4** (`2 unit-resolution | 2 rewrite`).

### 23.21 Micro-step 5G-2: form (4) via `or`-congruence with disjunctive negation (trusted 4 -> 3)

The last rewrite of form (4) is `(or A L2) <=> (or A R2)` with the SAME first disjunct `A`
(byte-identical, `sexpEq`). So it suffices to prove `L2 <=> R2`, which needs TWO implications.
The obstacle was measured: `negateAsLeZero(R2)` failed, because `¬R2` is a DISJUNCTION
(`¬(not (or …)) = (or …)`), not a conjunction.

Implemented:
* `negAlternatives()` — decomposes `¬to` into ALTERNATIVES (`¬to = OR(alts)`), each an
  alternative being a conjunction of constraints:
  `(not (or Y1..Yk))` -> one alternative per `Yi`; `(and X1..Xk)` -> one per `¬Xi`;
  `(= X Y)` -> two strict inequalities `(X-Y+1<=0)`, `(Y-X+1<=0)`; otherwise one `¬to`;
* `impliesLinear()` — checks `{from} ∧ ¬to` unsatisfiable by verifying EVERY alternative
  (the distributivity law), through `builtin_lia`;
* `orCongruence()` — same first disjunct, then two-way `impliesLinear` on the second.

**Measured:** `rewrite (linear): 13 -> 14`, `trusted: 4 -> 3`.
**Trajectory:** 15 -> 14 -> 13 -> 11 -> 9 -> 8 -> 7 -> 4 -> **3** (`2 unit-resolution | 1 rewrite`).

### 23.22 Micro-step 5G-3: `musl abs.c` reaches `trusted: 0 | holes: 0`

`[PROOF VERIFIED] steps: 51 | premises bound: 2/3 | mp: 7 | rewrite (linear): 15 |
farkas: 3 | trusted: 0 | holes: 0`.

Trusted-step trajectory (every step closed by a PROOF, never "forgiven" via `.unverifiable`):
`15 -> 14 -> 13 -> 11 -> 9 -> 8 -> 7 -> 4 -> 3 -> 1 -> 0`.

The last three steps were closed by:

1. **Recursive splitting on a DISJUNCTIVE literal** (`unitsPlusPicksUnsat`). MEASURED
   (`[dbg-combo]`): a clause-combination contained the disjunctive literal
   `(or (not (>= D 0)) (not (<= D 0)))`, which cannot be converted into a conjunction of
   constraints. SOUND (case split): a combination is unsatisfiable iff EVERY branch
   (substituting one disjunct) is unsatisfiable. This closed **both** remaining
   `unit-resolution` steps (3 -> 1).
2. **De Morgan for `and`** (`andDeMorganEq`). MEASURED (`[dbg-rw0]`):
   `(and X Y) <=> (not (or (not X) (not Y)))`. The identity is PROPOSITIONAL, so it is
   checked STRUCTURALLY (`sexpEq`) — no solver, no term analysis.
3. **Unfolding a PROVEN `intro-def` definition** (`eqUpToDefs` + a pre-pass). MEASURED
   (`[dbg-rw1]`): the last trusted `rewrite` is
   `(= (>= (result - ite(...)) 0) (>= (result - z3name!1) 0))`, i.e. unfolding the name
   `z3name!1` into its definition. SOUND: a name is unfolded ONLY when its definition was
   proven by an `intro-def` step (fresh name + two `ite` definition clauses).

**Ordering matters:** the checked `rewrite` comes BEFORE its `intro-def` (step #1), so the
definition map is filled by a PRE-PASS over `intro-def` steps — and only for those whose
structural check passed. Otherwise the unfolding would rely on an unverified definition
(unsound).

Negative counterparts: a de Morgan rewrite with a SUBSTITUTED disjunct is rejected; and
`eqUpToDefs` in a context WITHOUT the definition refuses to unfold.

`premises bound: 2/3` is NOT a defect: `total` includes local `hypothesis` entries that are
removed by the `lemma` rule; `premises_unbound == 0`, which is exactly what `checksPass()`
requires.

### 23.23 Echelon 1 acceptance (5 gates)

Before Echelon 2, all new Echelon 1 code was put through destructive and formal
verification. Every number below is a real run on this machine.

**GATE 1: RAM disk + parallel pool (no loss of precision).**
`make lia-diff`: 2.55 s (1 worker) -> **0.86 s** (6 workers) = **2.96x**;
`make audits`: 33.41 s -> **24.21 s** = **1.38x**. Verdicts are IDENTICAL
(lia-diff: 86 checked / 14 honest unknown / 0 divergences in both modes;
audits: 6 proven / 9 refuted / 1 SKIP). Temp files moved to `/dev/shm`; the pool
is a `ThreadPoolExecutor` with deterministic output order.

**GATE 2: Lean 4 theorems for the NEW rules.** `formal/FarkasSoundness.lean`
**+8 theorems** (**50 theorems across 8 files, 0 errors, 0 sorry**):
`int_eq_zero_iff_le_ge` (antisymmetryZero), `int_eq_iff_sub_zero`
(eqTransferZero), `int_not_eq_iff_disj` (negAlternatives), `ite_flip_cond_eq`
(iteSwapEq), `or_congruence_right` (orCongruence), `and_de_morgan_iff`
(andDeMorganEq), `lemma_raa_discharge` (verifyLemma), `case_split_2x2_unsat`
(SOUNDNESS of checkFalseBySplitting).

**GATE 3: allocator fault injection (0 leaks).** `builtin_lia.checkUnsatFallible`
via `checkAllAllocationFailures` — OK. `verifyProof` — a custom `fail_index`
sweep 0..400 (the proof walk is INFALLIBLE by design, so the stock harness does
not apply): **0 leaks, no panic**. Three real defects were found and fixed:
`checkUnsat` SWALLOWED OOM (body moved to a propagating `checkUnsatFallible`,
production wrapper keeps the conservative `.unknown`); `verifyProof` reported
"unparseable" instead of OOM (now propagates); `newCtx` used
`arena.create(...) catch unreachable`, which PANICS under OOM (the `defs` field
became a value allocated from the arena).

**GATE 4: mutation bombardment of the new code.** `src/verifier/builtin_lia.zig`
added as the 15th target file. A `--max 60 --seed 7` run exposed survivors; a
TARGETED test was added for each: `proof_check.zig:288 [false->true]`
(sexpEqNum list-vs-atom), `:1174 [false->true]` (verifyLemma rejects a non-step),
`:1397 [false->true]` (negAlternatives refuses non-linear terms),
`:2140 [or->and]` (complementary pair of NON-comparisons -> `.unsat`).

**GATE 5: extended differential control.** `make lia-diff`: **40 -> 100 systems**,
generator extended (up to 4 variables, coefficients up to 11, EQUALITIES as a
pair of non-strict inequalities, STRICT inequalities via the integer shift).
Result: **0 divergences from Z3** (86 checked, 14 honest unknown).
`canfail --check-anchors`: **76 literal anchors applicable** (after fixing the
`lia-soundness` anchor for `checkUnsatFallible`).

**GATE 4 — HONEST OUTCOME (correction).** The canonical `make mutate`
(`--max 40 --seed 7 --jobs 4 --require-solver`) scored **82.5 % (33/40)** after
the 15th target file was added — NOT the previous 95.0 %. Reason: the stratified
sample changed (15 files instead of 14), so it hit DIFFERENT sites. Seven
survivors: `proof_check.zig:1920 [>=->>]`, `model_extract.zig:245 [>=->>]` and
`:66 [and->or]` (all NEW Echelon 1 code), `proof_check.zig:288 [false->true]`
(defensive branch), `z3_bridge.zig:52 [true->false]` (killer-thread flag),
`kimg_writer.zig:209 [true->false]` (pre-existing), and
`proof_check.zig:1184 [!=->==]` (DIAGNOSTIC-ONLY: inverts a debug print, does
not change any verdict).

**HONEST STATUS: the >= 95 % target is NOT met.** This is an open acceptance
item, not a pass: 4 of 7 survivors live in the NEW Echelon 1 code and need
targeted tests in a follow-up iteration.

**GATE 4 — ATTEMPT TO CLOSE SURVIVORS: honest outcome.** Four targeted tests
were added and each kill was VERIFIED BY APPLYING the mutation manually:
`proof_check.zig:288 [false->true]` (sexpEqNum: lists of DIFFERENT length are not
equal -> 1 test fails), `:1920 [>=->>]` (asLeZero handles `(not (or Y))` with a
SINGLE disjunct), `model_extract.zig:66 [and->or]` (renderValue must NOT fold
`(- 42 7)` because it contains a space), `model_extract.zig:245 [>=->>]`
(truncated input -> `Malformed`, no out-of-bounds read). The diagnostic line
`proof_check.zig:1184 [!=->==]` is now EXCLUDED from mutation (same class as
defect #106: a debug print cannot change a verdict).

**CORRECTION to §23.23: the score did NOT rise — it is 80.0 % (32/40)**, and the
survivors CHANGED (`1937`, `z3_bridge:52`, `model_extract:295`,
`kimg_writer:209`, `2070`, `1203`, `2084`; only the last two of the previous set
remained).

**KEY FINDING (a tool defect requiring its own iteration):** `sample_stratified`
with a fixed `seed` RE-DRAWS sites after any edit, because the site set changed.
So ">= 95 %" is a MOVING target: closing some sites PUSHES others into the
sample. Scores are not comparable across runs until sampling is STABLE (e.g. a
canonical site ordering plus a deterministic fraction), or until new files are
mutated over the FULL site set without sampling.

**HONEST STATUS: the >= 95 % target is NOT met (80.0 %).** Open acceptance item.
The added tests are real improvements (4 mutants killed, verified by applying the
mutations), but systematically closing ALL defensive branches of the new code
requires a stable sample — otherwise the task is not well-posed.

**DEFECT #124 FIXED: the mutator is no longer a "moving target".**
`sample_stratified(seed=7)` used ONE sequential PRNG over files in sorted order,
so any change in the number of sites in one file shifted the PRNG state and
PULLED DIFFERENT sites in ALL other files. The "score" was therefore not
comparable across runs: 95.0 % -> 82.5 % -> 80.0 % on the same code and seed was
not a regression but a re-draw.

**Fix (Option A).** Each site now gets an INDEPENDENT score
`sha256(seed:file:line_text:mutation:dup)`; sites within a file are taken in that
order. The key is the line TEXT, not the line number, so inserting a line
anywhere no longer shifts the sample.

**PROVEN BY EXPERIMENT:** removing 187 sites in `proof_check.zig` did NOT change
the sample in the other 14 files — **27 of 27 matched**. Two consecutive runs are
identical. A `--full-file <path>` flag was added (Option B: all sites of a file,
no sampling).

**GATE 4: 85.0 % (34/40), and the sample is now REPRODUCIBLE.** Additionally
killed (each verified by APPLYING the mutation): `builtin_lia.zig:223 [!=->==]`,
`proof_check.zig:1308 [or->and]`, `:1920 [>=->>]`, `:288 [false->true]`,
`model_extract.zig:66 [and->or]`, `:245 [>=->>]`.

**HONEST STATUS: 85.0 % (34/40); the >= 95 % target is NOT met.** Six reproducible
survivors remain (stable thanks to #124): `blake3_simd8.zig:154 [<=-<]`,
`kimg_writer.zig:212 [false->true]`, `proof_check.zig:1892 [false->true]`
(allocator catch in `pushLin`), `z3_bridge.zig:283 [true->false]`
(killer-thread stop flag), `proof_check.zig:1259 [false->true]`, `:49
[false->true]`. Three of them are defensive branches on allocator/thread failure
paths requiring a `FailingAllocator` test or a timeout scenario — next iteration.

**TEST B DONE: metamorphic invariance of LIA.** A unit test
`METAMORPHIC: invariance under row reversal, variable renaming and x3 scaling`
was added to `src/verifier/builtin_lia.zig`: **20 systems** (10 UNSAT, 10 SAT) x
**3 transformations** = **60 invariance checks**, all passing. Rationale:
(a) row reversal — Fourier-Motzkin eliminates variables in order, so a different
order takes DIFFERENT paths; (b) renaming (`x <-> y`) changes the elimination
order; (c) scaling by `k = 3 > 0` (`sum + c <= 0` <=> `3*sum + 3*c <= 0`) also
exercises gcd reduction. The verdict must be STRICTLY the same; the test also
checks the base verdict against the EXPECTED one (10 unsat / 10 sat), otherwise
"invariance" would degenerate into "always unknown".

**GATE 4 CONTROL MEASUREMENT (dual score) — MEASURED.** Canonical
`make mutate` (`--max 40 --seed 7 --jobs 6 --require-solver`): raw **90.0 %**
(36/40 killed), effective (excluding 3 proven-equivalent) **97.3 %** (36/37).

**A BUG IN MY OWN REPORT was found and fixed:** the first version printed
`effective 10.8 % (1/37)` — the formula divided SURVIVORS by the denominator
instead of KILLED. The correct formula (DO-178C / IEEE) is
`Score = Killed / (Total - Equivalent)`; after the fix the measurement is
**97.3 %**.

**The fourth survivor turned out NOT to be equivalent** — and that is a real
finding: `proof_check.zig:1267 [false->true]` is
`const h = t.items[0].atom orelse return false;` in `isNegOfTerm`. The mutant
`orelse return true` produces a FALSE "this is minus Y" when the head of the
term is a nested list rather than an atom. A targeted test was added
(`isNegOfTerm(((a) b), b) == false` plus 3 controls), **verified by APPLYING the
mutation: 1 test fails**. Tests 327/327.

**HONEST GATE 4 OUTCOME:** raw 90.0 % (36/40) — the formal >= 95 % raw threshold
is NOT met; the effective score (excluding 3 proven-equivalent) is 97.3 %. The
remaining survivors `blake3_simd8.zig:154`, `kimg_writer.zig:212`,
`z3_bridge.zig:283` are proven equivalent (§81.18).

**TEST A DONE: adversarial proof-checker fuzzer (30/30).** A new CLI subcommand
**`kernc check-proof <smt2> <proof>`** verifies a FINISHED proof WITHOUT a solver.
The "confirmed" criterion was tightened to
`checksPass() and proof_concludes_false and trusted_steps == 0`.

The fuzzer `tools/proof_tamper_check.py` (target `make proof-tamper`) takes the
**real** Z3 proof for `musl abs.c` (51 steps, `trusted: 0 | holes: 0`; fixtures in
`tests/fixtures/`, 2998 bytes) and applies **30 point tamperings**, one per run:
comparison (`(<= ` -> `(< `), arithmetic (`(+ ` -> `(- `, `(* ` -> `(+ `,
`(- 1)` -> `(- 2)`), connective (`(or ` -> `(and `), step reference (`@xN` ->
`@x9`), name (`z3name!1` -> `z3name!9`), constant (`0))` -> `1))`).

**MEASURED RESULT:** positive control rc=0; **30 tamperings, 30 rejected,
0 accepted**. So `trusted: 0` on `abs.c` is NOT a coincidence: the proof cannot
be silently falsified in any of 30 places. Registered as `proof-tamper` = CHECK
with canfail case `proof-tamper-soundness`.

**HONEST: my own process defect (verifier race).** While verifying mutant kills I
**started a second instance of the script while the first was running**. Both
edited the SAME file (`model_extract.zig`) restoring it from their own copy — the
race **left two mutations in the tree** (`if (n != 0)` and `if (n == 3)` instead
of `== 0` / `!= 3`). Found by `git diff` showing PRODUCTION lines I never
changed; fixed by restoring from git and re-applying the test block only.
`git diff` now confirms no production line is changed. Lesson: tree-patching
scripts must hold a lock (the mutator has `acquire_lock`) and run in a SINGLE
instance — the same class as defect #116.

**TEST C DONE: full mutation bombardment (`--full-file`, no sampling).**
`src/verifier/model_extract.zig`: **75 sites, 75 killed = 100.0 %** (was 62/75 =
82.7 %). `src/verifier/builtin_lia.zig`: 17 sites, 15 killed = 88.2 % (was 14/17),
2 survivors (`:80 [false->true]` — the local `merged` flag in `combine`; killing it
needs a system where LOSING a merged term changes the verdict, and no such
scenario has been constructed — NOT proven equivalent, simply uncovered; `:189
[false->true]` — `if (acc > 0) return false;` in `satisfies`, which only matters
when a found point violates the system, and the current corpus never produces such
candidates).

**TESTS A, B and C are now COMPLETE.** Echelon 1 has been verified at the level
the DoD demands: adversarially (30/30), metamorphically (60/60) and by full
mutation (100 % on the new module).

**TEST A FULLY CLOSED: native in-memory fuzzer.** Besides the external fuzzer
(`tools/proof_tamper_check.py` + `make proof-tamper`) there is now a **native Zig
test** running all 30 tamperings **in memory** (no process spawning): the fixture
`src/verifier/abs_proof_fixture.zig` is GENERATED from `tests/fixtures/` (the real
Z3 proof for `musl abs.c`, 51 steps) together with a 30-entry tamper array
`(needle, repl, occ)`. The test checks the POSITIVE CONTROL (`checksPass()` +
`proof_concludes_false` + `trusted_steps == 0` + exactly **51 steps**), then
applies 30 tamperings and requires EVERY one to be rejected. **Measured:**
343/343 tests; 30 applied, 30 rejected.

**TEST C FULLY CLOSED: both new modules at 100 %.**
`model_extract.zig`: 75 sites, **75 killed = 100.0 %** (was 62/75).
`builtin_lia.zig`: 17 sites, **17 killed = 100.0 %** (was 14/17). The last two
survivors, previously reported as "not covered", were killed by targeted tests:
`:80 [false->true]` (the `merged` flag in `combine` — the system
`x <= 0, x + y >= 0, y <= -1` stops being refuted once the `y` term is lost:
`.unsat` -> `.unknown`) and `:189 [false->true]` (`if (acc > 0) return false;` in
`satisfies` — for `x + y = 3` no candidate point satisfies it, so the correct code
returns an honest `.unknown` while the mutant returns a FALSE `.sat`).

**GATE 4 CLOSED: raw score 100.0 % (40/40).** Proven-equivalent sites are now
excluded from the POOL at `collect()` time (like string literals and
`KERN_DEBUG`), not merely subtracted from the denominator: such mutants are
indistinguishable by ANY test (§81.18), so they only polluted the raw score. After
exclusion the pool holds **772 sites and 0 equivalent**. Raw 100.0 % (40/40),
effective 100.0 % (40/40), **zero survivors**. The raw >= 95 % threshold is MET.

**ECHELON 2, ITEM 12: BIT-ROT / DATA-POISONING GUARD.**
`tools/bitrot_chaos_check.py` (target `make bitrot-chaos`) takes a REAL `.kimg`
(7979 bytes, 34 objects), verifies integrity (positive control), then flips ONE
bit at 30 different positions, requiring a refusal on each.

**MEASURED: 30 injections, 26 detected, 4 do not affect the data, 0 REAL GAPS.**
The "does not affect the data" class is VERIFIED, not assumed: for every
undetected injection the SHA-256 of the CONCATENATED decompressed objects is
compared — if it matches, the data is provably unchanged (deflate alignment
bits); if not, it is reported as a GAP.

**DEFECT #127 (found by this chaos test and FIXED).** The first version of
`check-integrity` computed the Merkle root over the STORED digests and never
recomputed them from the data. MEASURED: **11 of 20** injections went undetected.
Fix: `check-integrity` now recomputes each object's digest from its bytes (for
compressed objects, AFTER decompression — i.e. what the consumer sees).
Detections rose 9 -> 26 of 30.

**The remaining hole was a SECOND finding of the same class:** byte 3445 turned
out to be corruption of an object NAME (`abs_kern_absBroken.smt2` ->
`abs_kern_ab?Broken.smt2`). The name lives in the data region but is covered by
NEITHER the object digest (computed over CONTENT) NOR the Merkle root (computed
over digests). Consequence: the content is intact but the object becomes
UNREACHABLE by path (`cat` -> `FileNotFound`) — a silent loss of access.

**MITIGATION (in code, with an explicit caveat):** names must be PRINTABLE ASCII;
a non-printable byte is rejected with precise diagnostics. This is NOT a complete
fix — a flip to another printable character still slips through. The complete fix
is to include the name region in the Merkle root (a container format change),
left as an open item. After the mitigation: **0 REAL GAPS**.

**ECHELON 2, ITEM 11: TAMPER-EVIDENT MERKLE AUDIT CHAIN** (`src/next/catalog.zig`,
the Belnap verdict journal in SQLite). Each record is chained to the previous one:
`hash_i = BLAKE3(prev_hash_i || record_i)`; the schema is
`audit_chain(seq INTEGER PRIMARY KEY AUTOINCREMENT, record, prev_hash, hash)`, and
the first record uses 64 zeros as `prev_hash` (fixed 64-hex length makes the
concatenation unambiguous). API: `appendAudit(record)` and
`verifyAudit() -> AuditStatus` (`.ok: N` | `.broken: {seq, why}`). Two attack
classes are caught: RECORD SUBSTITUTION (recomputed hash mismatch) and RECORD
DELETION (a gap in the monotonic `seq`). Three tests pass in
`zig build test-next` (42/42): positive control (3 records -> `.ok: 3`),
substitution of `seq=2` -> `.broken{seq:2}`, deletion of `seq=2` ->
`.broken{seq:3}`. The negative tests FAIL if detection breaks, so they prove
detection, not merely functionality.

**ECHELON 2 ACCEPTANCE: two defects found by the check.**

**DEFECT #129: `kernc verify` returned `rc = 0` with a REFUTED contract.** The
command counted `proven`/`refuted`/`no_contract` and printed a summary, but the
exit code was ALWAYS 0 — so CI, a pre-commit hook or a script saw "success" even
when a contract was refuted (the gate is formally closed, but there is no signal).
FIXED: `refuted > 0 -> rc = 1`. Found while implementing Item 9 (PCC), whose
acceptance criterion requires `rc != 0` on a forged certificate.

**DEFECT #130: the `canfail` case for `pcc-check` was VACUOUS.** The first version
broke `ProofVerdict.checksPass()` (always true). MEASURED with
`canfail --only pcc-check`: **`VACUOUS 1`** — the fault was injected but the target
stayed GREEN, because the forged certificate was caught by `proof_concludes_false`,
not by `checksPass()`. FIXED: the case now breaks exactly the PCC acceptance
condition (`if (v.checksPass() and v.proof_concludes_false and v.trusted_steps == 0)`
-> `if (true)`); afterwards **non-vacuous 1 | vacuous 0**.

**LESSON.** A vacuous case is a FALSE proof: it looks like a check but verifies
nothing. That is why "every new CHECK must be run through `canfail --only`" is not
a formality — checking the four new targets (`pcc-check`, `bitrot-chaos`,
`tree-lock`, `binary-audit`) exposed exactly such a case.

### 23.26 Defect #133 — FOURTH VACUOUS CASE (process)

`canfail --only simplify-check` reported **`VACUOUS 1`**: the fault was injected but the
target stayed GREEN. Verified MANUALLY (applied the patch, ran the target) — the
harness was RIGHT.

**Root cause (my own misunderstanding of my function):** `_smt_sat` maps SAT -> `True`,
UNSAT -> `False`, otherwise `None`. The first case patched the FIRST condition to
`if False:`, so SAT fell through and returned **`None` (unknown)** instead of `False`:
live branches were NOT pruned, `n_changes == 0`, the function was skipped and the target
stayed green. The correct fault is `return True # SAT` -> `return False # BREAK`, which
makes ALL branches look dead and prunes LIVE ones.

**Verified manually:** with the correct patch the target **turns red (`rc=2`)** and the
independent runtime cross-check prints **58 mismatches** (`clean(25): 26 != 0`). After
fixing the case: **`1 non-vacuous | 0 vacuous`**.

**Conclusion (fourth case in a row):** a vacuous case is not a rarity but a SYSTEMIC
hazard, detectable ONLY by mandatory `canfail --only <target>` with `0 vacuous`.

### 23.27 Echelon 4, Item 21 — ARRAY BOUNDS (`arr[i]` -> `0 <= i < len`)

`--xray` gained a **`[BOUNDS PATH]`** detector. The array length is supplied by
`# @kern:len(arr) = N`; the safety obligation `0 <= i < N` is emitted **WITH path
conditions** (guards `if i < 0 ... if i >= N ...` make the function safe — and this is
**proved**, not assumed). Without the directive an honest
**`[BOUNDS] ... length UNKNOWN, bounds NOT checked`** is printed.

**MEASURED** on `examples/array_bounds.py`: `get_unsafe` -> `[BOUNDS PATH]` with
counterexample `i = -1` (bounds `0..7`); `get_safe` (guarded) -> **no finding**;
`get_unknown_len` -> honest `[BOUNDS]`.

**Defect #134 (mine):** the first version also accused `get_safe` — statements AFTER
`if` were processed with the ORIGINAL (empty) path, so `if i < 0: return 0` was lost.
Fixed by narrowing the path with `NOT cond` when the THEN block always exits.
A **false positive** is more dangerous than a miss: it discredits the tool.

**Defect #135:** `@kern:len` directives were read file-wide, so a second function
declaring the same variable overwrote the first (`0..3` instead of `0..7`). Fixed:
lengths are read from the comment block immediately preceding `def`.

`make xray-check` now asserts three things (unsafe accused; safe NOT accused; unknown
length reported honestly). canfail case `bounds-check`: breaking the detector turns the
target red. MEASURED: `1 non-vacuous, 0 vacuous`.

### 23.28 Echelon 4, Item 20 — TOTAL LOOP CORRECTNESS (Floyd-Hoare)

`--loops <file>`: `# @kern:invariant` + `# @kern:decreases` -> FOUR obligations in Z3
(QF_LIA, no CHC): Init, Consecution, Post, Termination. The step is modelled
**sequentially** (assignments applied in program order).

**MEASURED** on `examples/loops.py`: `count_up` -> PASS; `count_up_bad_inv` ->
FAIL LOOP INVARIANT VIOLATED (`n = 0, i = 0` and `n = 0, i = -1`);
`count_up_no_terminate` -> FAIL NON-TERMINATING LOOP (`n = 1, i = 0`).
Summary: `PASS 1 | FAIL 5 | SKIP 0`.

**Defect #137 (soundness-critical):** `_smt_counterexample` returned `None` for BOTH
`UNSAT` and **`N`** (solver gave up), so any UNRESOLVED formula silently counted as
PROVEN. Also `_subst` wrapped ATOMS in parentheses, producing `(0)` — invalid SMT-LIB —
so Z3 could not parse the formula at all -> `N` -> PASS. Fixed: three-valued
`_smt_verdict` -> `("sat", ce) | ("unsat", None) | ("unknown", reason)`; `unknown` is
printed as `[UNKNOWN]` and is NEVER counted as proof.

**Defect #138:** only parameters were declared — loop locals (`i`) and `result` were
undeclared -> Z3 error -> `N` -> false PASS. Fixed: all state variables are declared;
`result` in the `post` obligation.

**Defect #139:** `_subst` wrapped an already-complete s-expression -> `((+ i 1))` ->

---

## §24. Session B: PRESETS (Item 26), ANTI-ARBITRAGE (Item 27), PROOF-TAMPER 40/40

### 24.1 Step 0 — the adversarial fuzzer now covers THREE theories

Was: 30 tampers on `abs.c` (QF_LIA) only. Now: **30 + 5 + 5 = 40** tampers across
three independent theories — `abs.c` (51 steps), the path sanitizer `QF_S`
(39 steps), and the `IEEE-754` NaN model (56 steps). The proof fixtures are
committed (`tests/fixtures/qfs_proof.txt`, `ieee754_proof.txt`).

Soundness proven on one theory says nothing about another, so the fuzzer must
cover all three.

ANTI-VACUUM: if fewer tampers are generated than requested (e.g. the proof lacks
the needed forms), the target **turns red** — previously it would have passed
silently. MEASURED: `tampers: 40 | accepted: 0`, rc=0.

### 24.2 Item 26 — one-word presets + `--spec-gaps`

Flags: `--presets <file>`, `--spec-gaps`. Target `make presets-check`.

| Preset | Obligation |
|:--|:--|
| `non_negative` | `result >= 0` |
| `percentage` | `0 <= result <= 100` |
| `bounded(lo, hi)` | `lo <= result <= hi` (bounds may be expressions) |
| `idempotent` | `body(body(x)) == body(x)` |
| `monotonic` | `x1 <= x2 => body(x1) <= body(x2)` |
| `no_arbitrage` / `conservation` (Item 27) | `body(a1) + body(a2) >= body(a1 + a2)` |

SINGLE COMPOSITION MECHANISM: `_instantiate_body(body_smt, param, expr)`
substitutes an arbitrary SMT expression for a parameter inside the SYMBOLIC BODY.
Three separate implementations (`idempotent`, `monotonic`, `no_arbitrage`) would
drift apart and disagree on the same code.

MEASURED on `examples/presets_demo.py`: 4 PROVEN with `trusted: 0 | holes: 0`
(`non_negative`, `bounded`, `idempotent`, `monotonic`), 3 REFUTED (`percentage`
returns 102 for x=51; `monotonic` has a backward step; `non_negative` fails for a
negative input), `0 unknown`, and 8 `[SPEC GAP]` findings with the flag.

`--spec-gaps` (MacFarlane) is a SEPARATE diagnostic mode: it prints `[SPEC GAP]`
for one-sided postconditions and for an unconstrained negative parameter domain;
it does not touch a normal run without the flag.

### 24.3 Idempotence — the PATH-WISE formulation (measured, not guessed)

Substituting a branch VALUE back into the body produces a NESTED `ite`; Z3 then
finishes with `ite`-axiom steps the checker cannot machine-check (MEASURED:
`clamp_idem` — 8 trusted steps, `[UNKNOWN]`). Splitting the body into PATHS
removes the nesting: the obligations become constant (`(< 0 0)`) and fold away.

### 24.4 Five new SOUND checker rules (triad: code + negative test + Lean)

| Rule | Soundness | Where it came from |
|:--|:--|:--|
| `constCmpEval` — evaluate a CONSTANT comparison | arithmetic on concrete numbers | dump: `(rewrite (= (<= 0 100) true))` |
| `constIteEq` — fold `ite` with a constant condition | with a known condition `ite` is branch selection | dump: `(rewrite (= (ite false 100 0) 0))` |
| reflexivity `(= A A) = true` | holds for any term | dump: `(rewrite (= (= x x) true))` |
| `linTautEq` — LINEAR TAUTOLOGY `(= E true|false)` | UNSAT of the negation is decided by the built-in Fourier–Motzkin (gate `make lia-diff`) | dump: `(rewrite (= $x50 true))` for `3a1+3a2 >= 3(a1+a2)` |
| `pushLin` DROPS ZERO COEFFICIENTS | a zero-coefficient term does not change the inequality | MEASURED: without it a constraint that became constant (`1 <= 0`) was not recognised as INCONSISTENT → `unknown` → the step stayed trusted |

Each rule ships with a positive and a NEGATIVE test in `proof_check.zig` (the
negatives: "a non-tautology is NOT accepted", "a non-constant condition is NOT
folded") and a theorem in `formal/FarkasSoundness.lean` (`0 sorry`).

### 24.5 Item 27 — financial anti-arbitrage

MEASURED on `examples/arbitrage_demo.py`:
```
[FAIL] fee_threshold:    no_arbitrage REFUTED — a1 = 100, a2 = 1
[FAIL] fee_floor_capped: no_arbitrage REFUTED — a2 = 1, a1 = 99
[PASS] fee_proportional: no_arbitrage PROVEN (trusted: 0 | holes: 0)
```
A threshold fee and a floor-plus-cap fee let a client SPLIT a payment and pay
less — the classic rounding leak. The linear (proportional) fee is subadditive
and is proven.

### 24.6 REGRESSION found by the regression pass: `make audits` was RED

The criterion `refuted > 0 -> rc = 1` (introduced with Item 9) breaks
`make audits`: the golden corpus **by design** contains refuted MUTATIONS (that is
its purpose — prove the original, refute the mutation). MEASURED: `make audits`
→ rc=2.

FIXED in `kernc verify` — the alarm criterion is now a **DISAGREEMENT between the
solver verdict and the DECLARED status** of a claim:
* declared `proven` but the formula is refuted → ALARM;
* declared `refuted` but the formula is proven → ALARM;
* no declared status (`N`) → the verdict is informational;
* a forged certificate (`[PCC REJECTED]`) → ALARM **always**.

The declared status in the corpus is the **MEASURED** solver verdict on THAT
formula (no heuristics by function name or reason text: MEASURED that
`divCeilBuggy` first failed an overflow obligation while its main formula is also
refuted, and `alignForwardAdd` is the opposite).

ANTI-VACUUM: the corpus must contain BOTH classes of formulas (otherwise the check
degenerates).

MEASURED after the fix: `make audits` rc=0, `L4 verify: assertions checked`,

### 24.8 Item 25 — polyglot on 7 languages + Sorbet-style range inference

Added `.ts`, `.js`, `.go` (previously `.py`, `.zig`, `.c`, `.rs`).

| Language | Header form | Notes |
|:--|:--|:--|
| TypeScript | `function name(x: Type): Ret {` (also `export function`) | types `int32`/`uint32`/`Percent` |
| JavaScript | `function name(x) {` | type absent → **model `int`** |
| Go | `func name(x int32) int32 {`, `func (r T) name(...)` | `if cond {` without parens, `;` optional, `a, b int` |

**EXPLICIT ASSUMPTION (recorded both in code and here):** JS numbers are float64
while KERN checks an INTEGER model. So for JS without a type annotation the tool
uses the model `int` (i32) — that is a tool convention, not a fact about the

---

## §25. Session C: Echelon 5 CLOSED (Items 28, 29, 30, 31)

### 25.1 Item 28 — double-spend race (`@kern:no_double_spend`)

Both transactions check a SNAPSHOT of the balance while the deduction runs against
the current value, so the total can go negative. The check verifies the main
consequence: the function must not return a negative balance for non-negative
inputs (path-wise decomposition).

MEASURED on `examples/double_spend_demo.py`: `withdraw_race` REFUTED
(`balance = 1, a1 = 1, a2 = 1, result = -1`); `withdraw_serial_safe` PROVEN over
all 3 paths with `trusted: 0 | holes: 0`.

### 25.2 Item 29 — FFI bridge (`@kern:calls_i32` / `@kern:calls_u32`)

A value from an arbitrary-precision language crosses into a C-ABI type of FINITE
width; leaving the range means truncation, invisible to Python/JS.

MEASURED on `examples/ffi_bridge_demo.py`: `to_c_u32_unsafe` REFUTED (`x = 4295`);
`to_c_u32_safe` and `to_c_i32_safe` PROVEN over 3 paths each (`trusted: 0`).

### 25.3 Item 30 — RLS policies (`--verify-sql`) — PARTIAL, honestly

The access PREDICATE is checked (`result == 1` only when
`(row_tenant == req_tenant ∨ is_public == 1) ∧ is_deleted == 0`); SQL boolean flags
are constrained to `{0,1}` (otherwise `is_deleted = -1` would look like a bypass —
MEASURED).

```
[FAIL] rls_buggy: RLS POLICY BYPASS FOUND (path 1) —
       is_public = 0, is_deleted = 1, req_tenant = 0, row_tenant = 0
[UNKNOWN] rls_safe: 2 paths NOT re-checked by the proof checker (NOT counted)
```

**HONEST:** the bypass IS caught with an exact counterexample (the security-critical
direction). For the SAFE policy Z3 returns UNSAT but the checker leaves 4
atom-heavy steps (`def-axiom`/`rewrite` over introduced atoms), so `[UNKNOWN]` is
printed instead of PASS. Three alternative formulations were measured — same class.
This is a NAMED checker boundary, not a masked green tick.

### 25.4 Item 31 — pricing matrices (`--verify-pricing`)

Two formal properties: COMPLETENESS (a negative price is an "unhandled input"
sentinel = a gap) and DISJOINTNESS (rules with DIFFERENT prices must not overlap;
conditions are taken AS WRITTEN, otherwise the overlap would vanish by
construction).

```
[FAIL] price_gap: PRICING GAP (unhandled input, path 3) — age = 18
[FAIL] price_conflict: PRICING CONFLICT (Belnap B): rules 1 and 2 overlap — tier = 2
[PASS] price_safe: PROVEN COMPLETE & DISJOINT (rules 2, paths 3, trusted: 0 | holes: 0)
```

### 25.5 SIX new SOUND checker rules (all derived from dumps, not guesses)

| Rule | Soundness | Dump it was derived from |
|:--|:--|:--|
| `commEq` | `+`/`*` are commutative | `(* x 1000000)` vs `(* 1000000 x)` |
| `deMorganEq` + `polarEq` | de Morgan BOTH ways + double negation | `(not (and A B))` vs `(or (not A) (not B))` |
| `linTaut` | truth of a linear comparison (Fourier–Motzkin) | `(= E true)` |
| `andTautEq` | `¬(A ∧ true) ≡ ¬A` with `true` PROVEN by the solver | `(<= x x)` |
| `andEquivEq` | `¬A ≡ ¬B` when `A ↔ B` (both implications) | `0≤10⁶x≤4294967295` ≡ `0≤x≤4294` |
| `_range_obligations` (path-wise) | paths cover the domain ⟹ all inputs covered | 2–3 trusted steps on the whole body |

Each rule: positive + NEGATIVE test in `proof_check.zig` (**+4 tests: 346/354**)
and theorems in `formal/FarkasSoundness.lean` (**+7 theorems: 67 in the file,
8/8 files, 0 errors, 0 sorry**).

### 25.6 Defect #144 — the SIXTH VACUOUS CASE (process)

`canfail --only ffi-bridge-check` reported **VACUOUS 1**: my patch targeted
`_smt_verdict`, while presets go through **`_prove_checked`**, so the target stayed
green. FIXED: anchor `return ("sat", ce, None)` (unique to `_prove_checked`).
After the fix: `1 non-vacuous, 0 vacuous`.

### 25.7 Gates and regressions

| Check | Result |
|:--|:--|
| `make double-spend-check` / `ffi-bridge-check` / `pricing-matrix-check` | `[OK]` |
| `make sql-policy-check` | `[OK]` (bypass caught; safe status is an honest UNKNOWN) |
| `canfail --only` ×4 | **1 non-vacuous, 0 vacuous** each |

---

## §26. Session D: Echelon 6 — AI SECURITY SHIELD (Items 32–35)

### 26.0 First, the Point 30 tail is closed (Defect #145)

The RLS invariant used to be checked as ONE compound formula `¬((A ∨ B) ∧ C)`,
which made Z3 introduce Tseitin atoms (4 trusted steps → `[UNKNOWN]`). FIXED: the
invariant is a CONJUNCTION, so a violation is searched COMPONENT-WISE (de Morgan):
two separate violations — "deleted row" and "foreign non-public tenant". SAT of
either equals SAT of the whole violation (sound and complete).

MEASURED: `[PASS] rls_safe: PROVEN (tenant isolation on all 4 paths, trusted: 0 |
holes: 0)`, 0 unknown. The `or UNKNOWN` allowance was REMOVED from
`tools/sql_policy_check.sh` — the gate now requires a strict PROVEN and 0 unknown.
Lean: `invariant_componentwise_check` (proved by hand, core tactics only).

### 26.1 Item 32 — anti-cheat (`--anti-cheat` + `--import-lock`)

An AST scanner catches five classes of Reward Hacking plus slopsquatting:
always-true `__eq__`; `sys.exit`/`os._exit` inside tested code; an `except: pass`
swallowing an `assert`; `unittest.mock` in production; test-case overfitting
(`if x == 42 and y == 17`); and imports outside the `--import-lock` allowlist.

MEASURED: `examples/anti_cheat_demo.py` → **5/5**; clean
`examples/presets_demo.py` with `examples/import_allowlist.json` → `[OK] clean`.

**Defect in my own code (found by running):** the name resolver only understood
`Attribute(Name)` and missed `unittest.mock.patch` (nested attribute) → 4/5.
Fixed with `_dotted()` → 5/5.

### 26.2 Item 33 — MCP poisoning (`--audit-mcp` + `--mcp-lock`)

Prompt injections in `description` (`ignore previous`, `~/.ssh`, `<system>`, …),
invisible Unicode (U+200B–200F, U+202A–202E, U+2060–2064, U+E0000–E007F, U+FEFF)
and RUG-PULL: a SHA-256 per tool (canonical JSON) compared against
`mcp.lock.json`.

MEASURED: a clean schema creates the lock and passes; after editing a description
→ `MCP RUG-PULL DETECTED`; a poisoned schema → `PROMPT INJECTION` (3 patterns) +
`INVISIBLE UNICODE U+200B`.

### 26.3 Item 34 — non-interference (`@kern:secret`, 2-Safety)

Goguen–Meseguer self-composition: two copies with the SAME public input and
DIFFERENT secrets must produce the SAME output. Obligation:
`body[s := s1] ≠ body[s := s2]` → SAT means a leak.

MEASURED on `examples/noninterference_demo.py`: `check_pin_leaky` → `SECRET LEAK`
(`pin__1 = 0, pin__2 = 1, guess = 0`); `constant_time_op` → `PROVEN
NON-INTERFERENT (trusted: 0 | holes: 0)`.

### 26.4 DEFECT #146 (found by this item): the counterexample was HIDDEN

The model validator (`src/verifier/model_extract.zig`) could not evaluate `=`
between **BOOLEAN sub-formulas** (`(= (= p g) (= p2 g))` — two Bools, not Ints):
`asInt` failed, and the code declared the model `SPURIOUS MODEL`, **hiding a valid
counterexample** (it printed "spurious model" instead of `[COUNTEREXAMPLE]`).

FIXED twice: (a) `=` compares boolean sub-formulas as booleans; (b) "cannot
evaluate this form" (`Malformed`/`Overflow`) is now `unsupported`, NOT `spurious` —
`spurious` is reserved for an **evaluated false**.

### 26.5 Item 35 — agent-swarm arbitration in the Belnap lattice

A NATIVE test in `src/next/truth.zig` over `Bit.join` (the core's real lattice):
`JOIN_K(T,F) = B` (Gates CLOSED, allowance = 0); absorption (100 votes of T never
overwrite B); `JOIN_K(T,T) = T` (Gates OPEN, allowance = 1); `JOIN_K(B,F) = B`
(a vote of F does not lift the conflict). `zig build test-next`: **45/45**.
`make belnap-swarm-check` requires rc=0 and the test's presence; the canfail case
breaks `Bit.join` (`n = false`) → the target turns red.

### 26.6 Gates and regressions of Session D

| Check | Result |
|:--|:--|
| `make anti-cheat-check` / `mcp-audit-check` / `noninterference-check` / `belnap-swarm-check` | `[OK]` |
| `canfail --only` ×4 | **1 non-vacuous, 0 vacuous** each |
| `make sql-policy-check` | `[OK]` — STRICT PROVEN, no allowances |
| `registry.py` | **129 targets, 106/106 CHECK** |
| test catalog | **400**, in sync |
| Lean 4 | 8/8 files, `FarkasSoundness` — **75 theorems**, 0 errors, 0 sorry |
| `zig build test-next` | 45/45 |

| `registry.py` | **125 targets, 102/102 CHECK** |
| test catalog | **399**, in sync |
| `zig build test` | 346/354 (8 skipped), 0 failed |
| `./formal/check.sh` | 8/8 files, 0 errors, 0 sorry |

language.

**HONEST REFUSAL instead of a guess:** the type `number` (float64) does **not**
get the `int` range — it goes to SKIP with an explicit reason: `float64
(IEEE-754) outside the integer model; use @kern:float`.

**SORBET-STYLE:** the range is inferred from the MEANING of the type name, with
no manual `@kern:requires`: `Percent` → 0..100, `PositiveInt`/`pos_int` → `> 0`,
`NonNegativeInt`/`nat` → `>= 0`, `int32`/`uint32`/`int64`/`uint64` → machine
bounds.

**No `;` (Go/JS/TS):** `_normalize_clike(keep_newlines=True)` keeps newlines as
statement separators and `_join_if_blocks` merges `if`/`else` with the following
statement, so the form matches what the SHARED C-like code parses. The mirror
`_eval_body_concrete` (concrete model replay) uses the SAME `_clike_stmts`
function — otherwise it would replay different code.

MEASURED on `examples/polyglot_demo.{ts,js,go}` (target `make polyglot-7-check`):
4 PROVEN (`clampTs`, `pctTs`, `clampJs`, `clampGo`), 3 REFUTED (`badTs`/`badGo`
int32 overflow with counterexample, `badJs` contract violated with
`[RUNTIME CONFIRMED]`), 1 honest SKIP (`number` → float64), 0 UNRESOLVED.

TRIAD: +3 Lean theorems (`percent_implies_nonneg`, `positive_implies_nonneg`,
`int32_overflow_at_min`); canfail case `polyglot-7-check` (we break the type
table) — **1 non-vacuous, 0 vacuous**.

`DISAGREEMENTS WITH DECLARED STATUS 0`, `formulas measured: 17 | proven 9 | refuted 7`.

### 24.7 Regressions (all clean)

| Check | Result |
|:--|:--|
| `abs.c` | `trusted steps 0`, `trusted: 0` |
| `make proof-tamper` | **40/40 rejected** |
| `make lia-diff` | **0 disagreements** with Z3 |
| `./formal/check.sh` | 8/8 files, **0 errors, 0 sorry** |
| `make audits` / `pcc-check` / `kimg-deflate` | rc=0 |
| `zig build test` | 342/350 (8 skipped), 0 failed |
| `canfail --only presets-check` / `arbitrage-check` / `audits` | **1 non-vacuous, 0 vacuous** each |
| `canfail --check-anchors` | 91 anchors applicable |
| `registry.py` | 121 targets, **98/98 CHECK** |
| test catalog | 395, in sync |


Formulation (sound and complete for the fragment): for every pair of paths
`(p, q)` check `P_p ∧ P_q[V_p] ∧ (V_q[V_p] ≠ V_p)`. The paths cover the domain,
so enumerating pairs covers ALL inputs.

MEASURED: `idempotent — paths 9 | PASS 9 | FAIL 0 | UNKNOWN 0` → `trusted: 0`.

unparseable -> `N`. SMT-LIB notation is PREFIX, so substituting a full s-expression
needs NO parentheses. Fixed.

**IMPORTANT:** #137-#139 lived in SHARED helpers, so they affected EVERY check
(including Item 21). After the fix Items 17 and 21 were re-verified. Defect class:
**an SMT parse error was silently reported as a proof**.

---

## §27. Session E: Echelon 7 (Items 36–39)

### 27.1 Item 36 — Action/FinOps Firewall (`--verify-action`)

An agent's JSON call is checked BEFORE execution: `allow` must hold, `forbid` must
not. Verdicts (Belnap + RFC 9110): safe call → **T (1,0), e=1, 200 OK**
(`trusted: 0`); over budget → **F (0,1), 422** with a counterexample; `allow`
and `forbid` both true → **B (1,1), 409 Conflict**. MEASURED: `action_ok` → 200;
`action_over` → 422; `action_conflict` (forbid `amount >= 40`) → 409.

### 27.2 Item 37 — document contradictions (`--verify-doc`)

Clauses form a conjunction. MEASURED: a consistent document → `[PASS] DOCUMENT
CONSISTENT`; a contradictory one (sla<=4, review>=6, sla>=review) →
`CONFLICT B(1,1)` plus the **minimal core** (greedy deletion):
`[clause_1, clause_2, clause_3]`.

### 27.3 Item 38 — RLVR reward oracle (`--rlvr-reward`)

MEASURED: good → `R=+1.0 [VERIFIED]` (trusted: 0, anti-cheat clean); buggy →
`R=-1.0 [REFUTED]` + counterexample; cheater (`sys.exit`) → `R=-2.0`
`[REWARD HACKING PENALTY]`. `unknown` NEVER yields +1.0 (zero false rewards).

### 27.4 Item 39 — bug hunt (`tools/bug_hunter.py`)

`--xray` over real stdlib files plus a **CONTROL** on known findings. MEASURED:
control `xray_demo.py` → **3 findings** (the detector works); stdlib: 8 files,
`checked 83 / 135 (skipped 52)` with reasons, **0 findings** — honestly.

### 27.5 Defect #147: TWO VACUOUS CASES (process)

`canfail --only action-firewall-check` / `rag-conflict-check` → **VACUOUS 1**
each: the gates grepped `HTTP 422` / `CONFLICT B(1,1)`, which REMAIN when
`[FAIL]` becomes `[INFO]`. FIXED: grep the **verdict line** `[FAIL] ...` → both
became `1 non-vacuous, 0 vacuous`.

### 27.6 Gates

| Check | Result |
|:--|:--|
| `make action-firewall-check` / `rag-conflict-check` / `rlvr-oracle-check` / `bug-hunt-check` | `[OK]` |
| `canfail --only` ×4 | **1 non-vacuous, 0 vacuous** each |
| `registry.py` | **133 targets, 110/110 CHECK** |
| anchors | **104** |
| Lean 4 | 8/8 files, `FarkasSoundness` — **81 theorems** |
| test catalog | 400 |

---

## §28. Session F-1: Item 40 (Echelon 8) — PARTIAL: 3 of 5

### 28.1 40B — Interactive proof canvas (`--html`)

`tools/canvas_template.html` + `cmd_html`: Tangle-style parameter sliders
recompute the active branch live (a small linear-SMT evaluator), the Belnap B4
square is coloured by the verdict, plus a passport (CC, path count).
MEASURED: 7019 bytes, 7 functions, **0 external references** (the gate greps
`https?://`).

### 28.2 40C — MCP 5 -> 8 tools

Added `kern_xray_code`, `kern_verify_action`, `kern_rlvr_reward` — **thin
wrappers over the CLI** (no duplicated logic). MEASURED: `make mcp-selftest` —
**ALL PASSED** (tools/list = 8, DEAD BRANCH, 422 firewall, RLVR −2.0).

**A limitation of `--xray` found en route:** sequential `if ...: return`
statements do NOT narrow the path for later statements — DEAD BRANCH is detected
only inside if/elif chains. This is NAMED, not hidden: the MCP test uses a chain
and the limitation is recorded here.

### 28.3 40D — fuzz corpus + `install.sh`

`tests/fuzz_corpus/`: 8 files (truncated S-expression, empty/garbage SMT,
`deep_nest` with 400 parens, `torn.kimg`, empty `.kimg`, junk proof). Each is run
**TWICE**. MEASURED: `files 8 | crashes 0 | nondeterministic 0`.
`install.sh --check`: size + sha256 + binary launch.

### 28.4 Defect #148 (the 9th vacuous case)

`canfail --only fuzz-corpus-check` -> **VACUOUS 1**: the gate grepped `0 паник`,
which REMAINS when `[OK]` becomes `[FAIL]`. FIXED: grep `[OK] 0 паник` ->
`1 non-vacuous, 0 vacuous`.

### 28.5 NOT DONE (honestly)

| Sub-item | Status | What is required |
|:--|:--|:--|
| **40A WASM** (`zig build wasm`) | ❌ NOT done | a new `src/wasm_api.zig` (export `kern_wasm_belnap_join` / `_admission_valid`), a `wasm32-freestanding` step in build.zig, a magic-bytes `<512 KB` gate. `proof_check.zig` cannot be pulled into freestanding (it spawns z3) |
| **40B `kernc grep`** | ❌ NOT done | a `src/main.zig` subcommand: verifyMerkleRoot + object walk with `decompressObject`, printing `name:line:match` |

Reason: the session budget went into bringing 40B/40C/40D to 100% (including
catching two vacuous cases). These two are CORE Zig work, not shop-window work.


---

## §29. Echelon 8, item 40 (final): 40A WASM + 40B `kernc grep`

### 29.1 Item 40A — KERN core in WebAssembly (`src/wasm_api.zig`, `make wasm-check`)

Only syscall-free parts of the core are exported: the Belnap lattice (`JOIN_K`),
the gate allowance (e=1 for `T` only), the 64-bit `AdmissionCode`, and the
built-in Fourier-Motzkin solver (`builtin_lia.zig`).

Memory: `var wasm_buf: [256 * 1024]u8` + `FixedBufferAllocator`; the allocator
state is kept GLOBALLY — a local variable would dangle (caught by the compiler:
`expected '*T', found '*const T'`).

What is NOT in WASM and why: `proof_check.zig` imports `z3_bridge.zig` (spawns an
external `z3` process); `wasm32-freestanding` has no syscalls at all. This is a
NAMED boundary: in a browser you get integrity checks and the LIA solver, but
NOT re-checking of the Z3 proof.

MEASURED (`make wasm-check`): build rc=0; WASM magic valid; No-Bloat gate
**8,144 bytes** (< 512 KB); all 4 exports present; SEMANTICS verified natively
(`zig test`) -> **All 40 tests passed**. Checking only module bytes would be
vacuous: a module can have the right size and still not work.

### 29.2 Item 40B — `kernc grep <pattern> <image.kimg>` (`make kimg-grep-check`)

Order is STRICT: header + `verifyMerkleRoot` first, search second. Searching a
corrupted image is BLOCKED (`rc=2`) — otherwise output would mislead. Compressed
objects are decompressed (`decompressObject` re-checks the digest). Both object
NAMES and content lines are searched.

MEASURED on `audits/real_code_corpus.kimg` (34 objects): pattern present ->
**rc=0**, 6 hits; absent -> **rc=1**; one byte flipped -> **rc=2**
(`MerkleRootMismatch`).

### 29.3 Defects #149, #150, #151

| # | What | Found by | Fix |
|:--|:--|:--|:--|
| #149 | `--xray`: consecutive `if…: return` did not narrow the path | MCP test (if/elif chains worked, consecutive did not) | narrow path by `NOT cond` in `_walk_branches` |
| #150 | `wasm-check` case failed: file missing from FAULTABLE | `canfail --only wasm-check` | file added to `FAULTABLE` |
| #151 | `kimg-grep-check` case was VACUOUS: the gate never rebuilt the binary, so patching `exit(1)`->`exit(0)` in `src/main.zig` had no effect | `canfail --only kimg-grep-check` | `zig build` before checks in `kimg_grep_check.sh` |

After the fixes both gates report **1 non-vacuous, 0 vacuous**.

### 29.4 Result: all 40 plan items closed

8 echelons, 40 items, zero tails.

---

## §30. BLAKE3 SIMD-8 and `align(32)`: measured, caveat removed

Bench: `src/bench_simd8.zig` (`make bench-simd8`), `ReleaseFast`, 64 MB,
4 KiB objects, 8 lanes of `@Vector(8,u32)`, warm-up excluded.

| Config | Runs | Median |
|:--|:--|--:|
| with `align(32)` | 2.40 / 2.48 / 2.42 GB/s | **~2.42 GB/s** |
| without `align(32)` | 2.46 / 2.20 / 2.41 GB/s | **~2.41 GB/s** |

Honest conclusion: on this pattern `align(32)` gives **no measurable gain**
(difference within noise). The change is harmless, but it must not be sold as
speed-up. The "~90 GB/s" figure in README is RAW addressing (no hashing) —
a different operation, not a contradiction.

### 31. Items 3 and 4 — bug-hunter trophies (8/8) and full-file sweep of every verifier

**Item 3 — four battle scenarios** (`bug_hunter.py --trophies`, target `make bug-hunt-check`, requires 8/8):

| Scenario | Positive | Negative |
|:--|:--|:--|
| 1. Bloch `binary_search` | buggy `(low+high)/2` in **QF_BV** → `[FAIL]`, counterexample `result = #xc0000000` (**negative**) | safe `low+(high-low)/2` in `Int` → **PROVEN** |
| 2. PR audit (`--diff-equiv`) | regression → **`[DIVERGED]`** + counterexample | correct refactor → **`[EQUIVALENT]`** |
| 3. DeFi `@kern:no_arbitrage` | threshold/floor fee → **REFUTED** (splitting pays less) | proportional fee → **PROVEN, trusted: 0** |
| 4. Python stdlib | — | **checked 83/135, findings 0** (no false positives) |

**Honest limitation (MEASURED):** the Bloch bug is **invisible in the `Int` theory** — the
intermediate sum cannot overflow there, so refutation requires machine semantics
(`@kern:bitvec32` → QF_BV). Stated in the scenario, not hidden.

**Item 4 — `--full-file` on every verifier:** `z3_bridge` **22/22**, `noninterference` **9/9**,
`cegis` **2/2**, `unsat_core` **4/4** — all **100.0 %**. Five new tests, each verified by
**applying** the mutation (`killed.store(true)→false` gives `.ToolError` instead of `.Timeout`;
`KillCtx.init(true)` gives `.Unknown`; `code != 0 → == 0` gives `.Unknown` instead of
`.ToolError`; `or→and` loses the cmov taint; `false→true` makes `earlyExitEqual` ignore length).
A stub `tests/fixtures/hang_solver.sh` (hangs, ignoring argv) plus `timeout_ms = 150` proves
the killer thread terminates the process in under 3 s.

**Process defect (mine):** while checking a mutation by hand, an interrupted command left
`z3_bridge.zig` **empty** (787 deleted lines). Restored from git; the tests were re-added and
**committed before the next experiment**. Rule: never mutate the working tree with `sed`
without a commit — use a copy or an immediate `git checkout`.

### 32. Item D6 — full sweep of every CHECK target (closed)

```
TOTAL: non-vacuous 138 | VACUOUS 0 | HARNESS FALSE POSITIVES 0 | CASE ERRORS 0 | skipped 0
```

First end-to-end run after all Echelon 5–8 and Session F-1/F-2 changes; previously new
targets were only checked with `--only`, so a regression in an OLD target could have gone
unnoticed. Runtime ≈ 19 min (heavy `evidence` cases take 2–4 min each).

**Found by the sweep — Defect #157:** `write_atomic` did not preserve the file mode, so
after an interrupted run **29** `tools/*_check.sh` scripts were left as `100644` instead of
`100755` (lost `+x`). Fixed: `stat` → `chmod` on the tmp file → `os.replace`, with a test.

**Baselines re-checked:** `proof-tamper` 40 attacks / 0 accepted · `abs.c` `trusted: 0 |
holes: 0` · Lean 4 — 8 files, 0 errors, 0 `sorry`.

### 33. Full population mutation sweep — 1225/1225 = 100.0 %

```
MUTATION SCORE (raw):       100.0%  (1225/1225 killed)
EFFECTIVE SCORE:            100.0%  (1225/1225 killed)
REAL_SECONDS=1383  (23 min, --jobs 6, all 20 files, NO sampling)
```

Closes the **last technical debt**: the canonical gate sampled 40 of 1225 sites (3.3 %)
and `--full-file` covered 16 modules (244 sites). Now the **whole population** is checked
and **zero** mutants survive.

Speed-ups used: `/dev/shm` slots with a warm `.zig-cache`, two-stage fail-fast
(`zig test --test-filter <module>` = 2 s, full suite = 10 s only if the mutant survived),
`--jobs 6`, and `KERN_MUTATE_FAST=1` (fewer stress iterations, no tests disabled).

**Defect found by the run itself:** at 252/1225 `/dev/shm` was 62 % full (slots grew to
1.4–1.7 GB each); a further `ENOSPC` would have been counted as `KILLED_COMPILE` — a
**false** kill. Fixed by `_trim_slot_cache()` (every 25 mutants, drop the whole cache above
800 MB; never `.zig-cache/o` alone — generated `sqlite3_bridge.zig` lives there).
**MEASURED: 41 trims, `ENOSPC` = 0.**

### 34. Field-testing `--xray` on third-party code (6 adapters)

Added (all sound): `self.x`/`this.x` as symbolic `obj__field`; let-inlining of local
assignments (`total = a + b`, `x += 1`) into conditions and divisors; module-level integer
constants; `min/max/abs` translated to exact linear `ite`; recursive `--xray <dir>` with
service-directory skipping; and a **length invariant** for the real pattern
`if len(x) != K: x = ...[:K]`.

The length invariant was found on real code: without it `urllib/request.py: ip2num`
produced a **false** `[BOUNDS PATH]` (`len(parts) = 0`) although both branches guarantee K.

**Measured on Python stdlib (9 files):** `checked 211 / 413` functions (51 %). Of the
34 reported lines, 33 are `[BOUNDS] “length unknown”` — i.e. honest refusals, not findings.

**Limitations (measured):** Zig bodies are not parsed (`checked 0 / 11`, honest SKIP);
C-like `if` conditions are checked without path narrowing; Python has no type information
(a string attribute can be treated as `Int`); aggregation attribution needs re-checking for
nested calls. Baselines after the changes: `make contracts` unchanged (11 proven / 4
violated / 0 unresolved / 2 vacuous), `make edge-cases` OK.

**Defect #158 (found by the field scan):** in Python `%` is BOTH modulo and **string
formatting**. `'<urlopen error %s>' % self.reason` was parsed as `mod`, producing a
**false** `[CRASH PATH]` in `urllib/error.py` and `http/cookiejar.py`. Fixed with
`_is_str_expr()` (string literal / f-string / `%`-formatting / `.format()`) applied in
**all three** divisor-collection sites; such `%` now yields an honest SKIP.

**Before/after on the same 9 stdlib files:** 201/413 (49 %) with **1 false finding** ->
**211/413 (51 %) with 0 findings**. Coverage grew AND false accusations were eliminated —
for a security tool that matters more than any gain.

### 35. `--xray` on real Zig stdlib: 0 -> 80 functions

`parse_clike` *executes* the body; real std Zig uses `comptime assert(@typeInfo(T) …)`,
`@as`, `try`, so execution failed and `raw_body` stayed empty. For x-ray, execution is not
needed: `_clike_functions()` takes the body by brace balance and extracts `if (...)` without
executing anything; `cmd_xray` routes non-`.py` files there.

**Path narrowing is strict:** a constraint is added only for `return/break/continue` right
after the condition or for `else`; otherwise nothing ("unknown" is not "dead branch").

| Target | Before | After |
|:--|--:|--:|
| `std/math.zig` | 0 / 11 | **13 / 32** |
| `std/math/` (64 files) | 0 | **80 / 219** (139 skipped) |
| unreadable files | 63 | **0** |
| findings after fixes | 1 false | **0** |

Defects found by this run: **#159** (`else if` after `else if` produced a false DEAD BRANCH) —
narrowing restricted to `return`/`else`; **#160** (`REDUNDANT GUARD` for C-like produced a
false "always true" in `math/pow.zig`) — for C-like only `DEAD BRANCH` is reported.
Principle: for a security tool a **false accusation is worse than a miss**.

### 36. Third audit pass — defects found in the browser WASM code

Verified with real Node/WebAssembly and a mock DOM (not by eye).

**Defect #165 — `i64` needs BigInt (the widget did NOT work in a browser).**
`kern_wasm_lia_unsat2(…: i64)` and `kern_wasm_admission_valid(code: u64)` require `BigInt`;
passing Numbers throws `TypeError: Cannot convert -1 to a BigInt`. Fixed in three places;
proven by running the widget logic: `A=OK` (reachable) and `B=OK` (DEAD BRANCH, UNSAT).

**Defect #166 — the WASM wrapper returns `unknown` where the CLI returns `SAT`.**
`(-1,0,-5, 1,0,4)` i.e. `x >= -5 ∧ x <= -4` → WASM `0` (unknown), while
`LE -1:x -5 / LE 1:x 4` in the CLI → `SAT x=-5`. Return codes: **1 = UNSAT, 2 = SAT,
0 = unknown**. Not fixed (touching `builtin_lia` before a release is unsafe); the widget is
now three-valued: `1 → DEAD`, `2 → reachable`, `0 → UNKNOWN (B4: N, e=0; NOT proven)`.

Also checked: `chromium --headless --dump-dom` (rc=0, 0 JS errors), `node --check` for all
three script blocks, native WASM exports (JOIN_K(T,F)=B, ALLOW_CODE=1), `--audit-repo`
edge cases (symlink and `.min.js` are skipped), and the tree (`git status` clean, no leftovers).

### 37. Pre-release session 2026-10-19: full can-fail run, WASM kernel, evidence collector

**36.1 The 139-goal run and why the guard called it invalid.**

```
RESULT: non-vacuous 139 | VACUOUS 0 | harness false alarms 0 | case errors 0 | skipped 0   RC=0
[OK] tree clean: every patch rolled back
[guard] FILES CHANGED DURING THE RUN:
        - formal/KernAllMath.lean: bfb175a4fecf -> b8d944be3ab0
        - zig-out/bin/kernc:       a90cf0583a82 -> 372c7b2e56c2
```

Both files are **run products**, not inputs: `zig-out/bin/kernc` is rebuilt by the
harness itself at the end, and `KernAllMath.lean` had been snapshotted **mid-run**
(with `CANFAIL_PROBE` still appended). The guard was accusing the harness of doing
what the harness is designed to do — defect #173, fixed in the same session.

**36.2 WASM kernel — what is actually measured.**

```
kernc.wasm: 86 953 bytes; exports:
  kern_wasm_belnap_join, kern_wasm_belnap_allow, kern_wasm_admission_valid,
  kern_wasm_lia_unsat2, kern_wasm_verify_proof
test: valid proof -> 1 | forged proof -> 0 | proof without `false` -> 0
```

Honest scope: `proof_check.zig` only compiles for `wasm32-freestanding` after a lazy
`z3_bridge` import plus `dbgPrint()`/`dbgEnv()` shims — in Zig 0.17 `std.debug.print`
for freestanding pulls `std.Io.Threaded` → `posix.getrandom` and fails to build.

**36.3 #166 — false `unknown` inside WASM (found by tag, not by guessing).**
`pickVar` picked a variable with a **zero** coefficient, so Fourier–Motzkin never
progressed, `eliminated` hit `MAX_VARS`, and the WASM solver answered `unknown` where
the CLI answers `SAT`. After the fix: `lia S = 2`, `make lia-diff` — 0 mismatches,
`--full-file src/verifier/builtin_lia.zig` — 18/18.

**36.4 #155 — a forged DAG was accepted as a proof.** Renaming a step definition
(`@x147` → `@x9`, references untouched) produced `farkas 3 -> 0, trusted 0, rc=0`.
An unresolved `@xN` fell into `formulaOf() orelse .structural_only`, and
`.structural_only` does **not** increment `trusted_steps`, so `checksPass()` passed.
Fixed: a broken reference (with `stepexpr` built) is `.bad`. Verified: mutant → `rc=1`,
`abs.c` → `rc=0, trusted: 0`, core tests 401/401.

**36.5 #171 — `bench-semantic` / Merkle root.** `semantic_probe.zig` built the image by
hand and used the pre-#128 root formula → `MerkleRootMismatch`. Now it goes through
`sealImageRoot` (single source of truth); digest is stable across runs.

**36.6 #173 — the guard, fixed and proven with 6 scenarios.**

| Scenario | Expected | Measured |
|:--|:--|:--|
| clean baseline | `rc=0` | `rc=0` (114 files, no `zig-out/`) |
| second `--snapshot` without `--force` | `rc=2` | `rc=2` |
| `--verify` after rebuilding `kernc` | `rc=0` | `rc=0` (build products not in baseline) |
| dirty inputs at start | list + `rc=3` | `rc=3` |
| `--verify` after restore | `rc=0` | `rc=0` |
| tree after tests | clean | clean |

**36.7 Permanent protection.** `tools/injection_guard.py` (markers in `src/`,
`examples/`, `tools/*.py` except `canfail.py`/itself; empty `git status` for `src/`
and `tools/`; refuse while `canfail`/`mutate_zig`/`collect_evidence` is alive),
`tools/evidence_guard.py` (write-once snapshot, products excluded).
Full defect journal of the session: `docs/CAPABILITY_STATUS.md` §6d (#153–#173, 19 entries).

### 38. #176 and three spot-checks before the clean run

**38.1 Waiting by timeout is not completion.** The automation script waited for
the collector with `for i in $(seq 1 60); do pgrep … || break; sleep 10; done` —
10 minutes, while the full run takes ~20. The loop expired and was treated as
success, so files were edited, evidence committed and the attestation signed
**while the harness was patching sources**. The harness caught it by itself:
`[!] ХАРНЕСС ОСТАВИЛ ИЗМЕНЕНИЯ В ДЕРЕВЕ: docs/evidence/scorecard.json`,
`ВАКУУМНЫХ 1`, `RC=1`.

**Rule:** wait with `while kill -0 $PID` (or a completion marker in the log) and
**abort on timeout** — a timeout is never a success signal.

**38.2 Three spot-checks measured before the clean run.**

| Check | Method | Result |
|:--|:--|:--|
| WASM static-buffer leak | 10 000 consecutive `kern_wasm_lia_unsat2` calls in Node | 10 000/10 000 correct, heap 4.6 MB, no growth: `allocator()` re-initialises the `FixedBufferAllocator` on every call |
| MCP invalid JSON | `printf 'not-a-json\n…'` piped into the server | `-32700 parse error`, then the server keeps serving the next request |
| Constant-time digest compare | grep across 6 directories | **2 production sites** in `src/main.zig:786-787` (PCC certificate binding) used `std.mem.eql` → replaced with `std.crypto.timing_safe.eql([32]u8, …)`. The test-only simulator `dst_sim.zig` keeps plain compares |

**38.3 Ordering:** all edits, docs and `scorecard.json` are prepared and committed
**before** the collector starts; during the run the tree is untouched; afterwards
only fresh logs, then signature and attestation.

**38.4 Defect #177 — telemetry parser vs new mutator output.** The clean run
reported `telemetry FAIL 0/12` with `score=None`, while the mutator itself printed
**100.0 % (40/40)**. Root cause: `tools/measure_all_kern.py:195` expected
`MUTATION SCORE:` (colon right after the word), but after the dual-score change
the line is `MUTATION SCORE (raw): …`. The parser returned nothing, the whole
mutation block scored 0/12, the stand reported 88/100 and `RC=1`.
Fixed with `MUTATION SCORE[^:]*:\\s*([0-9.]+)%`; re-run: **100/100, RC=0**.

Same class as #166 and #175: **change an output format — check every consumer**.

---

### 40. Field audit of 14 industry repositories (#174 closed, #178–#184 fixed)

Run in `/tmp/kern-field-lab` (clones `--depth 1`, hooks disabled, third-party
trees untouched). Full report: `docs/FIELD_AUDIT_REPORT.md`.

**#174 — closed.** 52 names were defined twice in `tools/kern_contracts.py`
(2024 lines of dead code). Removed all shadowed copies **bottom-up by AST
(`52 -> 0`, −2003 lines)**; `dup_defs_guard` ratchet is now at **0**.
Root cause of the earlier crash was found: the file had **two**
`if __name__ == "__main__"` blocks (the middle one called `main()` before the
later half of the file was defined → `NameError: cmd_xray`), and the *early*
`cmd_xray` copy was **newer** than the live one, so C-like routing silently
did nothing.

**Scorecard before → after** (profile/`LICENSE*`/tests/Lean fixes, #181):

```
cmark-gfm 40 D -> 78 B    actions/toolkit 40 D -> 83 B    ripgrep 50 D -> 73 B
mcp/servers 50 D -> 85 A  python-sdk 68 C -> 85 A         ts-sdk 50 D -> 83 B
fastapi 64 C -> 81 B      fastmcp 56 C -> 75 B            click 58 C -> 83 B
flask 50 D -> 73 B        requests 52 C -> 70 B           tigerbeetle 54 D -> 84 B
zls 60 C -> 73 B          aesop (Lean 4) 42 D -> 73 B
```

**`[CRASH PATH]` before → after:** total **469 → 10** across 13 code
repositories. About 95 % of the original findings were false: slashes inside
`//` / `///` comments, string literals, JS regex literals, `ALL_CAPS` macros
and identifiers that were never inputs (#178). Additional fixes: Python
`assert` as a path guard + *loop-modified variable kill* (#179), Rust
`pub(crate) fn` / generics / `if cond {` (#180), balanced-paren `assert`
(#182), machine type ranges + let-inlining + `@kern:requires` as part of the
domain + divisor must depend on parameters (#183), and — **soundness** —
`_smt_sat` now delegates to the three-valued verdict instead of reading
`N` as SAT, with free names declared (#184).

Remaining 10 findings are listed with per-case verdicts in the report; the
rule is unchanged: **a false accusation is worse than a skip.**

---

### 41. B2: `[BOUNDS PATH]` / `[OVERFLOW PATH]` for C-like + retro-test on historical CVE fixes

**Why.** The 14-repository field run showed that in C the real defects are not
division by zero but a **negative index** (`buf[i-1]`) and a **size overflow**
before `malloc`. Both classes were added to `_xray_clike_file`.

| Class | Claimed when | Decision |
|:--|:--|:--|
| `[BOUNDS PATH]` | index is a difference and Z3 confirms `SAT(idx < 0)` on the path | one-sided sound: the counterexample is a concrete input |
| `[OVERFLOW PATH]` | size passed to `malloc/calloc/realloc/strbuf_grow/alloc` is a `+`/`*` and Z3 confirms `SAT(size > INT32_MAX)` | same |

Not claimed: a lone parameter index (`buf[i]`, range comes from the type), loop
locals, struct fields/`->`. Measured reason: without this, one function
(`autolink_delim` in cmark-gfm) produced **3 false accusations** because its
bound comes from `while (link_end > 0)` and loops are not modelled (defect #187).

Synthetic control: `buf[i-1]` → flag; the same under `if (i < 1) return 0;` →
silence; `malloc(len + 1)` → flag; under `if (len > 1000) return 0;` → silence.
(4/4 as expected.)

Retro-test on published `github/cmark-gfm` security fixes (file before/after):

| # | Fix | Vulnerability | Before | After | Verdict |
|:--|:--|:--|:--|:--|:--|
| A | `2cb4a20` | OOB read in `validate_protocol` (`data[-rewind - i]`) | **2 findings, incl. exactly that index** | 1 residual | **CAUGHT** |
| B | `4682993` | unsigned pointer overflow via `(ptrdiff_t)` cast | 0 | 0 | missed (cast outside subset) |
| C | `ac80f7b` | `uint16_t` counter wrap in `table.c` | 0 | 0 | missed (not an allocation size) |
| D | `198669d` | off-by-one `<=` → `<` in `inlines.c` | 0 | 0 | missed (comparison semantics) |

**Result: 1 of 4, zero false accusations on the fixed file** except one honest
residual on `data[-rewind - len - 1]`, which after the fix is guarded by
`if (len == (size_t)(max_rewind - rewind)) return true;` — a C cast we cannot
translate, so it stays "possible" instead of "proven".

**Honest scope.** What we can say today is narrow: *"here is an index that can
be negative / a size that can overflow, decided by Z3 on this path"*. This is
not a detector for every CVE class. Fixes B/C/D need cast handling, struct field
widths and comparison-semantics analysis — those are the concrete next steps.

---

### 42. `--full-scan`: one pass + honest theory auto-routing

Actually executed per file (7 languages): `--xray` (`[CRASH PATH]`,
`[DEAD BRANCH]`, `[BOUNDS PATH]`, `[OVERFLOW PATH]`), `--anti-cheat` (all `.py`),
and `--audit-mcp` when `server.json`/`mcp.json` exists (with `mcp.lock.json`).

Not executed, and why: `QF_S`, `IEEE-754`, `no_arbitrage`, `2-Safety`,
`--loops`, `--infer-requires`, `--heal`, `--gen-tests`, `--diff-equiv` need a
**contract** (`@kern:…`) or two files. On bare third-party code they would either
`SKIP` or — worse — invent a verdict. So `--full-scan` prints them as
`[AUTO-ROUTE] … applicable — needs contract (@kern:…), not evaluated` and keeps
them **separate from findings**.

Measured on our own tree (`--full-scan .`): 212 files / 383 functions (82
checked), 6 xray findings, 259 anti-cheat candidates, MCP: `server.json checked`
(8 tools, 0 findings), 5 theories applicable by routing.

Honest anti-cheat limit: the heuristic cannot tell a CLI script from "tested
code" — `sys.exit()` at the end of `main()` is normal, inside a tested function it
is cheating. Such hits are printed as **candidates for manual review**, with an
explicit caveat, not as verdicts.

---

### 43. CVE retro-test: sniper accuracy (defects #189–#191)

After §41 one false residual remained on the **fixed** file and three fixes were
missed. Three narrow causes were found and closed: C casts made guards
untranslatable (#189 → `_strip_c_casts()`); the upper bound / off-by-one was not
checked at all (#190 → `<=` against a length parameter plus indexing by the same
counter); and “pointer offset is negative” was trivially true for any `data[-k]`
(#191 → class 1 only when the offset contains a loop counter).

Re-measured: **A `2cb4a20` — 1 finding before (exactly `data[-rewind - i]`), 0
after** (sniper); B/C/D — 0/0, still missed, each with a named reason (fixed
sum-offset without a counter, struct-field width, no `buf[i]` in that function).
Synthetic control 6/6.

Native certificates (our checker, not Z3 trust): unguarded model →
`KERN-EQ2 : F` with `[MODEL VERIFIED]` counterexample `max_rewind=0, rewind=0,
len=1`; guarded model → `[PROOF VERIFIED] steps: 29 … trusted: 0 | holes: 0`.

---

### 44. Four of four historical CVE fixes, a real zls finding, and .js/.go runs

Retro-test on `cmark-gfm`: **4 / 4** (was 1 / 4). A — backward pointer offset
containing a loop counter (#191); B — cast covering only one term, remainder
unsigned (#192); C — field type taken from the file's own `struct`
(`uint16_t n_columns`, #193); D — `<=` against a capacity-like name (#194).
Each: 1 finding before the fix, **0 after**. C and D run at **file level**
because both functions have multi-line signatures and the per-function parser
never saw them — the measured reason they were missed.

Native certificates: A `F`+`[MODEL VERIFIED]` → `T` trusted 0 (29 steps);
C `n = 65535` → `T` trusted 0 (5 steps); D `n = cap` → `T` trusted 0 (21 steps);
zls `initFromTrigram` `len = 0` → `T` trusted 0 (13 steps). B has **no**
certificate: unsigned wrap needs bit-vectors, our Int model cannot express it.

Real finding: `zigtools/zls` `src/TrigramStore.zig:519` — `index_1 % len` with
`len: u32`, no guard → `[CRASH PATH] len == 0`.

Field runs: `expressjs/express` 7/21 functions → 0 findings; `axios/axios`
32/133 → 0; `gin-gonic/gin` 86/1375 → 0; `cli/cli pkg/cmd` exceeded the budget.
The first run produced **9 findings, all false**, traced to three defects:
reassigned locals treated as constants (#195), `x = x || K` not modelled (#196),
and `err != nil` compared in an Int model (#197). After the fixes: zero findings,
and the checked counts honestly dropped where pointer comparisons are now skipped.

`--full-scan` became a real engine (#198: the Python branch called a
non-existent `_xray_file`, so Python files silently produced 0): it now uses the
real `cmd_xray` and runs `--infer-requires` + `--gen-tests` on findings
(`[autopilot] contracts 1 · tests 4`).

---

### 45. CVE-B closed (`trusted: 0`), certificates under a gate, `cli/cli` measured

**CVE B (`4682993`, cmark-gfm).** The `ite` form (`off = ite (a>=b) (a-b) (a-b+M)`)
left `trusted: 3`: Z3 inlines `define-fun`, rewrites the comparison inside `ite` and
reorders the addends. The certificate is therefore written as a **case split**
(`a < b` → wrap; the fix's guard removes that case) — the way a human argues it.
Result: **25 steps, premises 2/2, `trusted: 0`, `holes: 0`**.

**Two sound checker rules** (both found from dumps, not guessed): n-ary sums in
`collectSum` (Z3 writes `(+ K a (* (- 1) b))`, the old code accepted only binary `+`)
and `cmpCanonEq` (`x ≥ y` ↔ `x − y ≥ 0` ↔ `¬(y − x > 0)`). Lean:
`lin_sum_rearrange`, `cmp_sub_zero_iff`, `not_le_iff_shift`, `le_zero_iff_neg_ge_zero`.

**Named boundary:** a comparison with an `ite` *inside* it is not canonicalised yet
(a non-linear subterm is not a sum), so CVE-B uses the case split. The unit test
asserts only what is implemented.

**Defect #199 — the certificates were dead files.** `audits/{cmark,zls,gpa}/*.smt2`
were verified by **no** gate at all (grep over `tools/` was empty), so a solver or
front-end regression would have silently invalidated the published table. Fixed:
`tools/audits_run.py::cert_section()` checks the expectation from the file name
(`*_guard` → proven, `*_unguarded` / `*_control` → refuted) and fails `make audits`.
Measured: **12 certificates, 0 mismatches**.

**`cli/cli` (Go):** sparse checkout of two packages (`pkg/search`, `internal/ghrepo`),
9 files → **12 / 82 functions checked, 0 findings**. A whole-repository scan does not
fit a bounded session, and claiming “0 across the repo” from a partial scan would be
false.

| Metric | Value |
|:--|:--|
| cmark-gfm CVEs with a `trusted: 0` certificate | **4 / 4** |
| Certificates under a gate | 12 (0 mismatches) |
| Lean 4 | **125 theorems / 8 files, 0 errors, 0 sorry** |

---

### 46. Re-checking the ZLS 0.17.0 finding: it was a false positive (#200)

**What was claimed.** Earlier the field report stated `--xray` had found a *real*
bug in `zigtools/zls` (`src/TrigramStore.zig`, `initFromTrigram`: `split.index_1 % len`).

**What the actual ZLS 0.17.0 source shows** (clone of `zigtools/zls`, `build.zig.zon`:
`minimum_zig_version = "0.17.0"`; tag `0.17.0` exists):

| Fact | Value |
|:--|:--|
| The division really is `% len` (`len: u32`) | line 526 |
| The only construction site of the filter | line 169: `if (trigrams.len > 0) {` |
| Capacity for a single trigram | `capacityForCount(1) = divCeil(105,100) + (2 & 1) = 2` |
| The other `CuckooFilter.init` call | a test, `element_count = 499` → `filter_size = 524` |

**Verdict: `len == 0` is unreachable — the finding was false.**

**Cause (defect class).** `--xray` treats `len` as a free parameter and does not model the
caller's invariant (`if (trigrams.len > 0)`): it has no inter-procedural reasoning.

**Fix (narrowing the rule, not explaining it away).** A **length-like** divisor (`len`,
`size`, `count`, `n`, `cap`, `capacity`, `length`) is no longer accused, because non-zero
length is the caller's contract. Measured after the fix: `src/TrigramStore.zig` →
`checked 1 / 13, findings 0`. The `audits/zls/init_from_trigram_*.smt2` pair stays as a
**model demonstration**, not as a finding in zigtools' code.

**Why this is the right call.** A false accusation is worse than a miss (#178/#183), and
telling a third-party project “you have a bug” without checking the caller is exactly what
skeptics criticise. The check was done on their real source, not on a model.

**Regressions after narrowing:** `xray-check` rc=0 · `contracts` rc=0 · `edge-cases` rc=0 ·
`formal/check.sh` 8/8 · `proof-tamper` 40/40.

---

### 47. Hunting on today's HEAD: 0 true, 14 false (#201)

The question was whether our C analyzer can find bugs in *today's* code (i.e. whether it is
usable for Bug Bounty or for sending PRs). Measured on fresh `--depth 1` clones:

| Target (HEAD) | Files | Functions checked | Findings |
|:--|--:|--:|--:|
| `github/cmark-gfm` `src/` | 48 | 74 / 296 | **0** |
| `github/cmark-gfm` `extensions/` | 14 | 11 / 47 | **0** |
| `libgit2/libgit2` `src/util` | 122 | 178 / 661 | **14** |

**All 14 were verified by hand and all 14 are false:**

| File | Claim | Actual code |
|:--|:--|:--|
| `tsort.c:175` | `stack_curr - 3` may be < 0 | above: `if (stack_curr < 2) return 1; else if (stack_curr == 2) … else` → `stack_curr >= 3` |
| `tsort.c:206` | `stack_curr - 2` / `-1` | every `merge` call is under `stack_curr == 2` or `stack_curr - 1` with `>= 3` |
| `win32/path_w32.c:638` | `len - 1` may be < 0 | `if (!len \|\| str[len - 1] != '\\') break;` — short-circuit on `!len` |
| `wildmatch.c` (7) | "branch UNREACHABLE" for `(= t_ch p_ch)` | it is a runtime comparison of two chars; conditions from ONE loop branch leaked into another |

**Cause (#201):** the C-like path has **no control-flow modelling** — no early `return`, no
`break` inside `while (1)`, no per-iteration state, no caller invariants. Both classes
(`[BOUNDS PATH]` on `base - k` and `[DEAD BRANCH]`) are therefore noisy on real code.

**Decision (honest labelling, not renaming):** the rules stay (they are needed for the
targeted classes #191–#194 that scored 4/4 on cmark-gfm), but the tool now prints the
boundary whenever it emits C-like findings: they are **candidates, not bugs** — verify by
hand. **No external reports are sent from them: 0 confirmed out of 14.**

---

### 48. Contract audit of real library functions + funnel (2026-10-20)
* Population: 595 functions from `click`, `requests`, `urllib3`, `werkzeug`, `jinja2`, `starlette`.
* Contract from the **docstring**; body copied **verbatim**; every `REFUTED` replayed by a **live call**.
* Funnel: 595 total → 120 without structural constructs → **7 accepted before (1.14 %) / 8 after (1.31 %)**.
  After the fixes the top blockers are `Attribute` calls **117**, `try` **39**, nested `def` **30**, `AnnAssign` **28**;
  `raise` (24) and bare `Expr` (26) were removed by the new adapters.
* Live results: `jinja2.tests.test_divisibleby(0, 0)` → **ZeroDivisionError** (matches `[FAIL]`); with
  `requires num != 0` → **PROVEN, steps 3, trusted: 0, holes: 0**. `werkzeug.http.is_byte_range_valid`
  refuted for `length=1, start=0, stop=2` and **exonerated** by its caller (`min(end, length)`).
* Confirmed defects in third-party code: **0**.
* Fixed in KERN: **#202** (false FAIL with empty `ensures`), **#203** (chained comparisons), `raise`-guard and
  opaque-`Expr` adapters; 3 new checks in `edge_cases_check.sh` (13/13 OK).
* Honest limits: the funnel grows little because **calls** cannot be modelled without real semantics;
  `trusted: 4` for `value % 2` is still open (`mod` axiomatics in the proof checker).

---

### 49. Symbolic abstraction: funnel 1.14 % -> 27.23 % (2026-10-20)
The contract parser no longer discards a function on an unknown construct — it abstracts it:
`AnnAssign` (`x: int = 5`), nested `def` (No-Op), `try/except` (body walked, exceptions not modelled),
`a, b = e1, e2` (component-wise), `len(x)` -> symbol `len__x` with axiom `(>= len__x 0)`,
`int(x)`/`bool(x)`, and **any other call -> `_havoc_k`** (fresh integer).

Measured on the same population of 595 functions: **7 accepted (1.14 %) -> 162 (27.23 %), x23**.
Remaining blockers: `None` literal 40, `for` 34, `list` 30, subscript 26, unsized unpack 22, `dict` 21.

Rule #4 (Live Replay as final judge): a `SAT` on a havoc model is **not** a violation unless the live
call confirms it; otherwise the tool prints `[!] SAT not confirmed by live call -> FALSE ALARM`
(verdict `UNCONFIRMED`, new counter `FALSE ALARMS`), where previously it printed `CONTRACT VIOLATED`.

Verified: `ann`/`nested`/`tr`/`tup` -> `PROVEN, steps 7, trusted: 0, holes: 0`; havoc case ->
false alarm, not an accusation; annotations no longer leak into nested `def`.
Limits: exceptions not modelled; havoc results cannot be proven; loops/lists/dicts/`None`/subscripts
still refused; `trusted: 4` for `value % 2` open (Euclid axiomatics for `div`/`mod`); QuixBugs not run.

---

### 50. `None` / `Optional` + non-terminal branch: funnel 34.96 % (2026-10-20)
* Accepted bodies among the same 595 functions: **162 (27.23 %) -> 208 (34.96 %)**.
* `None` is modelled by the sentinel `-4611686018427387904`; `x is None` -> `(= x SENT)`,
  `x is not None` -> `(distinct x SENT)` (added `Is`/`IsNot` to `CMP`). This is a modelling
  assumption, so havoc counterexamples still go through Live Replay (rule #4).
* A branch without `return` (`if c: y = 1`) is no longer terminal: execution continues with the
  remaining statements; only `raise`-branches stay terminal.
* Remaining blockers: `for` 39, `list` 34, subscript 30, `dict` 24, unsized unpack 24, `import` 21.
* Verified: both synthetic `Optional` cases -> `PROVEN` (`trusted: 2` and `trusted: 1`, `holes: 0`).

---

### 52. QuixBugs: honest baseline + defect #206 (havoc is not a divergence)

**Done:** for the first time the world benchmark `jkoppel/QuixBugs` was run
(40 tasks, each with a buggy and a correct version) through `--diff-equiv`
(`∃x: f_old(x) ≠ f_new(x)`, no contracts needed). Driver: `tools/quixbugs_check.py` (replaced the v1.3 script that only ran `ast.parse`).

| Outcome | Tasks |
|:--|--:|
| **DIVERGED** (bug proven) | **0** |
| EQUIVALENT | 0 |
| **UNKNOWN** (`_havoc_k` abstraction) | **5** |
| **SKIP** (outside the subset) | **35** |

**DEFECT #206** (found by this run, fixed): the first version reported
**5 "caught bugs"** and all five were **false**. Bodies contained `_havoc_k` —
a call replaced by an **unconstrained** variable (symbolic abstraction, #205).
Then `(distinct _havoc_2 _havoc_5)` is trivially SAT and the tool printed
`[DIVERGED]` — an accusation without grounds.

**Fix:** if either body contains `_havoc_`, the outcome is
`[UNKNOWN] … not provable` with `rc=2` (in `--diff-equiv` **and** `--pr-summary`);
`--simplify` stays fail-closed. The edge case is pinned in
`tools/edge_cases_check.sh`: `[OK] #206: call (havoc) -> UNKNOWN rc=2, no false DIVERGED`.

**Blocker breakdown (35 SKIP, by function):** `List` 8, `While` 6, `For` 6,
`Dict` 3, variable-length unpacking 3, `ImportFrom`/`Subscript`/empty literal 2+2+2,
`Import`/`DictComp`/`ListComp`/non-linear multiply/assignment-to-non-name 1 each.

**Honest conclusion:** QuixBugs is algorithms over **lists and loops**. Until the
front end models `list` (`select/store`, `QF_AX`), slices and `for/while`
(bounded unroll or invariants), the honest number of caught bugs is **0 of 40**.
Full report: `audits/QUIXBUGS_BASELINE.md`. Next work order:
`list`/slice (QF_AX) → `for`/`while` (bounded) → re-run QuixBugs.

---

### 53. Bounded AST unrolling + Live Replay: first honest QuixBugs catch

Added to the contract path (`tools/kern_contracts.py`):
`while`/`for range` → **K unrolled copies** (`KERN_UNROLL_K`, default 2);
**bounded inline of self-recursion** (K steps, then havoc); `import` as a No-Op;
`AugAssign` (`x op= e`) translated exactly.

**Soundness.** Unrolling is an **under-approximation** (CBMC/Kani style): it finds
counterexamples but never proves correctness. Therefore every SAT candidate in
`tools/quixbugs_check.py` goes through **Live Replay**: a real call to
`buggy_fn(**args)` and `correct_fn(**args)` (2 s timeout, recursion limit 300,
small-domain enumeration for unconstrained args). `DIVERGED` is reported **only**
when the runtime really diverges, otherwise `DISCARDED`.

| Outcome (40 pairs) | Tasks |
|:--|--:|
| **DIVERGED `[RUNTIME CONFIRMED]`** | **1** |
| DISCARDED | 4 |
| SKIP | 35 |

**Caught:** `gcd` at `a = 0, b = 1` — the buggy version recurses forever
(`RecursionError`), the correct one returns `1`. Confirmed by live execution of
both versions, not by the model.
**Discarded:** `depth_first_search` (25 inputs), `find_in_sorted` (25),
`mergesort` (5), `rpn_eval` (nested `def` cannot be loaded) — SAT in the model,
but the live call showed no divergence ⇒ not an accusation (#206 works).

**Side effect on demo contracts (and defect #207):** the first version counted
`make contracts` as proven **11 → 12** (a `while` function "proven" by
unrolling). **That was a false proof** (defect **#207**): UNSAT over K=2 steps
does not mean the loop finished — it may continue on step K+1 (CBMC/Kani require
an *unwinding assertion*).

Fixed: with `unrolled=True` the `PASS` verdict is **forbidden** —
`[SKIP] [UNBOUNDED] K-step unrolling does not exhaust the loop`
(a proof requires a `--loops` invariant). A SAT counterexample stays honest
(it names a concrete input).

After the fix: `make contracts` — proven **11** (as before unrolling), "outside
the subset" 2 (`sum_to_n` → `[UNBOUNDED] SKIP` instead of a false PASS).
Pinned in `tools/edge_cases_check.sh`:
`[OK] #207: loop after unrolling -> UNBOUNDED SKIP (no false PASS)`.

**Remaining blockers (SKIP, per function):** `List` 8, assignment to `arr[i]` 5,
`for` over non-range 4, variable-length unpacking 4, `Subscript` 3, `Dict` 3,
path without return 2, non-linear multiply 2, empty literal 2, one binary
operator, one `DictComp`.

Next honest step: **array model (`QF_AX`, `array_theory.zig`) plus element
assignment** — without it the “caught” count cannot grow. Report:
`audits/QUIXBUGS_BASELINE.md`.

---

### 55. Defect #208: honest `--xray` coverage counter + end of silent swallowing

**Root cause (found by reading code):** `cmd_xray` incremented `checked` BEFORE
walking the body, unconditionally. A function with zero SMT obligations (no `if`,
no divisor, no index) was reported as "checked", i.e. `checked N/M` mixed real
verification with mere reading. Additionally 37 `except Exception` blocks inside
`tools/kern_contracts.py` swallowed internal errors (class #198: nonexistent
`_xray_file`).

**Fix:** `_SMT_CALLS` is incremented in the single choke point `run_kernc()`
(all solver calls go through it); `cmd_xray` prints `SMT-verified K,
no obligations N`. 14 translation sites narrowed from
`except (Unsupported, NoReturn, Exception)` to `except (Unsupported, NoReturn)`.
`_replay_soft()` keeps expected exceptions silent but prints
`NameError/AttributeError/SyntaxError` to stderr.

**Measured:** `examples/xray_demo.py` 4/4 checked -> SMT-verified 4,
no obligations 0; a file with one obligation-free function -> SMT-verified 1,
no obligations 1. `make contracts` 11 proven / 4 refuted / 0 false alarms;
`canfail --only contracts|xray-check|edge-cases` -> 3/3 non-vacuous, 0 vacuous.

---

### 56. Defect #209: list domain in Live Replay -> QuixBugs 1 -> 3

`mergesort` and `find_in_sorted` reached the solver and produced SAT candidates,
but were discarded: `_confirm()` enumerated only ints (`0,1,2,4,8`), so
`mergesort(0)` raised `TypeError: object of type 'int' has no len()` in BOTH
versions. Added a sequence domain (`arr|xs|lst|list|seq|items|nums|data|values`)
plus a `TypeError` fallback and `copy.deepcopy` per call. Soundness unchanged:
`DIVERGED` is declared only after a live call of both versions.

**Measured:** DIVERGED 1 -> 3, DISCARDED 4 -> 2, SKIP 35 (unchanged).
New bugs: `mergesort([1])`, `find_in_sorted([1], 2)`, `gcd(0, 1)` — all
`RecursionError` vs correct behaviour.

**Still open:** 35 SKIP blocked by `List/Subscript/for/Dict/unpacking` (needs
`QF_AX` in `parse_file`); Euclid axiom for `div/mod` in `proof_check.zig` NOT
implemented (reproduction gives `trusted: 6`).

---

### 57. Defect #210: `not-or-elim` in SIGNED form -> trusted 6 -> 4

Dump obtained by calling `./zig-out/bin/kernc prove <file.smt2>` DIRECTLY
(bypassing the Python wrapper, which swallowed the debug stream; without `z3` in
`PATH` the direct run only printed `[!] z3 unavailable`).

Six trusted steps were: 4 `rewrite` of Tseitin atoms and 2 `not-or-elim` of the
form `src=(not (or (= r 1) (= r 0))) concl=(not (= r 0))`. `verifyNotOrElim`
only accepted disjuncts that were themselves negations; `¬(A∨B) ⊨ ¬B` is the
same De Morgan law, so a second sound branch `asNot(concl) == disj` was added.

**Measured:** trusted **6 -> 4**, bool steps 17 -> 19, **reference `abs.c` stays
trusted: 0** (no regression). Lean: +3 theorems (125 -> 128), rc=0.

**Remaining 4 `rewrite`** are Tseitin-atom definitions (`def-axiom` clauses);
verifying them needs an atom-to-clause map and a biconditional proof — NOT done
in this iteration.

---

### 58. Defect #211: two rules from the `value % 2 == 0` dump -> trusted 4 -> 2

The dump showed these were NOT let-bindings (those expanded correctly):
`(= (ite (= (mod value 2) 0) 1 0) (ite (<= (mod value 2) 0) 1 0))` and
`(= (= result T) (and (<= result T) (>= result T)))`. The first holds only
because `0 <= mod x k` (Euclid axiom); the second is order antisymmetry.

Implemented soundly without calling the solver: `eqAntisymEq` (any terms) and
`eqZeroIteEq`, where `m >= 0` follows FROM THE SHAPE (`mod` with a positive
integer constant) — otherwise the step stays trusted, since `m = -1` would make
the identity false.

**Measured:** trusted **4 -> 2** (linear rewrites 17 -> 19); reference `abs.c`
stays `trusted: 0`; `make contracts` 11 proven / 4 refuted / 0 false alarms;
Lean **128 -> 131** theorems, 0 sorry.

**Remaining 2:** `(<= result T)` vs `(<= (+ result (* (- 1) T)) 0)` where `T`
contains `ite` — a linear-form comparison with an OPAQUE subterm; `parseLin`
rejects `ite`, so `normCmp` does not fire. Treating the `ite` subterm as an atom
would be sound, but is NOT implemented.

---

### 59. Bit tricks from the talk: measure BEFORE optimising + 3 theorems

| Measurement | Value |
|:--|--:|
| `kernc` startup only (21 MB binary) | **9 ms** |
| `kernc check-proof` (4 556 B proof, 81 steps) | **9–10 ms** |
| ⇒ read + tokenise + parse + verify 81 steps | **≤ 1 ms** |

**Measured conclusion:** the tokenizer is NOT the bottleneck for typical proofs
(3–5 KB). A 2× faster scanner saves ≈0.5 ms of 9–10 ms (≈5 %), so the
`@Vector(16,u8)+@ctz` scanner was **not** wired into the S-expression parser in
this iteration. The trick is relevant for large proofs (up to 623 KB were
observed in `audits/`) and must be measured there instead of assumed.

**Formally proved (bit part of the talk) — 3 new theorems:**
`lowbit_isolates`, `lowbit_spread` (64-bit) and `lowbit_spread_32` — the second
is exactly the borrow-spread identity that turns `@ctz` tokenisation into a
single instruction (`(y-1) &&& ~~~y = lowbit - 1`).

**Honest note on imports:** `FarkasSoundness.lean` used to be zero-import; for
`bv_decide` exactly one import was added — `Std.Tactic.BVDecide`, shipped with
Lean 4 (Mathlib NOT required), documented in the file header.

**Measured:** `formal/check.sh` → **ALL LEAN PROOFS OK (8/8 files, 0 errors,
0 sorry)**; theorems **131 → 134**. Bonus: `bv_decide` also FINDS
counterexamples (it refuted my first, incorrect formulation with
`y = 0x8000000000000000`).

---

### 60. Defect #212: term moving done STRUCTURALLY -> trusted 2 -> 0

Remaining pair from the dump: `L=(<= result T)`, `R=(<= (+ result (* (- 1) T)) 0)`
with `T = (ite (<= (mod value 2) 0) 1 0)`.

**Key decision: do NOT touch `parseLin`.** The rule checks structure only:
`(✦ A B) ⟺ (✦ (+ A (− B)) 0)` for ✦ ∈ {≤,<,≥,>}, and
`(≥ A B) ⟺ (≤ (+ B (− A)) 0)`, `(> A B) ⟺ (< (+ B (− A)) 0)`, where `A` and `B`
are compared byte-wise (`sexpEq`) and `(− B)` accepts both `(* (- 1) B)` and
`(- B)`. Since nothing inside `A`/`B` is inspected, an `ite` there is irrelevant.

**Measured:** `value % 2 == 0` — trusted **2 -> 0** (`trusted: 0 | holes: 0`),
linear rewrites 19 -> 21; reference `abs.c` stays `trusted: 0`; `make contracts`
11/4/**0 false alarms**; Lean **134 -> 137** theorems, 0 sorry.

### 60a. Defect #213: `--trust-score` missing from the CLI
Documented but absent from argparse. Added `--trust-score <PATH|owner/repo>`
delegating to `tools/trust_scorecard.py` (no growth of `kern_contracts.py`).

---

### 61. Lists in plain Int + rule↔theorem matrix + bare-`except` guard

`arr[i]`, `arr[i] = v`, `arr[i] += v`, `for x in arr` and `if n:`/`while n:`
(a number in `Bool` position) were OUTSIDE the subset, so 10+ `QuixBugs` tasks
were skipped **before the solver** — with a perfectly working Zig core.

**Implemented in plain `QF_LIA` (no array theory):** window `arr__e0..arr__e2 : Int`
plus `len__arr : Int` (created once per name → the same index yields the SAME
value, i.e. index congruence); reading `arr[i]` is an `ite` cascade; writing and
`+=` update the three `ite`s; a list literal carries its REAL length (constant);
`for x in arr:` becomes `for i in range(len(arr)): x = arr[i]` unrolled K steps
under `len__arr > t`; truthiness is coerced (`if n:` → `(not (= n 0))`,
`if arr:` → `(> len__arr 0)`).

**Soundness:** the model is an over-approximation (elements are arbitrary), so
`DIVERGED` is still claimed ONLY after a live call of both versions (#206).

| Check | Before | After |
|:--|--:|--:|
| `make contracts` | 11/4/0/0/2/2 (19) | **11/4/0/0/2/2 (19)** — unchanged |
| `QuixBugs` DIVERGED (live) | 3 | **5** |
| `QuixBugs` SKIP | 35 | **32** |
| `arr[0]` (parameter) | SKIP | **PROVEN, trusted: 0** |
| `[10,20,30][i]` | SKIP | **PROVEN, trusted: 0** |
| `arr[0] += 5` | SKIP | **PROVEN, trusted: 0** |
| `for x in arr: s += x` | SKIP | `[SKIP] [UNBOUNDED]` — honest (#207) |

Newly confirmed dataset bugs: `hanoi` (`buggy=[(0,1)]` vs `correct=[(0,0)]`),
`sieve` (`buggy=[]` vs `correct=[2]`).

**`trusted: 2 → 0` debt closed (#212):** structural `cmpSubZeroEq` without
touching `parseLin`; `value % 2 == 0` → `steps: 81 | trusted: 0 | holes: 0`;
Lean `cmp_sub_zero_iff`, `le_iff_sub_nonpos` (137 theorems total).

**`docs/RULE_THEOREM_MATRIX.md`:** 17 `verify*`/`check*` rules × 137 theorems,
with three rules honestly attributed to the Lean kernel (transitivity,
`And.left`, modus ponens) and `intro-def` as a conservative extension.

**Bare-`except` guard (#215):** 29 bare handlers wrapped with `_replay_soft`
(programming errors are printed, only expected ones are swallowed);
`dup_defs_guard.py` now also ratchets bare handlers (`bare_except_baseline.json`).

---

### 62. Defect #216: list rebuilt FROM THE Z3 MODEL (QuixBugs 5 -> 6)

`max_sublist_sum` reached the solver after the list scheme (#214) but was
discarded by Live Replay: the model carries `arr__e0..2` and `len__arr`, not
`arr`, so `p in model` never matched, and the fallback domain had no list
starting with a negative element.

**Fix (only `tools/quixbugs_check.py`):** the list is rebuilt from the model
(`[arr__e0, arr__e1, arr__e2][:len__arr]`) and the domain gained `[-1,2]`,
`[2,-1,2]`, `[1,-2,3,-1]`. **Soundness unchanged:** divergence is still claimed
ONLY after a live call of both versions (#206).

| | before (#214) | after (#216) |
|:--|--:|--:|
| `QuixBugs` DIVERGED (live) | 5 | **6** |
| DISCARDED | 3 | **2** |
| SKIP | 32 | 32 |

New confirmed bug: `max_sublist_sum`, `arr=[-1, 2]` — buggy returns **1**,
correct returns **2**.

---

### 63. Documentation integrity: 65 holes in the EN registry and duplicate section numbers (Defect #218)

**How it was found:** not by a report, but by a check — a script compared the number sets of both registries and the heading sets of both journals.

**Measured BEFORE:** RU registry **155** rows (#1–#217) vs EN **91**; **65 numbers missing** in EN (#52, #55, #56, #59–#92, #98–#124, #205); **#174 duplicated** in EN; RU `METRICS.md` had **§100, §101, §102 twice each** (14 prefixed lines); EN registry had **two `## 6e`** headers; `docs/README.md` advertised `#1–#216` and `§1–#136`.

**Note on the third column:** in the older registry sections (#59–#124) it holds a **defect class** ("tool (critical)"), in the newer ones a **status** ("FIXED"). That difference is preserved as a fact instead of being silently normalised; the EN index labels the column **"Class (as in RU)"**.

**Fixed:** (1) EN sections `6d-1` (#125–#152) and `6d-2` — a compact index of the **65 entries** with one-line summaries and a pointer to the Russian full text; (2) the SECOND §100/§101/§102 blocks renumbered to **§137/§138/§139** (subsections included; no external references existed — verified by `grep`); (3) the second `## 6e` → **`## 6f`**, and the duplicate #174 row marked **`174 (closure)`**; (4) `docs/README.md` ranges corrected.

**Measured AFTER:** RU **156 rows / 156 unique / max #218**; EN **156 / 156 / max #218**; **0** numbers missing in EN; **0** duplicate RU sections (115 sections, max §139); **0** duplicate EN headers; `registry.py` prints «defect numbers are unique (156 rows)».

---

### 64. The KERN-Next evidence had no count of executed tests (Defect #219)

**Symptom:** `docs/evidence/kern_next_tests.log` held only «Build Summary: 4/4 steps succeeded / test-next success / run test cached» and `RC=0` — **without «All 53 tests passed»**. Cause: on a cached step Zig does not execute the test binary and prints no counter.

**Consequence:** the showcase claims «53 / 53 passed» citing that log, while `evidence_gate` could not confirm it: the number of EXECUTED tests was absent from the evidence.

**Fixed:** `tools/collect_evidence.sh` runs the step with a separate `--cache-dir /tmp/kern_next_evidence_cache` (removed right after), so the step really executes and the log records `Build Summary: 4/4 steps succeeded; 53/53 tests passed`. Measured: **2 s** (no recompilation — the global cache is warm).

**Verified:** the log contains «53/53 tests passed» with `RC=0`; `evidence_gate` — 33 logs clean, no caveats. Side note: this confirms the documented Zig 0.17 behaviour (§22, §75) — a GREEN run still prints `failed command: … --cache-dir=…`; the verdict comes from the protocol, not from that line.

---

### 65. Stale test counts on the showcase (Defect #220)

**Found** by checking «claim ↔ evidence», not by a report.

| Where | Was | Fact |
|:--|:--|:--|
| `README.md` (build block) | `zig build test  # 308 core tests` | **401** (`core_tests.log`: «All 401 tests passed.») |
| `README.ru.md` (layout) | `test_root.zig (308 tests)` | **401** |
| `README.ru.md` | «catalog 424 tests» | **425** (`gen_test_catalog.py --check`) |
| `docs/README.md` | «catalog: 424 tests» | **425** |
| `docs/README.md` (about `VERIFICATION_0_17.md`) | «build, 308 tests» | that document is a **snapshot of 2026-10-13**; now marked |
| `README.ru.md` (migration branch) | «RC=0 (build, 283 tests…)» | a historical statement about that branch; marked «at migration time» |

**Verified:** `grep` over `README.md`, `README.ru.md`, `docs/README.md`, `docs/index.html` finds no 308/424 as CURRENT values; `gen_test_catalog --check` reports 425, synchronised.

---

### 66. Recurrence of class #178: the registry range drifted again (Defect #221)

**Found** the same way as #220: by checking «claim ↔ fact», not by a report.

| Where | Was | Fact |
|:--|:--|:--|
| `README.md` (documents table) | `defect registry #1–#184` | **#1–#220** |
| `README.ru.md` («defect registry» row) | `#1–#184` | **#1–#220** |
| `docs/index.html` (2 places) | `#1–#184` | **#1–#220** |
| `docs/CAPABILITY_STATUS.en.md` (section intros 6d-1/6d-2) | `#1–#217` | **#1–#220** |

**Why this matters more than the numbers:** exactly this class was already closed by defect **#178** («the public registry count and MCP tool names on the site were stale»), yet a one-off fix did not hold the metric — the registry grew to #220 while the showcase stayed at #184. It is recorded as a RECURRENCE (not a new class) so that no illusion of «solved» is created.

**Verified:** `grep '#1–#184'` over `README.md`, `README.ru.md`, `docs/index.html` — **0** hits; the EN registry states `#1–#220`; the fact is 158 rows with maximum #221 after this record.

**Automated guard (so that class #178/#221 cannot recur):** `tools/ecosystem_check.sh` gained check **7** — it reads the maximum defect number from `docs/CAPABILITY_STATUS.md`, and every `#1–#N` range in `README.md`, `README.ru.md`, `docs/index.html`, `docs/README.md` must equal it. Proven in both directions: now `[OK] ranges #1–#221 … match`; after substituting `#1–#184` the gate prints `[FAIL] README.md: range #1–#184 while the registry maximum is #221` and returns rc=1, then `[OK]` again after restoring. `canfail --only ecosystem-check` — 1 non-vacuous / 0 vacuous.

---

### 67. The license on the showcase contradicted the LICENSE file (Defect #222)

**Found** by checking «claim ↔ `LICENSE` file», not by a report.

| Where | Was | Fact |
|:--|:--|:--|
| `README.ru.md` (repository tree) | `├── LICENSE   MIT` | **PolyForm Noncommercial 1.0.0** |
| `server.json`, `.well-known/mcp.json`, `CITATION.cff` | `PolyForm-Noncommercial-1.0.0` | matches `LICENSE` ✅ |
| `README.ru.md` (repository tree) | `Makefile 62 targets` | **150 targets** (`registry.py`: «total targets: 150») |

**Why this is not cosmetic:** this is exactly the class raised in the external-audit discussion — scanners (m8ven.ai, GitHub licensee, MCP catalogues) compare the `license` field of the manifests with the `LICENSE` file, and a mismatch is read either as a ranking penalty or as a **false promise** to the user. «MIT» next to PolyForm in the repository tree is precisely a false promise.

**Fixed + guard:** `README.ru.md` corrected; `tools/check_license_consistency.py` added (check **8** of `ecosystem-check`): `LICENSE` mentions «PolyForm Noncommercial»; `server.json` and `.well-known/mcp.json` declare `PolyForm-Noncommercial-1.0.0`; `CITATION.cff` carries the same id; no `LICENSE … MIT` line in either README (`LIMITATIONS` excluded).

**Proven in both directions:** now `[OK] licence consistent`; after injecting `LICENSE MIT` into `README.ru.md` — `[FAIL] README.ru.md: the LICENSE line promises MIT`, rc=1; after restoring — `[OK]` again.

---

### 68. The Lean 4 theorem counter on the site was 17 behind (Defect #223)

**Found** by checking «claim ↔ `formal/*.lean`».

| Where | Was | Fact |
|:--|:--|:--|
| `docs/index.html` (**4** places: hero, meta description, metrics block, footer) | `120 Lean 4 theorems` | **137** |
| `README.md` | `137 theorems` (3 places) | ✅ matched |
| `README.ru.md` | `137 теорем` | ✅ matched |

**Why this is an important class, not a typo:** the Lean 4 theorem count GROWS (120 → 134 → 137 over three iterations) while the showcase is edited by hand, so the metric systematically lags — exactly as in #178/#221 (registry range) and #220 (test counts). Same root: **the number on the showcase is not tied to the source of truth**.

**Fixed + guard:** `tools/check_lean_counter.py` (check **9** of `ecosystem-check`) — the actual count comes from `formal/*.lean` (`^theorem `), and every number before «Lean»/«theorems»/«теорем» in `docs/index.html`, `README.md`, `README.ru.md` must equal it.

**Honest about the exclusions (otherwise the guard raises false alarms):**
1. «Lean 4 theorems» is the Lean VERSION, not a counter → skipped;
2. a line referencing a specific `.lean` file is that FILE'S count (e.g. `KernSemanticGap.lean: 8 theorems`) → skipped.
   Both exclusions were found by practice: the first version of the guard «caught» `4 theorems` and `8 теорем` — it worked, but wrongly.

**Proven in both directions:** now `[OK] Lean 4 theorems: 137 — showcase matches (7 occurrences)`; after substituting `137 Lean` → `120 Lean` — `[FAIL] docs/index.html: «120 Lean» — fact 137`, rc=1; after restoring — `[OK]` again.

---

### 69. Showcase audit: #224 (counters) + #225 (rollback outside FAULTABLE)

Every public surface was compared against a **measurable** source:
`docs/evidence/core_tests.log`, `kern_next_tests.log`, `cross_arch.log`, the
catalogue recount, `tools/registry.py --json` — not against prose.

**#224 — 7 places where text contradicted fact:** `README.md:45`
(`125 CHECK targets; 114 proven non-vacuous (95 fault-injection cases)`),
`README.ru.md` (`103 targets / CHECK 80 / 82/82 / 95 cases`), RU passport
(`195/195` without a snapshot marker), `PROJECT_SPECIFICATION.md` (`195/195`,
`Lean 4 (7 files)`), `PROJECT.md` (11 places: `279`, `38/38`, `92.5 %`, `60`,
`233`), `CAPABILITY_STATUS.en.md` (`279/279 OK`).

**Fix:** all numbers set to facts (401 / 53 / 425 / 127 CHECK / 143 cases) and a
new guard **`tools/check_metrics_consistency.py`** (`make metrics-guard`, case
`metrics-guard`) that checks a promise against evidence. Lines marked
`snapshot` / `history` are skipped; cross-architecture must cover the whole suite
(`passed + skipped == core`). Non-vacuity proven by injection: `999 proven
non-vacuous` -> `rc=1`, `999 объявлений` -> `rc=1`.

**#225 — false "tree clean":** the `metrics-guard` case edits `docs/PROJECT.md`,
which was **not in `FAULTABLE`**: no snapshot, no rollback, injection stayed in
the tree while `verify_restored()` (FAULTABLE-only) reported "[OK] tree clean".
Root cause: `patch()` refuses files outside `FAULTABLE`, `touch()` accepted them
silently; second offender `kern.intoto.sig` (case `slsa-bad-sig`).
**Fix:** both files added to `FAULTABLE`, `touch()` now raises the same
`RuntimeError` as `patch()`. Verified by re-running the case: the file is
restored byte-for-byte.

---

### 70. Registry integrity audit: 33 records were invisible to the duplicate guard (#226)

**Found** by comparing `registry.py` against the table itself: the duplicate guard
matches `| **N** |`, while part of the journal was written as `| N |`. Of **197**
canonical records the guard saw **164**.

| Item | Fact |
|:--|:--|
| records in the journal (real) | **197**, range #1–#226 |
| visible to the guard | **164** (bold format only) |
| invisible | **33**: #1–#10 (section 6), #31–#47 (moved in from METRICS), #93–#97, #165 |
| duplicate numbers | **0** (checked across all 197) |

**Why it matters.** The guard exists so that two different defects cannot take the same
number. It did not read a third of the journal — so it could not catch a collision
exactly where numbers were assigned by hand.

**Fixed:** #1–#10, #31–#47, #93–#97 and #165 converted to canonical format; the guard
now sees **197 rows** and confirms uniqueness.

**Not claimed:** that all 226 numbers exist. Historical gaps remain (e.g. #11–#30
were never used) — stated as a fact, not as a goal.

---

### 71. Defect #232: the gate existed, but CI never invoked it (`scorecard-check`)

**Symptom.** `docs/evidence/scorecard.json` (the Trust Scorecard passport the site
reads) carried **125 theorems** and **125 CHECK** while the facts were **137** and
**126**. The discrepancy survived several commits with a green CI.

**Why it was missed.** `tools/ci.sh` ran `ecosystem-check`, `metrics-guard`,
`check_lean_counter`, `gen_test_catalog --check` — but there was no
`scorecard-check` stage (the target existed only in the `Makefile`). Meanwhile the
canfail case `scorecard-check` failed correctly whenever the passport was tampered with.

**Root cause — a substitution of notions.** canfail answers "CAN the gate fail?"
(sensitivity). It does **not** answer "is the published artifact FRESH?"
(currency). They are two different checks, and the second one ran nowhere.

**Fixed:** stage `Trust Scorecard passport == facts (#232)` in `tools/ci.sh` right
after `ecosystem-check`; the passport regenerated (137/126, `commit ad61820`,
Grade A+, 100/100).

**Verified:** `bash tools/scorecard_check.sh` → `rc=0`; step 3 prints
`docs/evidence/scorecard.json matches the recomputation (100/100, Grade A+)`.

**Not to be confused with #87:** the `commit` field is deliberately not compared
(the artifact is generated before the commit and would always lag by one). What is
compared: `score`, `grade`, `mcp.tools`, `formal.theorems`, `metrics.check_covered`.

---

### 72. Stage 2: AST-guided trace explorer — 28/40 by live execution (#233–#235)

Stage 1 (static `QF_LIA` + Live Replay) covered 6/40 QuixBugs tasks; 32 fell into `SKIP`
(lists, dicts, slices, strings, generators, bit operations) — a **frontend** boundary, not a
kernel one. Instead of patching one AST node at a time, a second mechanism was added:
`tools/trace_explorer.py`.

Parameter kinds come from the AST and docstring (`declared_kind`): `int` / `list` /
`list[list]` / `str` / `float` / `tokens`. Domains are built from constants found in the
body itself (`c`, `c-1`, `c+1`) and ordered by whether the docstring precondition holds
(`precondition_of`). Inputs are executed live (timeout; `RecursionError`, `IndexError`,
`ZeroDivisionError`, `KeyError`, `TypeError` caught) and results are normalised
**recursively**, so generator objects never produce address-based false divergences.

Measured (`docs/evidence/quixbugs_full.log`, RC=0): `DIVERGED 28/40` (stage 1: 6,
stage 2: 22), `STAGE2-CLEAN 12`, `SKIP: DictComp 1`. Every hit is confirmed by a live call
`buggy(args) != correct(args)`; 15 witnesses were re-checked by an independent script
(`0 outside the domain`).

Defects found while building it: **#233** (parameter types unread → int domains for
strings/lists), **#234** (`NameError` swallowed by the precondition filter: generator
expressions inside `all(...)` resolve names in `globals`, not `locals`), **#235** (false
divergence message: a generator was consumed by the first `_norm`, the message printed a
second call).

**Honest limit.** Stage 2 is a **search**, not a proof: it never emits `PROVEN` and does not
replace Stage 1. The 12 `STAGE2-CLEAN` tasks mean "no divergence on the inputs tried".

---

### 73. "AI vs KERN" stand: `make ai-demo` (20 assertions, 0 failures)

The project's focus is verifying AI-written code, yet the showcase had no end-to-end
scenario showing **what the agent reported** next to **what KERN found in the same code**.
The stand reuses existing pieces only and is registered as CHECK target #153.

| Act | Shown | Real output |
|:--|:--|:--|
| 1 | CI is green | `2 passed in 0.01s` — one test has no `assert`, the other swallows failure |
| 2.1 | cheating test | `[CHEAT DETECTED: swallowed assert (except: pass)]` line 28 → `R=-2.0` |
| 2.2 | broken contract | `[FAIL] transfer_with_fee` · `[КОНТРПРИМЕР] result = -1, amount = 1, balance = 0` · `[RUNTIME CONFIRMED]` (2 violations, `ЛОЖНЫХ ТРЕВОГ 0`) |
| 2.3 | fee arbitrage | `[FAIL] fee_threshold: no_arbitrage REFUTED` · `a1 = 100, a2 = 1`, while `fee_proportional` is `PROVEN (trusted: 0)` |
| 2.4 | agent "cleanup" | `[DIVERGED] charge` · `res_old = -1, balance = -1, amount = 0, res_new = 0` |
| 2.5 | poisoned MCP schema | 4 prompt injections + `INVISIBLE UNICODE U+200B` |
| 2.6 | agent action | `[FAIL] Firewall: POLICY CONFLICT -> B (1,1), e=0, HTTP 409 Conflict` |
| 3.1 | auto-surgeon | `[HEAL] найдено крашей: 1 \| после патча: 0`, `[T (1,0)] файл вылечен`, `.bak` kept |
| 3.2 | mathematical clearance | `[PASS] transfer_with_fee: ДОКАЗАНО` · `steps: 50 \| premises bound: 3/3 \| trusted: 0 \| holes: 0` |
| 3.3 | training oracle | `R=+1.0 [VERIFIED REWARD, Belnap T, e=1]` |

Honest scope: the stand is a **scenario**, not a new engine — every verdict comes from
shipped commands (`--anti-cheat`, contracts, `--presets`, `--diff-equiv`, `--audit-mcp`,
`--verify-action`, `--heal`, `--rlvr-reward`). `[FAIL]` lines are KERN **verdicts** (expected),
not stand failures; `pytest` stays green, which is the whole point. `z3` is required
(the script adds `~/ai_lab/.venv/bin`), otherwise acts 2.2/2.3/3 make no sense → `exit 2`.
`make ai-demo` returns `rc=1` if any expected line disappears, so the demo cannot drift
into a claim the tools no longer back.

## §128. QuixBugs via `--diff-equiv`: invariants instead of promises (Stage 4B)

## §129. SV-COMP: the `no-overflow` property is broader than what KERN checks — measured, not claimed

**The source is OFFICIAL, and that is checkable.** Category
`c/signedintegeroverflow-regression` from `sosy-lab/sv-benchmarks` (the
repository of the international verification competition, TACAS). **15 tasks**,
ground-truth verdict from `.yml`: **10 `false` (BUG PRESENT)**, **5 `true`
(SAFE)**. Property: `../properties/no-overflow.prp`.

Measurement tool: `tools/svcomp_baseline.py` → `docs/evidence/svcomp_baseline.log`.
This is a **MEASUREMENT, not a gate**: a gate on these numbers would claim
coverage of a property KERN does not have.

| Column | Result |
|:--|:--|
| `--xray` on the **UNMODIFIED** official files | caught **0 of 10** unsafe; false alarms **0 of 5** |
| contract path on the official files | **15 SKIP** (without annotations — `no functions with annotations`; with a trivial annotation — `outside the subset`, because ALL 15 contain a `printf` call) |
| contract on a DERIVED file (annotation + `printf` removed) | `REFUTED` **2 of 10**, **FALSE `PROVEN` 4 of 10**, `SKIP` 7, `PROVEN` safe **2 of 5** |

**The exact mechanism of the gap.** `no-overflow.prp` requires **EVERY**
arithmetic operation to stay within the type bounds. KERN checks the **FINAL**
return value (`TYPE_RANGE` in `build_overflow_smt`). `(2147483647 + 1) - 23`
overflows **INSIDE** (`2147483648`), but the result `2147483625` lands back in
range — and the type obligation is **satisfied**. So "collapsing" cases are
missed, while traps are caught (`Division-1` = hardware `idiv`, #334;
`UnaryMinus` = unary overflow, #337).

**This is NOT a lie about the stated contract.** `ensures result == 0` genuinely
holds. KERN claims **LESS** than the SV-COMP property, not more — a **miss, not a
verdict swap**. That is what separates this from #206/#317 (a false proof of a
false claim).

**Why `--xray` is blind to this class.** The C-path detectors are: division by
zero, array bounds, **allocation size** (`_mentions_param`) and branches. There is
no detector for overflow of an **ordinary expression** — measured by running it,
not inferred from reading the code.

**What honest coverage would need (not done, named).** "Path C": applying the
property file (`.prp`) to **every** operation in the file, not just the return.
That is translator work, not configuration. Until then there is **no gate**.

**Boundaries named:** 15 tasks is one category, not all of SV-COMP (thousands of
files); the "contract (derived)" column refers to a **DERIVED** file and is NOT
the competition task in pure form; a missing task on disk/network yields an
honest `SKIP`, not a "green" result.


**Measured.** The `make quixbugs-diff-check` gate (`tools/quixbugs_diff_check.py`)
on the full `jkoppel/QuixBugs` corpus (40 pairs):

| Metric | Value | Required |
|:--|:--|:--|
| `DIVERGED` (bug caught by a live call) | **40 / 40** | — |
| `EQUIVALENT` on a buggy pair | **0** | — |
| **`false_equivalent`** | **0** | **0** |
| **`false_diverged`** (control `correct` vs `correct`) | **0** | **0** |
| Tool crashes on the control | **0** | **0** |

**Two invariants, not one.** `false_equivalent == 0` closes a FALSE PROOF (class
#206/#317: a bug declared equivalent to correct code). `false_diverged == 0` on
the control pairs `(correct, correct)` closes a FALSE ACCUSATION (class #178: an
analyser that accuses everything). Without the second half the gate would only
catch a "too soft" tool.

**The control half does not depend on the dataset** — it ALWAYS runs, so the gate
is never vacuous even on a machine without a network. When the external dataset is
absent, the 40-pair half is skipped OUT LOUD (with the clone command) rather than
counted as an "ok".

**A side finding (#361).** The gate's very first run showed that
`--diff-equiv a.c b.c` CRASHES with `SyntaxError` instead of an honest "outside the
subset": the control pair `cwe190_good.c` (the file against itself) produced a
crash, not `EQUIVALENT`. A crash is now distinguished as `tool_errors` and counts
neither as a divergence nor as proof.
