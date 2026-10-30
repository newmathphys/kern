# KERN — METRICS JOURNAL

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->487 · CHECK <!-- fact:check_targets -->183 · cases <!-- fact:canfail_cases -->223 · anchors <!-- fact:anchors -->183 · registry <!-- fact:registry_targets -->239 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

> **Note on quoted tool output.** KERN's tools print their verdicts in Russian; lines quoted verbatim (e.g. `[dbg-ur] посылок: …`, `0 паник`) are kept byte-for-byte, because the can-fail gates match those exact strings. Everything else in this file is English.


> Every number here comes from an actual run. Nothing from memory.
> Updated per iteration. English translation of `docs/METRICS.md`; the Russian
> original remains the source of truth for historical sections.
>
> **CURRENT STATE (2026-10-20):** v2.5.1 · core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->487 ·
> CHECK <!-- fact:check_targets -->183/<!-- fact:check_targets -->183 · cases <!-- fact:canfail_cases -->223 · anchors <!-- fact:anchors -->183 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 differential.
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
## §129. SV-COMP: the `no-overflow` property is broader than what KERN checks — measured, then CLOSED by "Path C"

> **RESULT AFTER DEFECT #367 (measurement history below).** The C path of
> `--xray` gained a detector for overflow of ANY arithmetic (binary `+ - * / %`,
> unary minus, `x++/x--`). **MEASURED on the same official category:
> `TP 10 / 10`, `FP 0 / 5`, `TN 5 / 5`, `TPR = 1.00`, `FPR = 0.00`,
> YOUDEN INDEX `J = 1.00`** (was `TP 0 / 10`). Gate: `make xray-overflow-check`;
> reference: `examples/overflow_xray_demo.c`; evidence:
> `docs/evidence/svcomp_baseline.log`.
>
> **FOUR CLASSES OF FALSE ACCUSATIONS found by re-measuring, all fixed:**
> literal type by value (C11 6.4.4.1p5), integer promotion to `int`
> (C11 6.3.1.1), unsigned wraparound (DEFINED in C, not UB) and a guard via
> `exit()`. Details: defect journal, entry #368.
>
> **HONEST BOUNDARY, NAMED:** the symbolic path is allowed only over INPUT
> PARAMETERS. The value of a local mutated in a loop is not derived (loops are
> not modelled), so for example `palindrome.c: reversedNumber * 10` — a true
> CWE-190 — is MISSED by the detector. The miss is named, not hidden.

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


## §130. REAL NIST JULIET C: the first measurement on ACTUAL files, not on our own fixtures

> **MEASURED.** The dataset `arichardson/juliet-test-suite-c` — the official
> mirror of NIST Juliet C: **607 MB, 118 CWE categories**;
> `CWE190_Integer_Overflow` — **5040 files**, **2220** of them signed-`int`
> variants. The verdict is computed **PER FUNCTION** (`_bad` vs `good*`):
> otherwise `_bad` and `good` inside one file would be mixed. Tool —
> `tools/juliet_measure.py`; sampling is **DETERMINISTIC** (every k-th file), not
> "the first N". The dataset is downloaded to a temp directory and is **NOT**
> part of the repository, so the script honestly prints `[SKIP]` when the
> directory is absent and does NOT credit such a run.

| Category, subdirectory `s01` (60 files of 616) | `_bad` / `good` | TP | FN | FP | TN | TPR | FPR | YOUDEN INDEX `J` |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|
| `CWE190_Integer_Overflow` | 42 / 52 | **0 / 42** | 42 | 2 | 50 | **0.000** | **0.038** | **-0.038** |
| `CWE369_Divide_by_Zero` | 42 / 54 | **0 / 42** | 42 | 2 | 52 | **0.000** | **0.037** | **-0.037** |

Evidence: `docs/evidence/juliet_real_cwe190.log`,
`docs/evidence/juliet_real_cwe369.log`. **NO GATE CREATED** — a decision made on
numbers, not postponed.

**WHY THIS IS A DIFFERENCE OF DEFINITIONS, NOT A KERN BUG (measured, not
assumed).** Juliet labels `_bad` as "POTENTIAL FLAW" — a POTENTIAL defect, not
undefined behaviour. A typical `_bad` of CWE-190 is
`char data; char result = data + 1;`. Here `data` is PROMOTED to `int`
(C11 6.3.1.1), so `data + 1` does **not** overflow, and the narrowing on
assignment to `char` is **implementation-defined**, not UB. KERN's detector
targets UB, so it misses such `_bad` BY SEMANTICS, not by mistake.

**BREAKDOWN OF MISS REASONS, not a single number.** In CWE-190: "narrow type
promoted to `int`; narrowing is implementation-defined" — **36**; "local value
not derivable / loop / call" — **6**. In CWE-369: "narrow type" — **26**,
"other" — **16**, plus a named reason: the divisor is a LOCAL
`float data = 0.0F` (the `[CRASH PATH]` detector requires the divisor to depend
on an INPUT PARAMETER — lesson #179/#200), it is a float (division by `0.0`
yields `inf`, not a panic), and the body contains sockets and loops. A miss for
three named reasons, not "we could not".

**TWO DIFFERENT CLASSES INSIDE ONE `FP` COUNT — and by its OWN property there
are ZERO false accusations.** MEASURED per class: `[OVERFLOW PATH]` FP = **0**.
The findings counted as "FP" belong to ANOTHER class: in Juliet's `_03` variant
the branch `if (5 != 5)` is genuinely unreachable, and Juliet itself annotates it
in the source — `/* INCIDENTAL: CWE 561 Dead Code, the code below will never run
*/`. So `[DEAD BRANCH]` there is a TRUE finding of a DIFFERENT property. Mixing
classes in one score would produce either a false alarm or false comfort — hence
a gate on `J` cannot be built, and that is named.

**HONEST BOUNDARY, NAMED:** measured on ONE subdirectory (`s01`) of two
categories and a deterministic sample of 60 of 616 files — NOT the whole Juliet
suite (118 categories, tens of thousands of files). The `J` number here
MEASURES THE DIFFERENCE OF DEFINITIONS, not KERN's quality.

## §131. A JOURNAL RECORD TORN FROM ITS SUB-ROWS: the gate compared a SET, not the STRUCTURE (defect #370)

**What happened.** Record #369 was inserted IMMEDIATELY BEFORE the first sub-row
`| **368.1** |` of the previous record. In `docs/CAPABILITY_STATUS.en.md` the
header `| **368** |` stayed ABOVE while the sub-points `368.1...368.7` slid BELOW —
under a foreign header. The reader attributes the sub-points of defect #368 to
defect #369: the journal says something OTHER than what it claims. The RU journal
was NOT affected — the divergence was ASYMMETRIC.

**Why every gate stayed silent.** `journal-parity-check` compares the SET of
record numbers in RU and EN. Here NOT A SINGLE NUMBER changed: the record pattern
`^| **N** |` does not match the sub-row `^| **N.k** |`, so the sets stayed equal
(330 = 330). `docs-parity` compares fact anchors, `claims-audit` scans numbers,
and both skip `CAPABILITY_STATUS` entirely. The boundary was DECLARED in the
gate's docstring ("does not demand record order") — and the defect passed through
exactly that boundary. Same class as #350/#356/#361/#365: a record that looks
verified but says something else.

**Closed by an invariant, not by hand.** Invariant (2) was added to the same
gate: for EVERY sub-row `| **N.k** |` the nearest preceding HEADER row must be
`| **N** |` (`orphans()`).

| Check | Value |
|:--|:--|
| Orphans in RU / EN AFTER the fix | **0 / 0** |
| Records RU / EN / intersection | **330 / 330 / 330** |
| Meta-test branches (was 4) | **6** (an orphaned header is caught; correct structure passes) |
| Non-vacuous case | `journal-orphan` (number-neutral) |

**The `journal-orphan` case is NUMBER-NEUTRAL — and that is not a detail, it is
the proof.** The sabotage renames the PARENT of one sub-row (`368.1` -> `367.1`).
The set of record numbers does not change, so invariant (1) is silent BY
CONSTRUCTION and ONLY invariant (2) can redden the gate. Shifting a header or
deleting a record would redden the gate on the sets too — and the non-vacuity of
the new invariant would have remained UNPROVEN.

**Honest boundaries:** the invariant checks the ATTRIBUTION of a sub-row to its
record. It does NOT check the content of sub-rows, their order WITHIN a record,
the contiguity of sub-numbers, and does NOT require records to be sorted by
number. Translation quality is still reviewed by a human.

## §132. SMT-COMP PROOF-CHECKING TRACK: 4 theories of the OFFICIAL SMT-LIB — and FOUR defects the measurement exposed

**Date:** 2026-10-27. Gate: `make smtlib-proof-check`
(`tools/smtlib_proof_check.py`).

### 132.1 What existed and what did NOT

`make smtlib-bench-check` (#366) pinned **ONE** theory (`QF_S`, 10 files) and
compared only the `sat/unsat` line against the `:status` tag. That checks the
**SOLVER**. The SMT-COMP **Proof-Checking Track** checks the **DERIVATION**: on an
`UNSAT` task the solver must produce a proof that an independent proof checker
parses and re-verifies. Our `src/verifier/proof_check.zig` took part in **no**
official-bank run — not once. That gap is now closed.

### 132.2 Sources — OFFICIAL, and verifiable

Every sample comes from repositories of the **SMT-LIB organisation** (not ours,
not someone's fork) or from its own Zenodo release. Task licence is CC-BY-4.0
(the `:license` tag inside the file).

| Theory | Source | Files |
|:--|:--|:--|
| `QF_LIA` | `SMT-LIB/benchmark-submission-2022`, `QF_LIA/20220307-SMPT` | 12 |
| `QF_LIA_heavy` | `SMT-LIB/benchmark-submission-2024`, `QF_LIA/20231117-c_inference` | 2 |
| `QF_BV` | `SMT-LIB/benchmark-submission`, `QF_BV/20250812-Circt` | 2 |
| `QF_AX` | Zenodo `10.5281/zenodo.16740866` (SMT-LIB release 2025), `QF_AX.tar.zst` | 4 |
| `QF_S` | `SMT-LIB/benchmark-submission-2025`, `QF_S/20250410-matching` | 3 |

### 132.3 FOUR defects found by the VERY FIRST run

None of them was visible before: the official tasks had never been run.

| # | What was broken (MEASURED) | Why no gate saw it |
|:--|:--|:--|
| **#371 A** | The Z3 proof query wrote the `.smt2` file **verbatim**. **EVERY** official SMT-LIB file ends with `(exit)`, so Z3 terminated BEFORE our `(get-proof)` — the proof was **never requested**, and the checker received an empty string. | No official-bank run ever invoked the proof checker: only the `:status` line was compared. |
| **#371 B** | `MAX_SEXP_DEPTH = 4096`, while the measured depth of official Z3 proofs is **4 606** (`add_three.4_bit`), **13 169** (`add_three.8_bit`), **200 690** (`blend.4_bit`). The limit was below the very first task. | The comment claimed "real Z3 derivations fit in a few levels" — never measured. On our own fixtures depth is < 20. |
| **#371 C** | Both causes were reported with one text: "the derivation does not parse as an S-expression" — i.e. it **blamed the solver for garbage**, although the derivation was a valid S-expression that hit OUR limit. | The refusal text was checked by nothing: it "looked like" a solver refusal. |
| **#372** | The `prove` path printed `[PROOF VERIFIED]` with `TRUSTED > 0` (MEASURED: **5** on `QF_AX/storeinv`, **2 970** on `QF_BV/add_three.4_bit`). The label "VERIFIED" sat on a derivation part of whose steps were NOT verified. The `check-proof` path obeyed the rule, `prove` did not. | No gate ever compared the label against the trusted-step count. |
| **#373** | `kernc smtlib` read `.smt2` with a **1 MB** limit, while official `QF_LIA/20231117-c_inference` files weigh **1 636 928** and **1 682 698** bytes. The read failed, `catch continue` **silently** skipped the file, and the counter printed "**files total: 0**" on a NON-EMPTY directory. | The report named the vacuum but not the CAUSE: an empty directory and unreadable files looked identical. |

**All four are the same class** (as #370): the message says something other
than what happened. And in all four cases the "wrong" behaviour looked green:
0 steps → "0 holes"; 0 files → "0 divergences".

### 132.4 MEASURED: 4 theories of the official bank

| Theory | Files | Checked | Matched | Diverged | False | Timeouts | Unreadable |
|:--|--:|--:|--:|--:|--:|--:|--:|
| `QF_LIA` | 12 | 12 | 12 | **0** | **0** | 0 | **0** |
| `QF_LIA_heavy` | 2 | 0 | 0 | **0** | **0** | 2 | **0** |
| `QF_BV` | 2 | 2 | 2 | **0** | **0** | 0 | **0** |
| `QF_AX` | 4 | 4 | 4 | **0** | **0** | 0 | **0** |
| `QF_S` | 3 | 3 | 3 | **0** | **0** | 0 | **0** |
| **TOTAL** | **23** | **21** | **21** | **0** | **0** | 2 | **0** |

Accounting is complete for EVERY theory: `checked + timeouts + skipped +
unreadable == files total`. The `QF_LIA_heavy` timeout is a RESOURCE LIMIT
(1.6 MB, 13.5 thousand constraints), not a wrong verdict.

### 132.5 PROOF TRACK: the Z3 derivation parsed by our `proof_check.zig`

Seven official `UNSAT` tasks. "Holes" are `hole/trust/sorry` in the derivation;
they are zero EVERYWHERE, and that is the gate's ABSOLUTE requirement.

| Task (official) | Steps | Holes | Trusted | Premises | Verdict |
|:--|--:|--:|--:|:--|:--|
| `QF_LIA/CircularTrains-PT-012/RC-00` | 38 | **0** | **0** | 5/5 | **`[PROOF VERIFIED]`** |
| `QF_LIA/2PhLockVParam/RC-02` | 66 | **0** | **0** | 7/7 | **`[PROOF VERIFIED]`** |
| `QF_LIA/2PhLockVParam/RC-07` | 15 | **0** | 1 | 1/1 | parsed |
| `QF_LIA/2PhLockVParam/RC-08` | 7 | **0** | **0** | 1/1 | **`[PROOF VERIFIED]`** |
| `QF_BV/add_three.4_bit` | **7 616** | **0** | 2 970 | 0/188 | refused (`premises_unbound`) |
| `QF_AX/storeinv_t1_np_nf_ai_00002` | 78 | **0** | 5 | 1/8 | refused (`premises_unbound`) |
| `QF_AX/storeinv_t1_np_sf_ai_00002` | 125 | **0** | 5 | 10/20 | parsed |
| **TOTAL** | **7 945** | **0** | up to 2 970 | — | — |

**Three official `UNSAT` tasks of SMT-LIB are verified with `trusted: 0 |
holes: 0`** — independently of the solver, without a single trusted step. That is
the SMT-COMP Proof-Checking Track result: not "the solver said `unsat`" but "the
derivation was parsed and re-verified".

### 132.6 NATIVE `builtin_lia.zig` WITHOUT Z3 on official QF_LIA

* On the FULL task the solver answers `UNKNOWN` — a **MEASURED BOUNDARY**: the
  budget is `MAX_VARS = 32` while `c_inference` has **302** variables; on small
  official tasks it answers `UNKNOWN rationally satisfiable, no integer point
  found` (Fourier–Motzkin without integer branching).
* Wrong answers: **0** — `UNKNOWN` is an honest "I do not know", not an error.
* A PREFIX PASS yields a non-vacuous positive: on prefixes of official tasks the
  solver returns **SAT points**, and EVERY point is verified INDEPENDENTLY (the
  arithmetic is recomputed in Python against the prefix constraints). MEASURED:
  `violated 0` on every task.
* SOUNDNESS OF THE COMPARISON (and a defect of the gate itself, found by its
  first run): a prefix is a RELAXATION, so a `SAT` on a prefix MUST NOT be
  compared against `:status` (a relaxed system is satisfiable even when the full
  one is not). The first version of the gate reddened with false "FALSE SAT"
  here — fixed and pinned by a meta-test branch.

### 132.7 HONEST BOUNDARIES, STATED

* `trusted == 0` is achieved on **THREE** official `UNSAT` tasks (all `QF_LIA`).
  On `QF_BV` there are **2 970** trusted steps: the checker has **NO** bitvector
  rules (`bitblast`, `bv-*`). That is a capability gap, not a lie: the number is
  printed and the `[PROOF VERIFIED]` label is NOT shown with it (#372).
* Derivations deeper than `MAX_SEXP_DEPTH = 12 288` are refused with an EXPLICIT
  reason. Measured official depths are **4 606 / 13 169 / 200 690**; the stack
  ceiling is **18 432 survives, 19 456 crashes**. Closing the class requires
  ITERATIVE tree traversal — separate work, not present here.
* The native `builtin_lia.zig` does NOT solve official `QF_LIA` tasks in full:
  the `MAX_VARS = 32` budget against 302 variables. The positive result comes
  from PREFIXES (relaxations) and is verified independently.
* `QF_LIA_heavy` (2 files, 1.6 MB) does not solve even in 120 s — the timeout is
  named, not hidden, and the accounting for it is COMPLETE.
* This is a PINNED sample of **23 tasks**, not the full SMT-LIB library (hundreds
  of thousands of files). The numbers refer to it.

### 132.8 Gate, cases and protection against vacuity

`make smtlib-proof-check` = meta-test (**14 branches**) + run. It reddens on: a
`:status` divergence; a false alarm; bank vacuity; a **HOLE** in a parsed
derivation; `[PROOF VERIFIED]` with `TRUSTED > 0` (#372); proof-track vacuity (no
parsed step at all); native-LIA vacuity; a false UNSAT / false witness from the
native LIA; an **unreadable file** and **incomplete accounting** (#373). It does
NOT redden on: `TRUSTED > 0` by itself (the number is published) and a timeout on
a heavy sample (resource limit).

Four non-vacuous can-fail cases: `smtlib-proof-exit`, `smtlib-proof-depth`,
`smtlib-proof-partial`, `smtlib-read-limit`.

## §133. SV-COMP: 4 OFFICIAL CATEGORIES + WITNESS VALIDATION (Executable Harness Witness)

**Date:** 2026-10-27. Gate: `make svcomp-witness-check`
(`tools/svcomp_witness_check.py`).

### 133.1 What existed and what did NOT

`svcomp_baseline.py` (#367/#368) measured **ONE** category
(`signedintegeroverflow-regression`) and printed a matrix. In SV-COMP a verdict
is **NOT counted without a CONFIRMED witness**: the proof that a violation is
reachable must be confirmed by an EXTERNAL validator. KERN had none at all — an
`UNSAFE` verdict was presented without a witness.

### 133.2 How the witness is built (and why it is external)

For every task an **EXECUTABLE HARNESS** is built on the **ORIGINAL**
championship file (copied unchanged — an SV-COMP requirement):

1. our stubs `assert.h` / `harness.c` (`__VERIFIER_*`, `reach_error`,
   `assume_abort_if_not`), declared WEAK so the task's own definition wins;
2. build: `gcc -O0 -g -Wall -Wextra -Woverflow -fsanitize=undefined,address
   -fno-sanitize-recover=all`;
3. **EXTERNAL VALIDATOR #1 — THE COMPILER**: MEASURED that a CONSTANT-FOLDED
   overflow (`int x = 2147483647 + 1;`) is NOT observable at run time — UBSan
   has nothing to check, the compiler already computed the expression. But the
   compiler DOES report it (`-Woverflow`), and that is exactly the external
   evidence SV-COMP requires;
4. **EXTERNAL VALIDATOR #2 — THE RUN** with a witness: nondeterministic inputs
   are fed through `KERN_ND` (comma-separated, the last value repeats), and the
   signal is taken ONLY for the task's OWN property (UBSan for `no-overflow`,
   `REACH_ERROR` for `unreach-call`) — otherwise an `unreach-call` `SAFE` task
   would redden because of an unrelated memory error.

### 133.3 MEASURED: 4 official categories, 37 tasks

| Category | Tasks | UNSAFE | SAFE | SKIP | CONFIRMED | UNOBSERVED |
|:--|--:|--:|--:|--:|--:|--:|
| `signedintegeroverflow-regression` | 15 | 10 | 5 | 0 | **9** | 1 |
| `bitvector-regression` | 10 | 0 | 4 | 6 | — | 0 |
| `loop-lit` | 6 | 1 | 5 | 0 | **1** | 0 |
| `array-examples` | 6 | 4 | 2 | 0 | **1** | 3 |
| **TOTAL** | **37** | **15** | **16** | **6** | **11** | **4** |

**FALSE ALARMS 0** (on 16 `SAFE` tasks none of the enumerated witnesses triggered
the property signal), **NO SHORTFALL**.

Confirmations by method:

| Method | Tasks | Example |
|:--|--:|:--|
| run under gcc sanitizers | **7** | `AdditionIntMin` (witness `-1`, UBSan "signed integer overflow"), `loop-lit/gcnr2008` (witness `-1`, `REACH_ERROR`), `array-examples/standard_init1_ground-1` (the task's own `assert`) |
| compiler diagnostic | **3** | `AdditionIntMax`, `Multiplication-2`, `NoConversion` (`-Woverflow`: "integer overflow in expression … results in «-2147483648»") |

### 133.4 DEFECT #374: our `assert.h` SILENTLY SHADOWED THE SYSTEM ONE — 6 official tasks would not build

**What was broken (measured).** The first version of the harness placed its own
`assert.h` stub next to the task. Some official tasks (e.g.
`array-examples/relax-1.c`) define `reach_error` THEMSELVES via `assert(0)` and
`#include <assert.h>`. Our stub captured the system header and had NO `assert`,
so 6 of 6 `array-examples` tasks reported "build failed" — the category was
VACUOUS, and that was visible only because the gate prints the SKIP reason.

**The fix.** `#include_next <assert.h>` as the FIRST line of the stub: the system
header is pulled in before our definitions. MEASURED after the fix: all 6
`array-examples` tasks build, and `standard_init1_ground-1` gets a
witness-CONFIRMED `UNSAFE` verdict.

**A second consequence, also measured.** Tasks that define `reach_error`
themselves do not print our `REACH_ERROR` — the signal is the failure text of
glibc's `assert`. At the same time `abort()` from `assume_abort_if_not` is NOT a
signal: it prunes an INFEASIBLE branch, it is not a violation. Both halves are
pinned in the code and in the meta-test.

### 133.5 HONEST BOUNDARIES, STATED

* **METHOD BOUNDARY: 4 UNSAFE tasks are UNOBSERVABLE** by either the compiler or
  the run. MEASURED on `signedintegeroverflow-regression/UnaryMinus`: neither
  `gcc -O0/-O1/-O2/-O3` with `-fsanitize=undefined`, nor an EXPLICIT
  `-fsanitize=signed-integer-overflow`, nor `-Woverflow` shows the violation
  (the program prints `2147483625`, rc=0); `clang` is ABSENT from the
  environment. This is NOT declared a false admission (no confirmation was ever
  claimed) and NOT counted as proven — it is printed on its own line.
* **SEARCH BOUNDARY:** the witness space is LIMITED — a constant from
  `{-1,0,1,2,3,5,10,100}` or a PAIR of those. An SV-COMP witness is an automaton
  over the call sequence; there is none here. "No witness found" is NOT a proof
  of unreachability, and the gate does not claim it.
* `SAFE` is NOT proven here: only the absence of a signal over the ENUMERATED
  witnesses is checked (16 tasks, 64 witnesses each).
* KERN verdicts on these categories are only MEASURED (`--xray`), so a wrapper is
  never passed off as a proof: `--xray` produced 10 findings on the overflow
  category and 1 on `bitvector-regression`.
* 6 `bitvector-regression` tasks are marked `SKIP`: their `.yml` carries
  **DIFFERENT** verdicts for different properties, and picking one arbitrarily
  would attribute a verdict the task does not have.

### 133.6 Gate and case

`make svcomp-witness-check` = meta-test (**7 branches**) + run. It reddens on: a
FALSE ALARM (signal on `SAFE`); category VACUITY; a harness that FAILS TO BUILD;
a SHORTFALL (a category with `UNSAFE` where no witness was confirmed). It does
NOT redden on "UNOBSERVED" while confirmations exist — that is a declared method
boundary. Non-vacuous case: `svcomp-witness-drop`.

## §134. THE LIVE-PYTHON ORACLE AGAINST MBPP+: 3 blind spots of EvalPlus itself and two `--xray` defects (#377, #378)

**Date:** 2026-10-27. Gate: `make mbpp-xray-check` (`tools/mbpp_xray_check.py`).

### 134.1 Why a table of tests is NOT an oracle

`EvalPlus (MBPP+)` is the world reference for testing AI code: it expands the base
`MBPP` tests **80x** specifically to catch edge-case bugs. Treating it as an
oracle ("it passed `MBPP+`, so it is clean") is tempting - and WRONG. MEASURED:
on **264** solutions with status `pass/pass` (passed BOTH `MBPP` and `MBPP+`) our
`--xray` pointed at a division by zero, and a **LIVE PYTHON RUN** confirmed it.

The oracle for `[CRASH PATH]` is therefore the **interpreter**:

  * `[CRASH PATH]` + Python crashed  -> **`confirmed_blindspot`** (a real find);
  * `[CRASH PATH]` + Python survived -> **`false_crash_accusation`** (gate failure);
  * `[BOUNDS] … length NOT known`    -> an **informational** line ("could not
    check"), NOT an accusation.

### 134.2 MEASURED: blind spots of MBPP+ ITSELF

| Task | Function | Counterexample | Live Python |
|:--|:--|:--|:--|
| `Mbpp/265` | `list_split(lst, n)` | `n = 0` | **`ZeroDivisionError`** |
| `Mbpp/292` | `find(a, b)` | `b = 0` | **`ZeroDivisionError`** |
| `Mbpp/422` | `find_Average_Of_Cube(n)` | `n = 0` | **`ZeroDivisionError`** |

All three passed BOTH base `MBPP` and the 80x `MBPP+`: the test generator simply
**never supplied zero**. These are not false alarms - they are a benchmark gap.

**A SECOND CONCLUSION, RECORDED AS A NUMBER:** on the **43 SEMANTIC** AI failures
(`base=pass, plus=fail`) the annotation-free `--xray` yields **0** crash paths.
Those bugs return a WRONG NUMBER without crashing the interpreter (`range(k)`
instead of `range(n)`, `x is True` instead of truthiness) - they are caught by the
`@kern:ensures` contract or `--diff-equiv`. The gate never substitutes one for
the other.

### 134.3 DEFECT #377: a false accusation inside `for i in range(n * k)`

**What was broken (measured on `Mbpp/286`).** The x-ray accused `i % n` of
division by zero when `n == 0`, NOT noticing that when `n == 0` the bound `n * k`
is zero, `range(0)` is empty and the loop body is NEVER executed. A live run
shows the function returns `-inf` and does not crash. Class #178/#183.

**The fix is in TWO places, and the second was decisive:**

1. new `_range_entry_guards(...)` - the NON-EMPTINESS guard of `for … in range(...)`;
2. the same guard in `_walk_expr_guarded` - the accusation arrived through the
   `ast.If` descent, which entered the `for` body WITHOUT any entry guard.

**WHY A PRODUCT IS NOT A PROBLEM (`QF_LIA`).** The bound `range(n * k)` is
non-linear and the linear translator will not translate it. The **sound property
of the ring of integers** is used: if `A · B > 0` then neither factor is zero, so
the **linear** conditions `(distinct A 0)` and `(distinct B 0)` are emitted.

### 134.4 DEFECT #378: the loop body was a blind spot of the x-ray

**What was broken (measured).** The `ast.Assign` and `ast.AugAssign` branches did
`continue` immediately after updating the environment - the assignment VALUE was
never crash-walked at all. Measured: `for i in range(3): t += a // n` and
`for i in range(3): x = a // n` produced **0** accusations, while `return a // n`
produced **1**. Any division inside a loop body written as an assignment was
invisible, and "0 findings" meant "we did not look there".

**The fix.** The accusation logic was extracted into `_crash_collect(...)` and is
now called from the assignment branches too - on the value, with path guards.

### 134.5 MEASURED BOTH WAYS (the fix does not silence genuine accusations)

| Input | Accusations | Why that is correct |
|:--|--:|:--|
| `for i in range(n * k): t += arr[i % n]` | **0** | with `n == 0` the bound is zero, there is NO body |
| `for i in range(k): t += arr[i % n]` | **1** | with `k > 0`, `n == 0` the crash is REAL |
| `a // n` outside a loop | **1** | there is no guard at all |
| the real `Mbpp/286` | **0** | the false accusation is gone |
| `for i in range(3): t += a // n` (after #378) | **1** | the loop body is no longer blind |

Existing gates `xray-check`, `xray-overflow-check`, `real-cases-check` stayed
**green**.

### 134.6 Gate and case

`make mbpp-xray-check` = meta-test (**4 branches**) + run. It reddens on a **FALSE
ACCUSATION** (Python survived); a **SHORTFALL OF BLIND SPOTS** (fewer than 3
confirmed - the detector went blind); **VACUITY** (no accusations at all). It does
NOT redden on 0 crash paths among the 43 SEMANTIC failures - that is the boundary
of the annotation-free layer. Non-vacuous case: `mbpp-xray-blindspot` (drops the
accusation emission -> the blind spot is lost -> the gate reddens).

## §135. HONEST BOUNDARY OF `cyberseceval_check.py`: it is a BASELINE, not the KERN core (defect #379)

**Date:** 2026-10-27.

### 135.1 What was established (measured by reading the code, not assumed)

`tools/cyberseceval_check.py` contains **ZERO calls to `kernc` and ZERO calls to
`z3`**. It is a dictionary of AST taint-sink rules and a recall measurement over
Meta's official dataset (`autocomplete.json`) - i.e. an EXTERNAL AST/regex
BASELINE.

### 135.2 Why it was recorded as a defect

The file was named a CWE check and printed percentages that are easy to read as a
KERN result. Same class as #370-#378: the message says something other than what
happened. The file header now names the boundary EXPLICITLY.

### 135.3 Where the REAL CWE verification lives

| Gate | What it does |
|:--|:--|
| `make cwe-twins-check` | `bad`/`good` pairs through contracts and SMT |
| `make svcomp-witness-check` | official SV-COMP tasks + EXTERNAL witness validation (compiler and a sanitized run) |
| `make smtlib-proof-check` | the official SMT-LIB bank and the native proof checker |

### 135.4 Why the file is kept

It is useful as a **reference point**: "how much does a plain regex dictionary
give". Without such a point the gain from the formal core would be
UNMEASURABLE. The `PurpleLlama/.../autocomplete.json` dataset is not in the
repository, so a run requires an external download - and that is stated in the
file header too.

## §136. `--full-scan` RE-MEASURED (defect #380): the documented numbers drifted from reality

**Re-measurement date:** 2026-10-27. Command: `--full-scan .` (the same as in §42).

### 136.1 THE DELTA (the old measurement is NOT rewritten)

| Metric | §42 (old) | §136 (date 2026-10-27) | Δ |
|:--|--:|--:|:--|
| files | 212 | **426** | 2.0x |
| functions | 383 | **1558** (1027 checked) | 4.1x |
| **`--xray` findings** | **6** | **61** | **10.2x** |
| anti-cheat candidates | 259 | **395** | 1.5x |

### 136.2 WHY IT DRIFTED (measured, not assumed)

Part of the growth is the tree itself (212 -> 426 files). But the `--xray` findings
grew **10x while the files grew 2x**: the cause is the **#378** fix (loop bodies
stopped being a blind spot of the x-ray, and our own code has divisions inside
loops). The **engine changed while the number in the document did not**.

### 136.3 WHY NO GATE SAW IT (verified with `grep`)

Neither `tools/check_metrics_consistency.py` nor `tools/metrics_guard.py` mentions
`xray findings` or `full-scan`. The number was measured ONCE and has been
protected by nothing since: it could drift silently - and it did.

### 136.4 HONEST BOUNDARY

A full `--full-scan` takes tens of minutes and does not fit CI, so the FINDING
count remains a **dated measurement**, not a live indicator. Only a CHEAP metric
(the file count) can be live - and that is what a gate should protect.

## §137. PHYSICAL ORACLE FOR ReDoS: NATIVE ANALYSIS VS THE REAL ENGINE (#385)

WHY. Until this step the `redos` family was checked MODEL AGAINST MODEL: `redos.zig`
looks for nested quantifiers and `theory_cli.zig` declares its own output correct.
That is a vacuum — the computer confirms to itself that its formulas are consistent.

WHAT WAS BUILT. `tools/oracle_redos_check.py` + `make oracle-redos-check`: for each
regex the CORE verdict (`kernc theory`) is compared with a REAL `re.fullmatch`
measurement in an ISOLATED process with a hard 8 s timeout. The sentinel is chosen
as an attacker would: `!`, and `\n` for `.`-patterns (`.` does not match it — measured:
`(.*)*` with `!` gives 0.0001 s, with `\n` 1.79 s).

CALIBRATION (measured 2026-10-28, N=24):

| class | slowest | fastest |
|:--|--:|--:|
| safe | 0.0007 s (`(ab|cd)+`) | 0.0000 s (`abc`) |
| vulnerable | 2.1194 s (`(a|a)+`) | 0.9756 s (`(.+)+` with `\n`) |

Separation ~1400×. The 0.2 s threshold is 285× above the slowest safe case and
4.9× below the fastest vulnerable one.
> **Range across runs (re-measured 2026-10-28):** fastest vulnerable `0.98 s`, slowest `2.12 s`; on re-measurement `(.+)+` gave `1.4237 s` instead of `1.44 s`. The stable claims are the **0.2 s threshold** and the `6/3/0/0` count, not the seconds.


RESULT (measured):

| class | count | what confirmed it |
|:--|--:|:--|
| vulnerable CONFIRMED | **6** | the real engine blew up (0.93–1.76 s) |
| safe CONFIRMED | **3** | instant (≤0.0001 s) |
| **FALSE ACCUSATIONS** | **0** | — |
| **MISSES** | **0** | — |
| boundaries (SKIP, fail-closed) | 2 | `(\d+)+`, `[a-z]+` |

DEFECT #385 FOUND BY THIS ORACLE. `parseAtom` supported only `(`, `.` and "any
character as a literal" — so `\d` was read as TWO literals and the analysis ran on a
DIFFERENT regex: `redos (\d+)+` returned `[PASS] PROVEN` while the real Python engine
blows up in 1.44 s. Fixed fail-closed: outside the subset → SKIP with the exact
character instead of a verdict.

WHAT THIS DOES NOT PROVE. (a) The measurement is machine-dependent; (b) nine
class-representative regexes were checked, not "all regexes"; (c) the parser subset
is narrow — character classes and `{m,n}` yield SKIP, not "safe".

## §138. A PHYSICAL ORACLE FOR absint: THE ABSTRACT INVARIANT VS A REAL LOOP (#386)

WHY. The `absint` family was checked MODEL AGAINST MODEL: `abstract_interp.zig`
computes an interval and declares itself correct. That is a vacuum.

WHAT WAS BUILT. The `absint loop <init> <step> <bound>` form in `kernc theory` +
`tools/oracle_absint_check.py` + `make oracle-absint-check`: the abstract invariant
against a REAL loop run in Python.

| loop (init, step, bound) | core invariant | exit | real heads |
|:--|:--|:--|--:|
| (0, 1, 10) | [0, 9] | [10, 10] | 10 |
| (0, 3, 20) | [0, 19] | [20, 22] | 7 |
| (-5, 2, 7) | [-5, 6] | [7, 8] | 6 |
| (0, 1, 1000000) | [0, 999999] | [1000000, 1000000] | **1000000** |
| (-100, 7, -1) | [-100, -2] | [-1, 5] | 15 |
| (100, -1, 50) | [100, 100] | empty | 0 |
| (0, 1, 0) | [0, 0] | empty | 0 |

RESULT: **0 soundness violations** — every invariant CONTAINS all real head values,
and `exit_state` contains the exit value. 5 cases with iterations (non-vacuity),
determinism confirmed (two runs — one interval).

WHAT THIS DOES NOT PROVE. SOUNDNESS is checked, not PRECISION: a wide interval is not
a violation and is reported separately. One kind of linear loop is covered (`x += step`);
non-linear bodies and arbitrary programs are not.

## §139. A PHYSICAL ORACLE FOR CHC/Horn: THE INVARIANT VERDICT VS A REAL LOOP (#387)

WHY. The `chc` family was checked MODEL AGAINST MODEL: `chc.zig` builds a Horn
query, Z3 answers `sat`/`unsat`, and that answer is declared correct.

WHAT WAS BUILT. The `chc <init> <step> <bound> <property>` form in `kernc theory` +
`tools/oracle_chc_check.py` + `make oracle-chc-check`.

KEY POINT: the loop is DETERMINISTIC (`init`/`step`/`bound` fixed), so a single real
run IS its whole trajectory, while the Horn verdict is universal. A mismatch in
either direction is an error.

| loop (init, step, bound) | property | real exit | core | class |
|:--|:--|--:|:--|:--|
| (0, 1, 10) | ge_bound | 10 | sat | confirmed (holds) |
| (0, 1, 10) | lt_bound | 10 | unsat | confirmed (violated) |
| (0, 2, 10) | parity_even | 10 | sat | confirmed (holds) |
| (1, 2, 10) | parity_even | 11 | unsat | confirmed (violated) |
| (5, 1, 10) | le_init | 10 | unsat | confirmed (violated) |
| (100, 1, 50) | ge_bound | 100 | sat | confirmed (holds) |
| (0, 1, 10) | le_init | 10 | unsat | confirmed (violated) |

RESULT: 3 `sat` and 4 `unsat` agree with the real loop exit value,
**0 false proofs, 0 false alarms**. selftest 13/13.

WHAT THIS DOES NOT PROVE. One kind of loop and 4 named properties — not arbitrary
Horn systems. AGREEMENT between verdict and execution is checked, not the quality of
the invariant: a confirmed `sat` does not prove the invariant is stronger than needed.

## §140. A PHYSICAL ORACLE FOR PATHS: THE KERNFS SANITISER VS THE REAL FILESYSTEM (#388)

WHY. The `strings` family was checked MODEL AGAINST MODEL: `string_theory.zig` builds
an SMT query, `validatePath` returns a verdict, and both are declared correct.

WHAT WAS BUILT. The `strings path <path>` form in `kernc theory` + `tools/oracle_string_check.py`
+ `make oracle-string-check`. A **canary OUTSIDE the root** is created in a sandbox,
and for every path a REAL `open(root + path)` is attempted (naive concatenation).

| path | core | escape (naive) | what the FS said | class |
|:--|:--|:--|:--|:--|
| `/ok.txt` | accept | no | opened, `inside` | CONFIRMED_ACCEPT |
| `/sub/ok.txt` | accept | no | opened, `nested` | CONFIRMED_ACCEPT |
| `/../secret.txt` | reject (PathTraversal) | **YES** | **opened, `CANARY`** | CONFIRMED_BLOCKED |
| `/sub/../../secret.txt` | reject (PathTraversal) | **YES** | **opened, `CANARY`** | CONFIRMED_BLOCKED |
| `/..` | reject (PathTraversal) | YES | IsADirectoryError | CONFIRMED_BLOCKED |
| `//etc/passwd` | reject (InvalidFormat) | no | FileNotFoundError | STRICTER_THAN_NEEDED |
| `/./ok.txt` | reject (InvalidFormat) | no | opened, `inside` | STRICTER_THAN_NEEDED |
| `/sub/` | reject (InvalidFormat) | no | IsADirectoryError | STRICTER_THAN_NEEDED |
| `/a\x00b` | reject (InvalidFormat) | no | `embedded null byte` | STRICTER_THAN_NEEDED |
| longer than PATH_MAX | accept | no | OSError (ENAMETOOLONG) | CONFIRMED_ACCEPT |

RESULT: **3 escapes blocked LOAD-BEARINGLY** (the canary outside the root was really
read), **3 paths accepted and stayed inside**, **0 false accepts**.

DISTINGUISHING "STRICTER" FROM "WRONG": 4 rejected paths with no escape are a
canonical-form policy (STRICTER_THAN_NEEDED), NOT a false alarm.

HONEST BOUNDARY. `validatePath` is a LEXICAL validator of the KERNFS namespace; it
does not resolve HOST symlinks because KERNFS serves an in-memory image. The "symlink
inside the root points outside" case is shown separately and is not part of the
differential: it is another layer.

## §141. A PHYSICAL ORACLE FOR NON-INTERFERENCE: THE MODEL VS REAL TIME (#389, step D)

### 141.1 WHY

The `noninterference` family (2-Safety, hyperproperties) was checked MODEL AGAINST
MODEL: an IR taint analysis declared that branching on a secret is a leak and that
`constantTimeEqual` is not, and this was taken on trust. Vacuum: nobody compared the
model's claim with PHYSICAL execution time.

### 141.2 WHAT WAS BUILT

1. **Static layer.** `kernc theory` gained the form `nonint <instructions>`
   (S/P/A/B/M/T/C) — 11 fixtures: 4 leaks refuted with the kind named (`branch`,
   `memory_index`, `variable_time`, taint via `assign`), 4 safe proven, 3 unsupported
   yielding SKIP with NO verdict (fail-closed).
2. **Physical layer.** The probe `src/verifier/nonint_timing_probe.zig` calls the REAL
   `constantTimeEqual` and `earlyExitEqual` on a 4096-byte secret differing at
   different positions (1 vs 4096) and prints the ratio of MINIMA over N=1000 runs.
3. **Reconciliation.** The model's verdict is read FROM THE KERNEL; a mismatch is
   classified as MISSED or FALSE ALARM (both forbidden).

### 141.3 MEASURED

| Quantity | Value | Threshold | Margin |
|:--|--:|:--|:--|
| `CT_RATIO` (constant-time) | **1.0003** (1.0025 / 1.0007 / 1.0052) | < 3.0 | 3x |
| `EE_RATIO` (early exit) | **68.80** (60.6 / 62.1 / 68.8) | >= 10.0 | 6.9x |

> **Range across runs (re-measured 2026-10-28):** `CT_RATIO` 1.0003-1.0035, `EE_RATIO` 68.80-86.81. The stable claims are the **thresholds** (`< 3.0`, `>= 10.0`) and the classification, not the ratios themselves.

At 16 bytes the signal DROWNED in timer overhead: measured `CT_RATIO=1.00`,
`EE_RATIO=1.20` — the secret length was chosen BY MEASUREMENT, not by eye.

Classes: `CONFIRMED_SAFE` and `CONFIRMED_LEAK` — both present, 0 MISSED, 0 FALSE ALARMS.

### 141.4 HONEST BOUNDARIES

* This is a **STATISTICAL oracle**: it measures REAL time, is subject to OS scheduler
  noise (hence min-of-N and a generous threshold) and is **not claimed as a proof of
  non-interference**.
* It measures the difference between TWO implementations, not the absence of leaks in
  an arbitrary function.
* The model (IR) and reality (Zig) are linked by a **described correspondence**, not by
  automatic translation of code into IR.

### 141.5 DEFECT #390 (found while wiring)

`toks()` silently truncated a specification line longer than 16 tokens and a verdict
was issued for the TRUNCATED line; the SKIP reason named a reason that was NOT the
real one. Fixed: the token count is computed before parsing; above 16 the line gets
SKIP "no verdict (fail-closed)".

### 141.6 ENVIRONMENT TRAP (measured)

`ziglang` from pip in `.venv/bin` is a DIFFERENT Zig (no `std.Io`). The oracle picks the
compiler BY VERSION (`0.17`), excludes `.venv/bin`, and prints the chosen path.

### 141.7 CAN-FAIL

The `oracle-noninterference-missed` case disables registration of the variable-time
leak: the model says "no leaks" while the live measurement shows 62x -> MISSED ->
`oracle-noninterference-check` goes red. Oracle meta-test: 14 branches; `--selftest` 14/14.

## §142. TWO DEFECTS OF ONE CLASS: THE LABEL LIED, THE REFUSAL BLAMED OUR CODE (#391, #392)

Both defects are about **a message that says something other than what happened** —
the same class as #370/#377/#378/#381. Both were found by CHECKING already
published numbers and commands against actual behaviour, not by reading code.

### 142.1 The verdict label named the DIVIDEND (#391)

| What | Value |
|:--|:--|
| Symptom | on `a // b` the verdict line said "divisor: **a**" — the DIVIDEND |
| Verdict and counterexample | were **correct** — only the label lied |
| Cause | the collector tuple is `(numerator, divisor, guards)` (since #334), but the printing took `d[0]` = the numerator |
| Fix | the existing helper `_divisor_of(d)` in both places |
| Second, latent | `_drop_macro_divisors` filtered by the NUMERATOR: on `Path / name` (#381) it checked `Path`, not `name` |
| Gate | `div_guards_check.py` asserts the real divisor in the label plus the non-vacuity of that assertion |

### 142.2 A refusal caused by a wrong compiler blamed our `build.zig` (#392)

| What | Value |
|:--|:--|
| Condition | pip package `ziglang` **0.13.0** in PATH (it lives in `.venv/bin` ON PURPOSE — for `portable-bench`) |
| Symptom | `make build` failed with an error INSIDE our code: `build.zig:12:54: error: no field named 'root_module'` |
| Cost | **59 targets** depend on `build`, including the showcase |
| Measured on the showcase | with pip-Zig: `showcase-live` — **7 rows, 4 failures**, each reading as a defect in our code |
| Fix | the `zig-guard` target compares `$(ZIG) version` with `0.17`; on mismatch `[ОТКАЗ]` with the program NAME and required version, rc=2; wired into 10 targets that call Zig directly |
| Measured after | correct Zig -> rc=0; pip-Zig -> `[ОТКАЗ]` rc=2 and **zero** `no field named` lines; Zig absent -> also `[ОТКАЗ]` rc=2 |
| Showcase after | `showcase-live` — **7 rows, 0 failures** |
| Gate | `make zig-guard-check` — three outcomes, two-sidedly: "the build failed" is NOT a named refusal, so `no field named` is forbidden separately |
| Case | `zig-guard` (rc=2 in 1 s): removing the guard from `build:` must turn the gate red |

## §143. A PROOF WITHOUT REPRODUCTION: TWO FOREIGN DEFECTS ARE NOW CHECKABLE FROM THE REPOSITORY (#393)

### 143.1 WHAT WAS WRONG

Two of the ten proofs (`docs/TEN_PROOFS.md`) had only a REFERENCE TO A SNAPSHOT:
`docs/evidence/example_why_kern/lcm.log` and
`docs/evidence/thealgorithms_rust/binomial_coefficient.rs`. A reader could not
verify the claim - only trust the snapshot. For Rust the shadow contract
`binom_step.rs` DID exist in the repository, but no command printed the verdict;
for C the shadow file did not exist at all.

### 143.2 WHAT IT IS NOW (MEASURED)

| File | Command | Verdict |
|:--|:--|:--|
| `docs/evidence/example_why_kern/lcm_numerator.c` | `python3 tools/kern_contracts.py <file>` | `[BV]` -> `[FAIL] lcm_numerator` + `[КОНТРПРИМЕР] a = #x643b3fbb, b = #5a724dfe, result = #x643a7a8a` (matched the snapshot) |
| `docs/evidence/thealgorithms_rust/binom_step.rs` | same | `[FAIL] binom_step: ПЕРЕПОЛНЕНИЕ типа u64` + `[КОНТРПРИМЕР] result = -1, k = 2, i = 1, n = 0` |
| `docs/evidence/example_why_kern/lcm_numerator_guarded.c` | same | `[PASS] ДОКАЗАНО` (same body, honest bounds) |
| `docs/evidence/thealgorithms_rust/binom_step_guarded.rs` | same | `[PASS] ДОКАЗАНО` (same body, `i <= n`) |

### 143.3 WHY THE CHECK IS TWO-SIDED

"REFUTED" alone proves nothing: a broken tool can produce it too. So guarded twins
with the SAME body sit next to the unguarded ones, and they must be PROVEN. If both
variants are proven, the refutation above was not about overflow, and the gate goes red.

### 143.4 THE GATE `make foreign-verdicts-check`

It checks the CLASS, not exact values: a violation + an exhibited counterexample +
`ЛОЖНЫХ ТРЕВОГ 0` + the named theory (`[BV]` for nonlinear multiplication), plus both
twins being proven. **Exact model values are NOT asserted** - the solver changes its
model between Z3 versions (lesson of #371), so pinning them would make the gate flaky.

The `foreign-verdicts` case (rc=1 in 4 s) replaces `requires` with the guarded
variant - the gate must go red.

## §144. A GAP BETWEEN GUARDS: `sync-check` GREEN WHILE THE NUMBER WAS STALE (#394)

Found on our own handoff document - which is why it is instructive.

### 144.1 WHAT HAPPENED

`docs/NEXT_SESSION.md` (the session handoff) has a facts block WITH anchors, and
below it a table whose numbers were BARE:

```
| Registry | 233 targets · **179/179 CHECK** · 217 non-vacuous cases |
```

After the `foreign-verdicts-check` target was added the facts became `234 / 180 /
218`, and this row did not.

### 144.2 WHY IT MATTERS: THE GUARD WAS GREEN

| Guard | What it checks | Verdict in that state |
|:--|:--|:--|
| `make sync-check` | only `fact:` ANCHORS | **green** - the anchors were fresh |
| `make claims-audit` | EVERY number in tracked files | **red** - caught the stale row |

So a file listed in `SURFACES` can carry a stale bare number, and the anchor guard
cannot see it by construction.

### 144.3 THE FIX - ANCHORS, NOT A NUMBER EDIT

The row was rewritten so that `make sync` updates it. Substitution in `sync_state`
is global (`ANCHOR.sub`), so two identical anchors on one line (for the `N/N` form)
are safe.

### 144.4 THE BOUNDARY, STATED PLAINLY

`claims-audit` is in the FULL contour (`tools/ci.sh:188`) but **not** in `ci-fast`.
So a bare number in a file listed in `SURFACES` can drift until the full run. This
is recorded as a known boundary: adding `claims-audit` to the fast contour is a
separate decision (it scans every tracked file and is therefore slower).

## §146. THE DOCS MAP WAS NOT CHECKED BY ANYTHING (DEFECTS #402, #403, #404)

Measured 2026-10-28 while answering "is everything documented locally".

**#402 — A GLUED ROW.** Line 29 of `docs/README.md` carried TWO table rows merged
into one via `||` (a full copy of itself: `ATTESTATION_PASSPORT.md` appeared 4
times in a single line). The reader saw a duplicate; no gate saw anything.

**#403 — 25 DOCUMENTS OUTSIDE THE MAP.** Checking `docs/*.md` (76 files) against
the map found 21 key documents with no mention at all: `CAPABILITY_MATRIX(.ru)`,
`CORPORA(.en)`, `TEN_PROOFS(.ru)`, `CHARTER(.ru)`, `SEMVER`, `NEXT_SESSION(.ru)`,
`CONTRACT_ANY_PROJECT`, `EXAMPLE_WHY_KERN(.ru)`, `SHADOW_AUDIT_EXAMPLE`,
`REAL_WORLD_CAPABILITIES(.ru)`, `REAL_WORLD_MEGATEST`, `CWE_COVERAGE(.ru)`,
`AI_TRAPS_SHOWCASE(.ru)`, `HIGH_STAKES_USE_CASES`, `SELF_VERIFICATION(.ru)`,
`LIVE_MODEL_EVAL`, `LIVE_BUGS_DISCOVERED`, `REAL_BUGS_FOUND`,
`ALL_CAPABILITIES_LIVE_GUIDE(.ru)`, `STATUS(.ru)`, `INTUITIONISTIC_DESIGN`. The
gate added **4 more**: `CAPABILITY_STATUS(.en)` - the defect journal itself!,
`PROJECT.md`, `CYBERNETIC_VISION.md`, `OWNERSHIP.md`.

**#404 — STALE SECTION RANGES.** The map promised `§1–§149` for `METRICS.md`
(fact §167) and `§1–§151` for `METRICS.en.md` (fact §145).

**FIXED:** the glued row split; sections "Proofs and presentation" (17 rows) and
"Charter, policy and plans" (4 rows) added; ranges brought to the fact.

**NEW GATE `make docs-map-check`** (`tools/docs_map_check.py`), three rules:
  * **R1** - every `docs/*.md` is MENTIONED in the map as `](NAME)` or declared in
    `EXEMPT` with an explicit reason (a stale exemption is itself a defect);
  * **R2** - every map link points to an existing file;
  * **R3** - no table row contains `||` (the signature of a glued row).

**MEASURED:** `76 docs in docs/, 20 exemptions with reasons, links resolve, no
glued rows` (rc=0). Meta-test - **3 of 3 corruptions caught** (new doc outside
the map / `||` glue / link to nowhere). Case `docs-map-gap` (drop a link while
keeping the file) - **PASS, non-vacuous, rc=2 in 0 s**.

**Honest boundary:** the gate checks the PRESENCE of a mention, not the accuracy
of the description - a description is prose and cannot be checked by machine.

**A guard fired:** the first case run failed with `docs/README.md missing from
FAULTABLE - the edit will NOT be reverted!` (class #48/#225) - the file was added
to `FAULTABLE` with a comment.

---

## §145. C-like `--xray` SKIP-REASON HISTOGRAM (DEFECTS #400, #401)

**Why.** Step 2.1 of the plan required measuring WHY `--xray` skips functions in
third-party C repositories. Without it, widening the parser would be guesswork.

**What was found.** The summary claimed "skipped N with explicit reasons" while
printing NO reasons at all (`_xray_clike_file` did not return them) — defect #400.
After the fix the histogram is printed and its sum matches the counter on both
corpora.

### 145.1 Measured (corpora pinned by SHA)

| Corpus | SHA | Files | Checked | Skipped | Reasons (all, descending) |
|:--|:--|--:|--:|--:|:--|
| `github/cmark-gfm/src` | `27d942c8` | 48 | 76 / 308 | 232 | `no if conditions` 124 · `syntax after translation` 53 · `nil/null` 49 · `binary operator` 4 · `no reason` 2 |
| `actions/toolkit/packages` | `0c3a9c33` | 159 | 58 / 458 | 400 | `no if conditions` 336 · `syntax after translation` 54 · `ternary without «…»` 6 · `nil/null` 3 · `no reason` 1 |

The sum of reasons equals the skip counter in both cases (232 = 232 and 400 = 400).

### 145.2 What this means for step 2.2

The top-3 reasons account for **93–95 %** of all skips:
1. **no `if` conditions in the body** (124 / 336) — nothing for the X-Ray to check;
   this is NOT a loss but an honest boundary (no branches — nothing to look for);
2. **syntax after C-like translation** (53 / 54) — the condition was translated into
   Python-like text and failed to parse; this is where widening pays off;
3. **`nil`/`null`** (49 / 3) — pointer comparisons outside the Int model.

### 145.3 DEFECT #401: FALSE `[DEAD BRANCH]` ON MUTUALLY EXCLUSIVE BRANCHES

On the real `cmark-gfm/src/utf8.c` the X-Ray produced **4 `[DEAD BRANCH]` findings**,
and all four were FALSE: their conditions contain constants (`(= 0 0)`).

**Root cause.** `if_derived` accumulated `(not cond)` for EVERY exited block without
distinguishing branches. For `if (A) { if (B) return; } else if (C) { if (D) return; }`
that yielded BOTH `not B` and `not D`. In `utf8.c`, `B` and `D` are opposites
(`str1 >= 160` and `str1 < 160`), so the path became **UNSAT** and EVERY later
condition was declared dead.

**Fixed.** `_clike_conds_at` is nesting-aware: `(not cond)` applies only when the
position is IN THE SAME BRANCH. `if_derived` was removed; `if` reachability is
checked POSITIONALLY.

**Two-sided:** mutually exclusive branches -> **0 findings** (was 4); a genuinely
dead condition -> the finding **IS** there (not silent suppression).

**Effect:** `cmark-gfm/src` findings **4 -> 0** with unchanged coverage 76/308.

## §147. TACK 2.2 PLAN: FOUR MEASURED ANSWERS AND TWO OPEN DEFECTS (#405, #406)

Basis: `docs/PLAN_takt22.md` (+ `.ru.md`). Base commit `08eb5cd`. Both corpora are
pinned by SHA in `~/.cache/kern/repos/`, so "before/after" is measured on
identical bytes.

### 147.1 The funnel is understated: functions WITHOUT `if` ARE checked (#405)

A live `--xray audits/codecheck` run prints `функций проверено 7 / 16` and, in the
same summary, `skip: нет условий if в теле` — while `audits/codecheck/c_unguarded.c`
holds `int ratio(int a, int b) { return a / b; }` (ZERO branches) and yields
`[CRASH PATH] ratio: возможно деление на ноль: b == 0`, and
`audits/codecheck/rust_overflow.rs` with `pub fn add32(a: i32, b: i32) -> i32 { a + b }`
yields `[OVERFLOW PATH]` with a counterexample. Both are counted as `skipped`.

Cause: the obligation detectors run unconditionally, while the `checked` counter
grows only when `proven > 0` — that is, only when a TRANSLATABLE `if` exists.
So the summary is understated and hides the fact that analysis ran. Defect #405.

### 147.2 The real funnel over functions WITH BRANCHES

The "no `if` conditions" bucket is not a parser failure: those functions have no
branches. Subtracting them gives an honest denominator: C — 184 functions with
branches (76 checked, 41 %), TS — 122 (58 checked, 48 %).

### 147.3 The `§N` ranges in the map drift with no rule R4 (#406)

`tools/docs_map_check.py` has R1/R2/R3 and not a single rule comparing section
ranges. Measured: the map says `§1–§167` while the real maximum is §168, and
`§1–§145` while the English mirror reaches §146. So defect #404 was closed for
exactly one commit.

### 147.4 Bitwise conditions — 21 in `cmark-gfm/src`

Measured: 21 conditions of the form `if (ident & CMARK_OPT_*)`, plus `|`, `^`, `~`.
Four fired (for the rest the first reason differs). Translating such conditions to
Int is UNSOUND: `& | ^ << >>` over unbounded integers is not the same as over
machine types; the BV mode is required (the same one used for non-linear
multiplication).

## §148. TACK 2.2, RE-MEASUREMENT BEFORE STEP 1: THE HISTOGRAM, AN EMPTY BUCKET, AND Z3 WITHOUT WHICH THE X-RAY GOES SILENT (#407)

> Measured at `d98953c` (clean tree, `HEAD == origin/main`). Corpora pinned by SHA:
> `cmark-gfm` `27d942c8`, `actions/toolkit` `0c3a9c33`; both clones clean
> (`git status --porcelain` empty). All runs are read-only — the tree is clean
> afterwards too. Runs were made BOTH without Z3 and WITH Z3 (`.venv/bin`), so that
> a property of the code is not confused with a property of the environment.

### 148.1 The plan's §0 histogram does NOT reproduce: the "no reason" bucket is empty

| Corpus | plan §0 | measured (4 runs, deterministic) |
|:--|:--|:--|
| `cmark-gfm/src` | no `if` **124** · syntax 53 · `nil/null` 49 · binary 4 · **no reason 2** | no `if` **126** · syntax 53 · `nil/null` 49 · binary 4 · **no reason 0** |
| `toolkit/packages` | no `if` **336** · syntax 54 · ternary 6 · `nil/null` 3 · **no reason 1** | no `if` **337** · syntax 54 · ternary 6 · `nil/null` 3 · **no reason 0** |

The sums and the headline numbers MATCHED: `232` and `400` skips, `76 / 308` and
`58 / 458` checked. Only the ATTRIBUTION of three functions differs: those the plan
recorded as "no reason" measure as "no `if`". The "functions WITH branches"
denominator therefore differs too: C **182** (76 = 41.8 %), TS **121** (58 = 47.9 %)
— the plan said 184 and 122.

**Consequence for step 3.** The acceptance of step 3 ("`no reason: 0` on both
corpora") is ALREADY satisfied, before any edit: the bucket is empty in four runs
out of four. As written, step 3 is a VACUOUS green — exactly what rule 6 of the
tack forbids. The dump (`print` of the name, `len(_ifs)`, `skip_why`) stays
meaningful only as a CONDITIONAL action: it is needed if the bucket reappears, not
as an unconditional step.

### 148.2 The evidence for #405 reproduces EXACTLY — but only with Z3

`python3 tools/kern_contracts.py --xray audits/codecheck`:

| Environment | `[REPO SUMMARY]` | Findings |
|:--|:--|:--|
| without `.venv/bin` in PATH | `16 files \| checked 7 / 16 (skipped 9) \| findings 0` | NONE, and not a single warning |
| `PATH="$PWD/.venv/bin:$PATH"` | `16 files \| checked 7 / 16 (skipped 9) \| findings 4` | `c_unguarded.c: [CRASH PATH] ratio: division by zero: b == 0`, `rust_overflow.rs: [OVERFLOW PATH] add32: … b = 2147483647, a = 1`, plus `rust_allman.rs` and `zig_div.zig` |

Cause: `kernc` prints `[!] z3 недоступен. Добавьте .venv/bin в PATH
(uv pip install z3-solver)`; `_smt_verdict` classifies that as `unknown`,
`_smt_sat` returns `None`, and the detectors claim nothing. A preflight exists in
`_demo` (`:4028-4030`) and on the contract path (`:4448`) — `--xray` has none.
This is recorded as defect **#407** (class #277/#184).

**A side symptom.** Without Z3 the tool prints `[!] пропусков БЕЗ записанной
причины: -6` (`:5655-5657`): `named` = 15 (9 "no `if`" + 6 "branch N not solved by
the solver" from the XRAY summary) versus `skipped` = 9 at REPO level. A negative
"number of skips" is a defect of the message; with Z3 the branches are solved and
the line disappears.

### 148.3 #406 recurred IN THE VERY COMMIT that recorded it

Measured at `d98953c`: the map `docs/README.md` says `§1–§167` while the real
maximum is **§169** (line 44) and `§1–§145` while **§147** (line 34). The drift grew
in exactly the commit that recorded #406 as open — that is, #404 recurred for the
THIRD time. This is the price of the missing rule R4.

### 148.4 What of the checked material DID match the plan (so it is not re-checked)

The #405 code anchors are accurate: `:6809` calls the detectors, `:6814` is
`if proven:`. The #405.3 safeguard is accurate: the fixture
`tools/xray_skip_reasons_check.py:53` holds `int plain(int n) { return 42; }`, and
the threshold `skipped >= 2` is at `:65`. Bitwise conditions in `cmark-gfm/src` are
indeed **21** (§1.4). Gates at `d98953c` are green: `docs-map-check` (78 docs,
21 exemptions), `sync-check`, `docs-parity` (21 pairs), `journal-parity`
(RU 366 == EN 366), `status-check`.


## §149. THE `--xray` FUNNEL UNDER KERN'S OWN CONTRACT: A SPECIFICATION PROVED BY KERN ITSELF (#405/#407.2)

> Decision of tack 2.2: the accounting invariant of the funnel no longer rests on
> good faith and is no longer guarded by a separate Python watchman — it is written
> as `# @kern:requires` / `# @kern:ensures` and proved by THE SAME ENGINE with which
> the project checks foreign code. The precedent is inside the project:
> `charter/laws.py` ("the project's laws, written as ordinary `@kern:` contracts so
> that the same engine proves them").

### 149.1 What was MEASURED before writing (four probes)

| Probe | What was tested | Result |
|:--|:--|:--|
| A | `unexplained = skipped - named` WITHOUT the precondition `named <= skipped` | 🔴 **REFUTED**: `[КОНТРПРИМЕР] result = -1, named = 1, skipped = 0`, `[RUNTIME CONFIRMED]` |
| B | the same WITH the precondition | ✅ **PROVED**: `[PROOF VERIFIED] steps: 50 \| premises bound: 3/3 \| trusted: 0 \| holes: 0` |
| C | the relational invariant `result + trivial + skipped == total` as the `ensures` of a SCALAR function | 🔴 **FALSE ACCUSATION**: counterexample `total = 0, trivial = 1` on a CORRECT function — the inputs are free, and `ensures` cannot state a relation BETWEEN them |
| D | a tuple as the result (to return three buckets from one function) | `SKIP — узел Tuple`: the engine does not support it |

Probe C is a boundary, not a detail: "just wrap the invariant in `ensures`" yields a
false accusation rather than protection (class #317/#349). The relation is therefore
expressed by the function `unaccounted`, and the GATE requires its value to be zero
on the real numbers.

### 149.2 What was done

* `tools/funnel_accounting.py` — four pure functions with contracts:
  `branches_denominator` (the "functions with branches" denominator),
  `unexplained_skips` (the guard against `-6`), `funnel_total` (the pin for #405:
  checks WITHOUT `if` ARE counted as checked), `unaccounted` (the remainder must be
  zero). Each refuses a precondition violation at RUNTIME too (`raise`), not only in SMT.
* `tools/funnel_contract_check.py` — a gate with four properties: (1) all four
  specifications are PROVED; (2) weakened twins MUST be refuted (otherwise the proof
  is vacuous); (3) the invariants hold on the measured corpus numbers; (4) the file is
  sealed in `docs/contracts.lock.json` and unchanged. Without a solver — `rc=3` and NO
  green: "the tool did not run" is N, not T (#407).
* Lock: 8 fingerprints (`fn:requires:hard` / `fn:ensures:hard`).
* Invocation: from inside `tools/xray_check.sh` (target `make xray-check`) — the SAME
  pattern as the #400 sub-gate (`xray_skip_reasons_check.py`). A new CHECK target is
  deliberately NOT created: an `--xray` sub-gate is part of the `xray-check`
  acceptance, and the registry counts must not grow for it. Non-vacuity is provided by
  the gate's OWN meta-test (twins must be refuted, forged verdicts must be rejected),
  not by a canfail case.

### 149.3 Measured by the gate (rc=0)

```
[OK] спецификация воронки ДОКАЗАНА: 4 функций, нарушено 0, нерешённых 0, вакуумных 0
[OK] двойник опровергнут (снята предпосылка `named <= skipped`): [КОНТРПРИМЕР] result = -1, named = 1, skipped = 0
[OK] двойник опровергнут (забыт `checked_arith_only`): [КОНТРПРИМЕР] trivial = 0, skipped = 0, checked_arith_only = 1, result = 0
[OK] cmark-gfm/src: знаменатель с ветвлениями 182, корзины сходятся (76+0+0+232=308), без причины 0
[OK] toolkit/packages: знаменатель с ветвлениями 121, корзины сходятся (58+0+0+400=458), без причины 0
[OK] смешанные единицы (9, 15) отвергнуты спецификацией: нарушена предпосылка named <= skipped
[OK] замок цел: 8 отпечатков контрактов tools/funnel_accounting.py не изменены
```

Harness: deliberately not added (see above) — non-vacuity is checked on EVERY run by
the gate itself: `[OK] двойник опровергнут` ×2 and `--selftest` with five forged
verdicts. The registry did NOT change: 222 cases, 182/182 CHECK.

### 149.4 Honest boundaries (they must not be silenced)

* The specification is sealed, but `--xray` ITSELF is not yet wired to it: separating
  FUNCTION-level reasons from BRANCH-level ones (`kern_contracts.py:4857`/`:4865`
  versus the counter at `:7354` and the scraper at `:7604–7612`) is the next sub-step
  of step 3. Until then this is a LOCK ON THE SPECIFICATION, not a guard on the tool.
* The corpus numbers in the gate are a FIXTURE measured at `d98953c` (corpora pinned
  by SHA). A live run is deliberately not used: without a solver it returns zeros, and
  the gate would become non-deterministic.
* A lesson in self-checking: a hand-RETYPED sample of the ИТОГО line repeated the
  pattern's error (the doubled "У" in ВАКУУМНЫХ was read as one), and a PROVED
  specification was reported as unproved. Hence the sample in the gate is the VERBATIM
  tool output, and the parser matches the tail "МНЫХ". A self-check against one's own
  retelling cannot catch an error the retelling introduced.


## §150. THE FUNNEL IS WIRED TO THE SPECIFICATION: BELNAP GATE AND UNIT SEPARATION (#407, CLOSED)

> Sub-step 3.2 of tack 2.2. §149 sealed the SPECIFICATION; here the tool itself is brought
> to it, and defect **#407** is closed. Only **#405** (step 2: three buckets) stays open.

### 150.1 Belnap gate: "the tool did not run" no longer looks like "clean"

`cmd_xray` calls `_xray_solver_gate(kernc)`: if `kernc` answers "z3 недоступен", it prints an
explicit `this is N(0,0) by Belnap, not «0 findings»` and returns **rc=2**. MEASURED by
stubbing the solver answer (`run_kernc` → the "z3 недоступен" line): `rc = 2`, the message is
printed. Previously this place printed `0 findings`.

### 150.2 Solver auto-pickup: the false zero is gone from MANUAL runs

`_solver_env()` prepends the directory holding `z3`, found NEXT TO `sys.executable` (and the
project's `.venv/bin`), to PATH for EVERY `run_kernc` call. MEASURED in a shell WITHOUT
`.venv/bin`: `python3 tools/kern_contracts.py --xray audits/codecheck` reports
**`4 findings`** and `checked 7 / 16 (skipped 9)`, whereas before the fix the same call gave
`0 findings` with no warning at all. Side effect: `make bounds-check`/`loop-check` are green
with `ZIG=<0.17>` and without `.venv` in PATH — the solver is found by itself.

### 150.3 Units separated — the root of `-6`

| Where | Before | After |
|:--|:--|:--|
| Python path, skip list | ONE list `skipped`: functions AND branches | `fn_skipped` (functions) and `notes` (branches) |
| Printing | everything under the `skip:` label | functions — `skip:`, branches — `note:` |
| Scraper `_xray_repo` | branches landed in `all_reasons` | `all_reasons` (functions) and `all_notes` (branches) |
| The difference | `skipped - named` (branches minus functions → `-6`) | computed by the SEALED spec `funnel_accounting.unexplained_skips`; a precondition violation prints "NOT A NUMBER" |

The dimension check is now NON-VACUOUS and deterministic: the Python fixture

```python
def g(x):
    if x > 0:
        if is_ok(x):
            return 1
    return 0
```

yields a branch note (a nested CALL condition is outside the subset) at `skipped 0` — exactly
the state that used to print `-1`. No solver is needed to reproduce it. Measured by the gate:
`[PASS #407.2] заметок уровня ВЕТКИ 3, пропусков функций 0, отрицательной разницы НЕТ`. The
gate's meta-test grew to **5 branches** and rejects the VERBATIM "before" output (it contains
the negative difference) — had it accepted it, the check would prove nothing.

### 150.4 What stays outside the boundary

* **#405 is open** (plan step 2): the buckets `checked` / `trivial` / `skipped` are not split
  yet, so functions without `if` are still counted as skipped although their arithmetic IS
  checked. The invariant is already sealed (§149), so the edit will proceed under contract.
* The corpus numbers in the §149 gate are a FIXTURE at `d98953c`, not a live run.
* The C-like path (`_xray_clike_file`) was not touched: units never mixed there — exactly one
  reason per function.


## §151. THREE BUCKETS IN THE `--xray` FUNNEL: AN HONEST LABEL INSTEAD OF AN UNDERSTATED COVERAGE (#405, CLOSED)

> Step 2 of tack 2.2. The funnel is split by the ACTUAL WORK of the solver, not by the
> presence of `if`. Defect **#405** is closed; the journal has **zero** open defects.

### 151.1 What exactly was counted wrongly

| Bucket | Definition |
|:--|:--|
| `checked` | the solver REALLY ran (there were obligations: division, bounds, overflow, branch reachability) |
| `trivial` | the function was parsed but has NO obligations — there is nothing to check |
| `skipped` | the function was NOT analysed (condition outside the subset, `nil/null`, bitwise operator, syntax) |

Before the fix `checked` grew only when `proven > 0`, i.e. by the number of TRANSLATABLE `if`s,
and `trivial` did not exist at all: a function without `if` landed in `skipped` although its
arithmetic WAS checked (the live evidence of #405: `ratio` and `add32` produced findings and were
counted as skipped).

### 151.2 MEASURED before/after on the SHA-pinned corpora (identical bytes)

| Corpus | BEFORE | AFTER |
|:--|:--|:--|
| `cmark-gfm/src` (`27d942c8`) | `checked 76 / 308 (skipped 232)` | `checked 76 \| trivial 126 \| skipped 106 \| Σ 308 == total 308` |
| `toolkit/packages` (`0c3a9c33`) | `checked 58 / 458 (skipped 400)` | `checked 58 \| trivial 337 \| skipped 63 \| Σ 458 == total 458` |
| `audits/codecheck` | `checked 7 / 16 (skipped 9)`, 4 findings | `checked 13 \| trivial 3 \| skipped 0`, 4 findings |

### 151.3 AN HONEST BOUNDARY: `checked` did NOT rise on the corpora

This is the main thing to state plainly. The 126 functions in `cmark-gfm` and 337 in `toolkit`
without `if` turned out to be functions **without obligations** — there is nothing for the solver
to check, so they became `trivial`, NOT `checked`. The fix changed the **truth about the label**,
not the coverage: they used to be called "skipped", and the funnel understated itself by 126 and
337 respectively.

Functions **with** obligations really did move from `skipped` to `checked` — visible on
`audits/codecheck`, where `ratio` (`a / b`) and `add32` (`a + b` over `i32`) are now `checked`,
and the funnel grew from 7/16 to 14/16.

A consequence for plan §4: the realistic target "C ~68 %, TS ~55 %" was computed from the old
denominator; after the split the denominator of "functions where there IS something to check" is
`total − trivial` (C 182, TS 121), and 76 and 58 are checked — that is **42 % and 48 %**, exactly
as measured in §150. Steps 4–6 (BV, ternary, `nil/null`) raise precisely those percentages.

### 151.4 A companion defect found while fixing (and closed)

`_SMT_CALLS` is a GLOBAL solver-call counter and it was **not reset per function**. The first
function with an obligation made `_SMT_CALLS[0] > 0` for all subsequent ones, so the `checked`
bucket would have been filled with functions the solver never touched (false coverage, class
#320). Found by verification: the gate's fixture (conditions outside the subset) reported
`checked 4 of 4`. Fixed by resetting the counter on each iteration — MEASURED after the fix:
`checked 1 | trivial 1 | skipped 2` on the same fixture.

### 151.5 The gate was updated TOGETHER with the code (safeguard #405.3)

`tools/xray_skip_reasons_check.py`: the parser reads TWO independent sources (the
`[REPO SUMMARY]` line and the `buckets:` line) and requires `Σ buckets == total` in both; the
fixture must exercise ALL THREE buckets (`checked >= 1`, `trivial >= 1`, `skipped >= 1`) — the
old threshold `skipped >= 2` was tied to the OLD funnel and rested on "no `if`". The meta-test
grew from 5 to **8 branches**: forgeries added for "`trivial` not exercised", "Σ buckets ≠ total",
"the `buckets:` line disagrees with the summary". MEASURED:
`[PASS #400] checked 1 | trivial 1 | skipped 2 | Σ 4 == total 4; причин 2 = пропусков 2`.

The repo summary now prints the buckets on a separate line, and its format
`функций проверено C / T (skipped S)` was NOT changed — so the parsers in
`tools/bug_hunter.py`, `tools/bounds_check.sh` and the #400 gate keep working (verified:
`xray-check`, `bounds-check`, `loop-check`, `bug-hunt-check`, `edge-cases` all green).


## §152. STEP 4, THE SAFETY HALF: A FREE CONSTANT IN THE PATH YIELDS NO ACCUSATION (`free_syms_in_path`)

> Class #178/#183 ("a false accusation is worse than a skip"). This is exactly the place
> plan §2.2 warns about: `UNSAT` checks tolerate a free constant, `SAT` checks do not.

### 152.1 MEASURED BEFORE the fix: a false accusation on CORRECT code

```c
#define MAX_BUF 1024
int scale_defined(int n) { if (n < MAX_BUF) return n + n; return 0; }
```

Gave: `[OVERFLOW PATH] scale_defined: i32 overflow … [КОНТРПРИМЕР] MAX_BUF = -2147483647,
n = -2147483648`. With `MAX_BUF = 1024` there is NO overflow: the parser does not substitute
`#define`, the name enters the path FREE, and Z3 picks it extremal. Same for an undefined
constant `LIMIT_UNDEFINED`.

### 152.2 What was done

* `_free_syms_in_path(asserts, params)` - names in the path whose value is unknown;
* `_smt_sat_guarded(...)` - `_smt_sat` with the flag: a free name in the path means REFUSAL
  (`None`) and a NAMED reason `путь зависит от неизвестной константы (SAT не решаем: #178/#183)`;
* wired into the SAT detectors: divisor, negative index, allocation overflow, expression
  overflow (`_clike_overflow_findings` gained a `skip_why` parameter);
* `UNSAT` checks (dead branch, redundant guard) were NOT touched - a free constant is sound
  there: "unreachable for every value".

### 152.3 MEASURED AFTER

| Check | Result |
|:--|:--|
| fixture with `#define` and with an undefined constant | **0 findings** (was 2), `note: путь зависит от неизвестной константы × 2` |
| `audits/codecheck` (regression) | **4** findings (unchanged), `checked 13 \| trivial 3 \| skipped 0` |
| new `xray_check.sh` section | TWO-SIDED: no finding AND the refusal must be NAMED |
| corpus `tests/fixtures/xray_free_path.c` | single-file run: `findings 0`, reason printed |

### 152.4 Found and fixed on the way (my own bug, exposed by the new test)

The single-file branch of `cmd_xray` called the reporter with ARGUMENTS OUT OF ORDER
(`tot` went into `checked`, the notes dict into `total`), so any single C-like file crashed
with `TypeError`. Caught by the FIRST run of the new section - before that only directories
were exercised, which take a different path.

### 152.5 What remains of step 4 (honestly)

**BV routing of bitwise conditions in `--xray` is NOT done.** The contract path already uses
BV (`_needs_bitvec`, `bv_expr_smt`, `_bv_smt_text`), but the `--xray` path builds the WHOLE
path in `Int`, so "just wire one bitwise operation" is impossible - a per-function BV mode is
required. Hence `binary operator` in the corpora (4 functions in `cmark-gfm/src`) is still
skipped. That is the next step, and it remains the riskiest one.

## §153. STEP 5: TERNARY -> `ite`, AND THE TRUTH ABOUT THE SKIP REASON (#408)

### 153.1 MEASURED before the fix

The `actions/toolkit` corpus had 6 functions reported as `тернарный оператор без ':'`. The
corpus contains **65 occurrences of `??`** and dozens of `?.` - the TS/JS optional chain and
the nullish operator, NOT ternaries. `convert_ternary` treated any `?` as a ternary, looked for
the matching `:` and found none - the translation failed.

A separate defect (exposed by the negative control): the FIRST `:` at zero depth was taken, so
a nested ternary `a ? b ? c : d : e` was parsed as `a ? (b ? c)` - and the translation FAILED on
the branch without a `:`.

### 153.2 Fixed

* a `?` is not a ternary when it is part of `?.` or `??` (on either side);
* the search for the matching `:` tracks `?` nesting - a right-associative parse.

MEASURED: `a ? b ? c : d : e` -> `((c if b else d) if a else e)`; `x?.a ?? 0` unchanged;
`a > 0 ? a : b` -> `(a if a > 0 else b)`.

### 153.3 AN HONEST BOUNDARY: coverage did NOT rise

| Corpus | BEFORE | AFTER |
|:--|:--|:--|
| `toolkit/packages` | `checked 58 \| trivial 337 \| skipped 63`, of which `ternary 6` | `checked 58 \| trivial 337 \| skipped 63`, `ternary 0`, `syntax 54 -> 60` |

The reason went **6 -> 0**, but `skipped` stayed **63**: the same 6 functions are now named
"синтаксис Python после перевода C-like". So the ternary was NOT the real cause of their skip.
What was fixed is the TRUTH ABOUT THE CAUSE - exactly the class tack 2.2 was about - but the
coverage did not rise, and claiming otherwise would be wrong.

### 153.4 The control (THREE-SIDED, inside `tools/xray_check.sh`)

Corpus `tests/fixtures/xray_ternary.ts` (optional chain + nullish + a nested ternary). Three
things are checked: (1) the "ternary" reason is gone; (2) the function IS parsed
(`checked 1 \| trivial 0 \| skipped 0`); (3) the translation ITSELF is correct - nesting yields
TWO `ite`s while `?.`/`??` stay untouched. The third part is mandatory: without it a "fix"
could silently break semantics.

A bug of mine was found on the way inside the section itself: backticks inside double quotes in
`echo` caused command substitution (`??: command not found`) - fixed, the section prints a clean OK.

## §154. STEP 7: THE HARNESS MUTATION LOCK (marker + gate `mutation-lock-check`)

> Closes the class of `3067a1b`: a `canfail` sabotage once reached `main`, and CI caught it
> only AFTER the push.

### 154.1 Why a marker when `flock` already exists

`acquire_run_lock()` (defect #71) stops a SECOND run, but it is INVISIBLE to git and to a human:
while the harness writes into working files, nothing prevents committing the tree. So the
harness leaves a VISIBLE trace - `.git/CANFAIL_ACTIVE_MUTATION` with `pid=` and `started=`.

The lesson of #50 is honoured (a flag file survived a crash and blocked everything): the marker
is removed in `atexit` on ANY normal exit and on an exception, and the gate DISTINGUISHES two
states - "mutation in flight" (PID alive) and "lock left after a crash" (PID dead) - and names
the cure.

### 154.2 The gate and its control

`tools/mutation_lock_check.py`: a pure `verdict(marker_exists, pid, alive)` plus a 4-branch
meta-test (no marker · PID alive · PID dead · PID unparsed).

The corpus case `mutation-lock` creates a marker with a LIVE PID inside the command and removes
it there too, so the tree never becomes dirty; the gate must go red. MEASURED: the case is
non-vacuous, and `make mutation-lock-check` is green afterwards (no marker).

### 154.3 What changed in the registry numbers (and why docs had to be edited)

The new CHECK target raised the counters: **CHECK 182 -> 183**, **cases 222 -> 223**. No gate
let that slip silently: `claims-audit` and `metrics-guard` named 30 occurrences in 14 files,
and they were fixed ON THE LINES the audit named (history in `METRICS`/the journal was NOT
touched - editing it would have rewritten the past).

## §155. STEP 6: A POINTER IS AN `Int` (0 = NULL) - 76 -> 141 CHECKED FUNCTIONS

> The `nil/null` reason held 49 functions in `cmark-gfm/src` and 3 in `toolkit/packages` - the
> largest remaining reserve. Closed without changing the solver theory.

### 155.1 Why it used to be dropped whole

Any condition mentioning `nil/null/NULL/None/undefined` was skipped (defect #197: `err != nil`
produced a FALSE `[DEAD BRANCH]` in the Int model). Dropping it was honest but expensive.

### 155.2 What was done

A pointer is modelled as an `Int` where 0 = NULL:
`p == NULL` -> `p == 0`; `p != NULL` -> `p != 0`; `!p` -> `p == 0`; a bare `p` in a boolean
position -> `p != 0`.

**Safeguard 1 (the Z3 sort trap).** `not p` over an `Int` is a sort error that `_smt_verdict`
would quietly turn into `unknown`, so `!p` is rewritten to `p == 0`.
**Safeguard 2 (reset on mutation).** `_assigned_between()` plus a filter in `_clike_conds_at`:
a predicate is dropped when its name was reassigned between the block's condition and the
analysis point - for EXITED blocks AND for ENCLOSING ones.

### 155.3 A false accusation found by measuring (not a celebrated plus)

The first run gave `1 finding`: `cmark-gfm/src/inlines.c: [DEAD BRANCH] parse_inline:
(distinct new_inl 0)`. Cause: the reset covered only EXITED blocks, so an ENCLOSING block's
condition `if (new_inl != NULL)` stayed in force after `new_inl = ...` was assigned INSIDE it.
After the fix the finding is gone.

The second run showed that the `!p` form was not rewritten at all (it contains NO `nil` word) and
the function was skipped as "syntax". But `!x` in C means `x == 0` for a pointer AND for an int
(0 = false), so the rewrite is sound for both.

### 155.4 MEASURED (cmark-gfm/src, `27d942c8`)

| | BEFORE | AFTER |
|:--|:--|:--|
| `checked` | 76 | **141** |
| `trivial` | 126 | 126 |
| `skipped` | 106 | **41** |
| findings | 0 | **0** |

`Sum 308 == total 308`. The plan's acceptance ("0 false alarms") is met. The remaining `skipped`
is "syntax" 37 + binary operators 4 (step 4b, BV).

### 155.5 The two-sided control (now ENFORCED by a gate)

Corpus `tests/fixtures/xray_null_ptr.c` and the step-6 section in `tools/xray_check.sh`:
(1) a contradiction WITHOUT mutation -> `[DEAD BRANCH]` IS found; (2) the `!p` form is
translated; (3) a pointer MUTATION between the checks -> NO findings. MEASURED:
`[OK] шаг 6: без мутации DEAD BRANCH найдена, с мутацией находок нет, форма !p переведена`.

## §156. DENOMINATOR, MEMOISATION, MASK: 308 OF 458 "FUNCTIONS" WERE CALLS (#410, #411, #412)

> Three changes in a row, each driven by a measurement, and one of them voids EVERY percentage in the project.

### 156.1 #410: 308 "functions" of `actions/toolkit` were not functions

In a `.ts` file the splitter `_clike_functions` took name/params **BY FILE SUFFIX** instead of by the
REGEX THAT MATCHED, and the fallback `RE_FN_C` matched **CALLS** (`await stat(p)`,
`throw new Error(...)`): the real name went into `params` while the TYPE SLOT went into the name.
The "function" body was cut from the middle of the file - hence the FALSE ACCUSATION
`io-util.ts: readlink: (= p 0)`.

**The fix - BOTH halves at once:** (1) the groups are taken by the regex that matched
(`RE_FN_C` -> `name = group(2)`, `params = group(3)`); (2) the rejection is by **WORDS OF THE TYPE
SLOT** (`throw new` is TWO words, so a whole-string comparison does not work).

**The acceptance oracle is met:** `cmark-gfm/src` 308 -> **308** (K = 0, the C path is untouched);
`toolkit/packages` 458 -> **150** (458 - 309); `lost_real_functions == 0` - the removed entries carry
SIX unique names and all are artefacts: `'await '` x195, `'throw new '` x101, `'new '` x6,
`'throw '` x5, `'await new '` x1, `'private '` x1 (the last is a RENAME: `private foo(...)` got its
real name and real parameters back). `io-util.ts` 8 -> 6.

### 156.2 AN HONEST BOUNDARY: every past percentage is void

`58 / 458 = 12.6 %` and `47.9 %` divided by calls. The truth (measured in §156.6, AFTER the mask):

| | total | checked | trivial | skipped | of all | of functions WITH branches |
|:--|--:|--:|--:|--:|--:|--:|
| `toolkit/packages` | 150 | **55** | 73 | 22 | 36.7 % | **55 / 77 = 71.4 %** |
| `cmark-gfm/src` | 308 | **147** | 126 | 35 | 47.7 % | **147 / 182 = 80.8 %** |

### 156.3 The literal architecture (after reverting the width truncation)

The stripper again replaces literals with **SPACES 1-to-1** (and PRESERVES newlines: dropping them
moved the `toolkit` denominator to `476`), while numbers are substituted **ONLY inside the cut-out
condition**, where file offsets no longer matter: `c != ' ' && c != '\t' && x == "utf8"` ->
`c != 32 && c != 9 && x == 8879553`.

### 156.4 The profiler: 152.5 s OF 153.3 s INSIDE solver calls

| Quantity | Value |
|:--|--:|
| solver calls on `scanners.c` | **2032** |
| unique queries | **382** |
| repeats | **1650 (81.2 %)** |
| time inside the calls | **152.5 s of 153.3 s** |
| the floor of one `kernc` call | **11 ms** |

### 156.5 Memoisation (#411) and BIT-IDENTICAL acceptance

The cache is keyed by the FULL SMT text, lives in process memory and is NEVER written to disk (the
verdict depends on the kernel/solver version). The coverage counter is incremented **ON A HIT as
well**, so `checked` = "a LOGICAL query happened", not "a process was launched" - the cache state does
NOT affect the report. `unknown` is NOT cached (a session state, not a property of the formula).

**MEASURED:** `scanners.c` **153 s -> 29-33 s** (5.3x). Buckets with and without the cache are
**bit-identical**: `toolkit` `55/73/22` (findings 0), `audits/codecheck` `13/3/0` (findings 4),
`scanners.c` `24/0/1` (findings 0).

**#411 is closed along the way:** the summary printed `SMT calls 29` (the LAST function's value,
because the counter is reset per function) while 2032 calls had happened. It now prints the file
total: **2031** (analysis), and the 1-call difference is EXPLAINED - it is the Belnap gate probe
(`_xray_solver_gate`), which `cmd_xray:7704` deliberately resets: 2032 = 2031 + 1.

### 156.6 #412: the search saw text INSIDE string literals

The raw body (needed for literals in conditions) exposed all regexes to string contents.
**MEASURED on `cmark-gfm/src/xml.c`:** the line `"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"`
produced a phantom local `version` with a `?` and no `:` -> `Unsupported` -> **A CRASH of the whole
corpus walk**.

**The fix: LOCATION by MASK, VALUE from the raw body** (`_strip_c_comments_strings` preserves length
character by character). Conditions are still taken from the raw body.

**The effect, measured per file on 159 files: EXACTLY 2 changed** -
`tool-cache/src/tool-cache.ts` (`2|0|0` -> `1|1|0`) and `glob/src/internal-path-helper.ts`
(`5|0|1` -> `5|1|0`). THE CAUSE IS NAMED: in `tool-cache.ts` line 357 is a **PowerShell script inside
a template literal** (`catch { if (($_.Exception...`), and before the fix the phantom `if` FROM IT
counted as a condition of a TS function. The denominator and the findings are unchanged.

**`cmark-gfm/src` COMPLETED FOR THE FIRST TIME: 47 s, `checked 147 | trivial 126 | skipped 35 |
Sum 308`, findings 0.** The last completed measurement before that was `141` on `291ebea`; the
intermediate states could NOT be measured (the walk never reached the end), so the `+6` is NOT
attributed to a specific change.

### 156.7 #413 (OPEN): six control bytes 0x08 instead of `\b`

Lines 2613, 2615, 7197, 7214, 7215, 7217 of `tools/kern_contracts.py` contain a literal backspace
(0x08) where a word boundary was intended - such regexes NEVER match. A LONG-STANDING defect (the
same 6 bytes are in `291ebea` and in `HEAD`). Dead are the DUPLICATES of rule C (a `uint16` field,
CVE class `ac80f7b`) and rule D (off-by-one `<=`) inside the loop. **Working twins exist:** the
file-level copy of rule D DOES fire (MEASURED: the fixture `numdelims <= max_delims` ->
`[BOUNDS PATH] off-by-one`). The fix is deliberately postponed: it would ENABLE rules that never
worked and must go with its own measurement.

### 156.8 Gates and evidence

`xray-check` (including the new step 4/5/6 sections and #410), `ci-fast` 11 green, `audits/codecheck`
4 findings, `Sum of buckets == total` on both corpora, the fixture `tests/fixtures/xray_ts_calls.ts`
(measured on both sides: before the fix `Sum 3 == total 3`, after `Sum 1`).

## §157. EIGHT CONTROL BYTES 0x08: DEAD RULES AND A LYING DOCSTRING (#413, CLOSED)

> Found while closing `#412`: six lines of the file carried a literal backspace where a
> word boundary `\b` was intended. Eight bytes - and three capabilities that did not work.

### 157.1 What exactly was dead

| Place | What did not work | How it was measured |
|:--|:--|:--|
| 7197 | rule C in the loop: a `uint16` field overflow (CVE class `ac80f7b`) | the fixture `row->n_columns++` |
| 7214, 7215, 7217 | rule D in the loop: off-by-one `<=` capacity | the fixture `numdelims <= max_delims` |
| 2613, 2615 | the **exact saturation rewrite** `_saturate_rewrite` (`+|` / `-|`) | `_saturate_rewrite('a +| b','u32')` |

In a Python raw string `0x08` is NOT an escape but the character itself: the regex requires a
backspace, which never occurs in source code, so it NEVER matches. The bytes are long-standing -
the same ones are in `291ebea` and in `HEAD`.

### 157.2 The docstring lied (the most important part here)

`_saturate_rewrite` describes itself as: "Previously `+|` / `.saturating_add` were simply
translated to `+` ... Now an exact expression `ite(a+b > HI, HI, ...)` is built".

**MEASURED before/after the byte fix:**

```
BEFORE: _saturate_rewrite('a +| b', 'u32') -> 'a +| b'          (the text did NOT change)
AFTER:  _saturate_rewrite('a +| b', 'u32') -> '(4294967295 if (a + b) > 4294967295 else (a + b))'
```

So the "exact expression" was NEVER built: the capability described in the docstring existed only
in the text. Same class as `#405` (a label instead of a fact) and `#410` (a denominator instead of a
fact) - except here the divergence was between the DOCUMENT and the CODE.

### 157.3 Duplication: the warning was confirmed by measurement

The file-level twins of rules C/D are written WITHOUT `\b` and worked all along; the in-loop copies
with `\b` were dead. After fixing the bytes both copies fired on the same line:

```
BEFORE dedup:  [BOUNDS PATH] scan: off-by-one: ...            <- the in-loop rule (FUNCTION name)
               [BOUNDS PATH] offbyone.c: off-by-one: ...      <- the file twin (FILE name)
               -> findings 2 for ONE error
AFTER:         [BOUNDS PATH] scan: off-by-one: ...            -> findings 1
```

The messages differ (function name vs file name), so `if msg not in found` cannot collapse them.
The deduplication is by SUBJECT: the in-loop rule records the subject (`_subj_c` - the field name,
`_subj_d` - `var <= cap`), and the file twin skips what is already reported. The file twins are KEPT:
they are needed for functions the splitter missed (multi-line declarations, `#194`).

### 157.4 The acceptance oracle is met on three corpora

| Corpus | Buckets | Findings |
|:--|:--|--:|
| `cmark-gfm/src` | `147 \| 126 \| 35`, Sum 308 | **0** (unchanged) |
| `toolkit/packages` | `55 \| 73 \| 22`, Sum 150 | **0** (unchanged) |
| `audits/codecheck` | `13 \| 3 \| 0`, Sum 16 | **4** (unchanged) |

Gates `bounds-check`, `loop-check`, `edge-cases`, `audits` - green.

### 157.5 A side finding: the BV route for `+|` was ACCIDENTAL

MEASURED on `tests/fixtures/zig_saturating_add.zig`: before the fix the function went through the BV
theory (`[BV] addSat ... явное \`+|\` — переполнение не паникует`), after - it is proved in Int with
the EXACT clamped model. Cause: `+|` reached BV because the `|` character matched the bitwise regex
`_BITWISE`, not by design. Real bitwise operations (`& ~ << >>`) still keep the BV route.

### 157.6 A ratchet against the class

`tools/source_hygiene_check.py` + a section in the EXISTING target `edge-cases` + a meta-test with
3 branches (a planted `0x08` is found · a clean regex is not accused · a mention of the byte in a
COMMENT is not accused). BOUNDARY: EXACTLY `0x08` is caught, because LEGITIMATE control bytes were
MEASURED - `0x1b` (ANSI colours, 7 places in `registry.py`/`canfail.py`) and `0x00` (byte tests in
three files); banning them would break working code for the sake of a pretty rule. MEASURED: 131
files of `tools/*.py` are clean.

## §158. FIELDS, OPERATORS AND A FALSE HAVOC MODEL: 93 % OF FUNCTIONS WITH BRANCHES (#414, #416)

> The dump of the remainder settled the question faster than any hypothesis: it refuted
> Priority 2 for TypeScript and confirmed it for C, and along the way found a SOUNDNESS defect
> nobody was looking for.

### 158.1 The dump: what ACTUALLY held the remainder

`cmark-gfm/src` (253 refusals): `syntax` 151 (of which **144 with field access**), `binary operator`
94, the `!` form 5, `nil/null` 3.
`toolkit/packages` (77): `syntax` 74 (with a field 55), `nil/null` 3.

**Verbatim from the \"syntax\" bucket (TS):** `error.code === 6123186`,
`seenArtifactNames == 0.has(artifact.name)`, `typeof body !== 3993132 || body === null`,
`fs == 0.existsSync(rootDirectory)`, `scopeParts?.[0] !== 9098484`.

So the blockers were NOT fields but: `===`/`!==`, the garbage from the `!` rewrite, `typeof`, `in`,
`?.`.

### 158.2 A false HAVOC model (#414) - a SOUNDNESS defect found in passing

The `!p -> p == 0` rewrite had no safeguard and hit CALLS:

```
!S_is_line_end_char(c)  ->  S_is_line_end_char == 0(c)  ->  (= S_is_line_end_char _havoc_1)
```

`expr_smt` took `0(...)` for a HAVOC call, so the FUNCTION NAME became a VARIABLE and `!f(c)` was
\"translated\" as a comparison with an arbitrary constant. **MEASURED:** in `cmark-gfm/src` **9
conditions** were SILENTLY accepted this way; in `toolkit/packages` the same **17** forms failed
loudly (in TS `0.method()` is a syntax error, in C `0(...)` is a valid call). A false model is
worse than a skip.

**Fixed:** the rewrite applies only to a BARE name (not before `.`, `->`, `[`, `(`, a word).

### 158.3 The \"what-if\" BEFORE the fix: each change's contribution

| Variant | `cmark` (254 refusals) | `toolkit` (77) |
|:--|--:|--:|
| A: `===` / `!==` | 0 | **-35** |
| B: the `!` safeguard | +9 (an apparent \"minus\": those are FALSE models, not coverage) | 0 |
| C: fields `a->b` / `a.b` | **-100** | -2 |
| D: `typeof X` | 0 | **-18** |

Priority 2 (fields) is confirmed for C and **refuted** for TS: there a field is only an ingredient
while the blocker is operators. That is exactly why the measurement goes BEFORE the change.

### 158.4 THE EFFECT (MEASURED, 0 findings on both corpora)

| Corpus | `checked` | `trivial` | `skipped` | of the functions WITH branches |
|:--|--:|--:|--:|--:|
| `cmark-gfm/src` (was 147/126/35) | **170** | 126 | **12** | 147/182 = 80.8 % -> **170/182 = 93.4 %** |
| `toolkit/packages` (was 55/73/22) | **72** | 73 | **5** | 55/77 = 71.4 % -> **72/77 = 93.5 %** |

`Sum == total` on both; the `audits/codecheck` regression is unchanged (`13 | 3 | 0`, findings 4).

### 158.5 Safeguard B: resetting a predicate when the FIELD or the BASE is mutated

The flat name `a__b` did not match the names `_assigned_between` returns (`a->b = ...` leaves the
name `b` before `=`). The new `_mut_names_for()` adds the BASE `a` and the FIELD `b` to the
predicate, so a condition on the OLD field does not survive a mutation - otherwise it would be the
same false-dead-branch class as `#409`.

### 158.6 The boundary: what remains is CALLS and BITWISE, not \"almost everything\"

`cmark` 12 = binary operator 4 + the `!` form 4 + syntax 4. `toolkit` 5 = all the `!` form (calls
`!f(x)`). The composition of the remainder after the fix: `typeof` 0, JS-`in` 4, `?.` 1, calls 15,
index 3, bitwise 12. The next big blocker in C is `&` and `[...]` (step 4b, BV), in TS it is calls
outside the subset (they cannot be modelled without interprocedural analysis).

### 158.7 Recorded separately, `#415` (OPEN): `make audits` hygiene

The generator does `rmtree(audits/smt2)` and rewrites TRACKED `EVIDENCE.md` and
`real_code_corpus.*`; no gate compares the set of `audits/smt2/*.smt2` with the `EVIDENCE.md`
table, which is why 9 cases lived in git since `b646ad1` and never appeared in the snapshot.

## §159. THE PARITY GATE FOUND AN ORPHAN ON ITS VERY FIRST RUN (#415, #417)

> A tool that compares \"table rows <-> formula files\" found a discrepancy immediately -
> and it turned out to be an undecided case that the snapshot silently hid.

### 159.1 What `#415` changed

| What | Before | After |
|:--|:--|:--|
| Generation | `rmtree(audits/smt2)` BEFORE any check | into a TEMPORARY directory, atomic swap |
| On a parity violation | the directory was already empty | the directory is NOT modified (MEASURED) |
| \"rows <-> files\" check | there was NONE | BOTH directions (a row without a file · a file without a row) |
| Snapshot drift | silent | a LOUD `+/-` report against the committed `EVIDENCE.md` |

### 159.2 What the gate found (first run)

```
[!] #415: паритет снимка нарушен (1 расхождений):
    файл БЕЗ строки в таблице (сирота): zcalloc_zcallocSizeBounded.smt2
    Каталог audits/smt2 НЕ изменён: снимок остался прежним.
```

**The cause (#417):** the extractor prints FOUR verdict kinds, including `[N]` -
\"NOT SOLVED\" (Belnap N), while `RE_VERDICT` knew only `PASS/FAIL/SKIP`. The formula of
an undecided function was emitted with no row. So EXACTLY the case an auditor must see
disappeared from the snapshot: \"the solver did not decide\" is N, not \"all is well\".

### 159.3 MEASURED after the fix

```
functions: 37 | PROVEN 15 | REFUTED 19 | SKIP 2 | NOT SOLVED (N) 1 | formulas emitted 37
```

The parity \"37 rows == 37 formulas\" holds, `make audits` RC=0. The drift report named the
single changed row: `+ audits/zlib/zcalloc.c :: zcallocSizeBounded`. The table gained a
`**UNKNOWN (N)**` column.

### 159.4 The Step 4b estimate (\"what-if\", MEASURED on `cmark-gfm/src`)

| What is added | Translation refusals | Gain |
|:--|--:|--:|
| current state | 141 | - |
| + index `a[i]` -> `a__at_i` (congruence BY TEXT) | 140 | **+1** |
| + bitwise abstraction `(a & b)` -> a free symbol | 119 | **+22** |

**Conclusion:** the index alone gives almost nothing in C (it nearly always comes together with
`&` or a call), while the bitwise abstraction gives +22 conditions but NO bit-level reasoning:
it will not catch a genuinely dead branch like `(x & 1) == 0 AND (x & 2) == 0 AND (x & 3) != 0`.
That needs REAL BV, i.e. re-encoding the accumulated path conditions from Int into
`(_ BitVec 32)` - a separate, large piece of work (and it is NOT started: the promised
\"+4 functions\" is not confirmed by the measurement).

## §160. BARRIERS 2+3: A TEST ON THE TRANSLATION ITSELF AND AN IR SNAPSHOT (#418)

> "The check exists, the needed observation is not in it" - class `#394.4`. Closed here for the
> C-like translator: 17 defects of the tack were invisible to all 183 gates.

### 160.1 Why the old tests were blind (two MEASURED examples)

| Defect | What happened | Why the test stayed silent |
|:--|:--|:--|
| `#413` | `_saturate_rewrite('a +| b')` returned its INPUT UNCHANGED | the file verdict was `PASS`: the `|` character routed the expression to the BV path |
| `#414` | `!f(c)` -> `(= f _havoc_1)` - a FALSE model | Z3 answered `sat`, quiet from the outside |

### 160.2 Barrier 2: the table-driven micro-test (`tools/clike_ir_check.py`)

19 pairs "raw condition -> the EXACT SMT or SKIP", each naming the defect it protects, plus 2
`#414` guards. It runs in **fractions of a second WITHOUT Z3**. The meta-test MUST turn red:
MEASURED - a planted `+X` and an empty expectation are both caught, the table passes. Wired into
the EXISTING target `edge-cases` (no registry growth).

### 160.3 Barrier 3: the corpus IR snapshot

```
cmark-gfm/src  : functions 308, conditions 2539, translated 2398, sha 0aa016a61960017a
toolkit/packages: functions 150, conditions 156, translated 134, sha 2a7aac90f9317962
```

Any change to the translator that alters the PARSE is visible here in fractions of a second. That
is exactly what was missing when the denominator jumped `458 -> 476 -> 443`. A missing corpus is a
NAMED skip, not a silent green.

### 160.4 Barrier 4 (extracting `clike_frontend.py`) - NOT done, the reason is measured

`grep`: **29 `canfail` cases patch `tools/kern_contracts.py`** by textual anchors, and
`docs/contracts.lock.json` contains that file. The extraction must go together with rebuilding the
anchors and the lock. The order is deliberate: **the net (2+3), then the surgery (4)** - under the
snapshot and the table the extraction stops being a lottery.

## §161. STEP 4b: REAL BV - AND THE FALSE ACCUSATION IT EXPOSED (#419, #420, #421, #422)

> The work started as \"add a bitwise mode\" and ended with three defects, one of which is an
> accusation of CORRECT code.

### 161.1 What was done (the two safeguards from the plan)

**No. 1, the sort trap.** `_bv_as_bool` wraps a bitwise term in a BOOLEAN position into
`(distinct <term> (_ bv0 32))`: in C one writes `if (options & MASK)` without `!= 0`, while
`(bvand ...)` has the sort `(_ BitVec 32)` and Z3 answers `sort mismatch`.

**No. 2, sort mixing.** The BV query is assembled ENTIRELY from BV forms: conditions translatable
in Int live in `if_blocks` and carry a parallel BV form; conditions translatable ONLY in BV live in
`bv_only`. `_bv_path_blocks` merges them into BV forms, so Int and `(_ BitVec 32)` never meet in one
query. The Int query does not change by a single byte.

### 161.2 The three defects found along the way (all MEASURED)

| Defect | What it was | How it was found |
|:--|:--|:--|
| `#419` | `!(x & 1)` -> `' not (x & 1)'` with a LEADING SPACE -> `IndentationError` -> SKIP | without it `!(x & 1)` was translated neither in Int nor in BV |
| `#420` | `_free_smt_vars` declared `bvand`/`bv1`/`_` as CONSTANTS -> a symbol clash -> \"not decided\" | the BV positive control stayed silent with a CORRECT query |
| `#421` | `x > 0 AND x + 1 < 0` was declared a dead branch | in C at `x = INT_MAX` the wraparound makes the branch ALIVE |

`#421` is an accusation of CORRECT code, and it is withdrawn by a **cross-check**: if Int declares a
branch dead and the condition contains arithmetic, the same question is asked in QF_BV32; SAT -> the
accusation is withdrawn and NAMED as a note (a silent withdrawal would be a silent loss).

### 161.3 The two-sided control (pinned by fixtures and a gate section)

| Control | Expectation | MEASURED |
|:--|:--|:--|
| `tests/fixtures/xray_bv_bits.c` | a bitwise dead branch IS found | `[DEAD BRANCH] bit_dead ... (UNSAT, BV32)` |
| `tests/fixtures/xray_bv_wrap.c` | NO findings + the reason NAMED | 0 findings, the note `ветка достижима в BV32 (перенос) — обвинение снято` |

### 161.4 The result and AN HONEST BOUNDARY

| Corpus | `checked` | `trivial` | `skipped` | of the functions WITH branches | findings |
|:--|--:|--:|--:|--:|--:|
| `cmark-gfm/src` | 170 -> **173** | 126 | 12 -> **9** | 93.4 % -> **95.1 %** | **0** |
| `toolkit/packages` | 72 (unchanged) | 73 | 5 | 93.5 % | **0** |

**The gain is SMALLER than expected (+3, not +4), and the reason is measured:** the \"what-if\"
promised +22 conditions, but 23 bitwise conditions in `cmark` come TOGETHER WITH CALLS, and the
\"havoc + BV\" mix is outside the subset (`is_ok(a) && (b & 1)` -> SKIP \"binary operator\"). The
`cmark` remainder of 9 = the `!` form 4 + syntax 4 + binary 1. The `cmark` run time grew 47 s -> 69 s:
BV queries cost more than Int.

### 161.5 The `#400` fixture had to be updated - and that is a measurement too

Its \"skips\" (`p->len`, `a & 1`) ARE NOW TRANSLATED (#416 and step 4b), so no \"real skip\" was left in
it, and the sub-gate honestly turned red. A new skip form was found by measurement: a MIX of a call
and a bitwise op (`is_ok(a) && (b & 1)`) - \"havoc + BV\" is outside the subset. MEASURED after:
`checked 3 | trivial 1 | skipped 1 | Sum 5 == total 5`.

## §162. `kernx` E2E: THE BELNAP CONFLICT WAS UNREPRESENTABLE IN THE CATALOG (#423, #424, #425)

> A one-minute dry run: two contradictory pieces of evidence for one claim. The truth layer
> worked - the catalog did not.

### 162.1 The measurement BEFORE the fix

Project: `claim "feature Z"` + two executions (`exit_code = 0` -> T and `exit_code = 124` -> F),
both linked `supported_by`.

| What | Result |
|:--|:--|
| `kernx status` | `статус conflicted: 1`, `резолюция исполнений: N->B(конфликт) 1` - **the truth layer works** |
| `kernx build` | **`[!] SQLite: CHECK constraint failed: status IN (...11 statuses...)`** |

**Cause (#423):** the CHECK list in `catalog.zig` knew 11 statuses while `ast.Status` has 12.
`conflicted` (Belnap B, produced by the joinK accumulator) was not in the schema, so **the
flagship capability was unrepresentable** and `build` crashed.

### 162.2 #424: the packet collapsed B into F

`export.zig` included `conflicted` in the `contradictions` list but printed the LITERAL `"refuted"`
as the reason. The human report said `[conflicted]`, the machine packet said `refuted`: for a
consumer that is \"refuted, drop it\" instead of \"there is both T and F, e=0, investigate\".

### 162.3 #425: a SQLite migration trap (found while fixing)

A bare `ALTER TABLE claims RENAME TO claims_old` **rewrites references in other tables**:
MEASURED - `metrics.claim_id REFERENCES "claims_old"(id)`; after the `DROP` the reference is
dangling and EVERY operation fails with `no such table: main.claims_old`. The catalog became
unusable.

### 162.4 What was done

1. **The CHECK list is assembled from `ast.Status` at compile time** (`status_check_list`), the DDL
   is a single constant. The drift became impossible BY CONSTRUCTION.
2. **Migration of an old catalog** with the procedure from the SQLite documentation:
   `foreign_keys=OFF` + `legacy_alter_table=ON` -> recreate -> copy -> `DROP` -> restore the PRAGMAs
   -> `PRAGMA foreign_key_check` with a loud message on a violation.
3. **Two tests** (both in CI via `test-next`): (a) EVERY status from the vocabulary inserts;
   (b) an E2E through the pipeline: resolution -> catalog -> packet, and the packet MUST say
   `"reason": "conflicted"`.

### 162.5 MEASURED after

| Check | Result |
|:--|:--|
| `kernx build` on a conflict (new catalog) | `[OK] Собрано: узлов=6`, the catalog holds `('claim:feature Z','conflicted')` |
| the agent packet | `[{"id": "claim:feature Z", "reason": "conflicted"}, {"id": "claim:execution: heavy", "reason": "refuted"}]` |
| an old catalog with a foreign key | `[i] миграция каталога: CHECK-список устарел`; the old row `old:1/tested` survived, the metrics survived, `FK: REFERENCES claims(id)` |
| a repeated run | the migration does NOT trigger (idempotency) |
| `zig build test-next` | green |

### 162.6 Boundaries, honestly named

* Verified on a FIXTURE project, not on a live project of the second contour (`/opt/rii` is absent
  in this environment).
* The migration recreates the table: if a row's status is OUTSIDE the new vocabulary the row is NOT
  carried over - and a message says so (no silent loss).
* `kernx` was NOT tested on `packet --scope` and `diff` for conflict cases.

## §163. A DRY MEASUREMENT ACROSS THREE POINTS: #424'S NEIGHBOURS, `trusted > 0`, THE ANTI-CHEAT

> Zero code changes, three measurements. One result is negative (and that matters),
> one confirmed an already-declared boundary, one exposed a class.

### 163.1 Point 1: there is NO third twin of `#424` (a negative result)

| Path on a conflicted claim | Behaviour |
|:--|:--|
| `kernx packet --scope issue-42` | `{"id": "claim:feature Z", "reason": "conflicted"}` OK |
| `kernx diff` (conflict -> no conflict) | `- claim:feature Z **conflicted**` / `+ claim:feature Z tested` OK |
| `state_axes.toBelnap` | an exhaustive `switch`: `proved->T`, `refuted->F`, `unknown/timeout/out_of_fuel/invalid_certificate/tool_error->N` OK |

Verdict: the neighbouring branches handle the conflict correctly. The hypothesis \"where there is one
hand-written branch without `conflicted`, there is a second one\" is **not confirmed** here - and that
is recorded as a result rather than hidden.

### 163.2 Point 2: `trusted > 0` - 3 of 7 are zero, the residue is almost ONE task

| Task | steps | mp | resolution | Farkas | rewrite(lin.) | eq | bool | TRUSTED |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| `2PhLockVParam_RC-02` | 66 | 19 | 0 | 1 | 22 | 3 | 14 | **0** |
| `2PhLockVParam_RC-07` | 15 | 1 | 0 | 0 | 4 | 4 | 4 | **1** (rule: **`rewrite`**) |
| `storeinv...00002_001.cvc` | 78 | 4 | 12 | 0 | 2 | 24 | 12 | **5** |
| `QF_BV/add_three.4_bit` | 7616 | - | 5247 | - | 55 | - | - | **2970** |

`make smtlib-proof-check` RC=0; the gate's own summary: \"4 theories: 0 discrepancies, 0 false
alarms, 0 holes. 7945 proof steps parsed. TRUSTED (the checker has no BV rules) up to 2970 - the
number is PUBLISHED, not claimed as 0\".

**Conclusion:** \"3 of 7 with `trusted: 0`\" is true; but 2970 of ~2981 trusted steps are ONE QF_BV
task, while the residue in the three tasks is 1 and 5+5 steps, and the first of them is NAMED:
**`rewrite`**. So most of the residue is a fundamental boundary (no `bitblast`/`bv-*` rules), not
\"we forgot a simple rule\". The gate DECLARES it.

**A gap found (#428):** the checker computes the rule name (`first_trusted`) and `kernc prove`
prints it, but the gate parses only NUMBERS - so the report cannot answer the auditor's question
although the tool knows the answer.

### 163.3 Point 3: the anti-cheat catches LITERAL forms, not masked ones (#426)

| Bypass class | Literal form | Masked form |
|:--|:--|:--|
| always-true `__eq__` | `def __eq__: return True` -> **CAUGHT** | `setattr(C, "__eq__", lambda s, o: True)` -> **NOT CAUGHT** |
| mock | `mock.patch("mod.fn", ...)` -> **CAUGHT** | `target_mod.withdraw = lambda b, a: 0` -> **NOT CAUGHT** |
| skip | - | `pytest.skip('passed')` -> **NOT CAUGHT** |
| exit | `os._exit(0)` -> **CAUGHT** | - |
| swallowed assert | `except BaseException: pass` -> **CAUGHT** | - |

Of the reviewer's 5 bypasses **2** are caught. At the same time the gate `tools/anti_cheat_check.sh`
claims \"ALL 5 cheat classes caught\" - because its fixture holds the LITERAL forms. Same class as
`#394.4`/`#418`: **the check exists, the needed observation is not in it**.

### 163.4 Side finding: `--anti-cheat <directory>` crashes with a traceback (#427)

MEASURED: `IsADirectoryError: [Errno 21] Is a directory`, rc=1, a full Python stack. The flag takes
a file, but a directory is not rejected with a NAMED error (class `#370`/`#371`).

## §164. THE ANTI-CHEAT: SEMANTIC RULES, FALSE POSITIVES AND A NON-VACUOUS GATE (#426, #427, #429)

### 164.1 Why the class was missed: the rules were SYNTACTIC

| Bypass class | Literal form | Masked form (BEFORE) |
|:--|:--|:--|
| always-true `__eq__` | `def __eq__: return True` -> CAUGHT | `setattr(C, "__eq__", lambda...)` -> **0 findings** |
| mock | `mock.patch("mod.fn", ...)` -> CAUGHT | `target_mod.withdraw = lambda...` -> **0** |
| skip | - | `pytest.skip('passed')` -> **0** |

### 164.2 What was added (semantic equivalents)

* `setattr` with a dunder name (`CHEAT_DUNDER`, 14 names) -> `dynamic dunder override`;
* assignment to an attribute of an IMPORTED module where the value is a LAMBDA or a FUNCTION
  REFERENCE -> `monkeypatch of imported module attribute`;
* an UNCONDITIONAL `pytest.skip`/`xfail` in the BODY of a `test_*` (not inside `if`/`try`) ->
  `unconditional skip inside a test`.

The fixture `examples/anti_cheat_demo.py` gained three masked twins and the gate requires **8
classes**. MEASURED: the reviewer's 5 bypasses -> **5/5**.

### 164.3 The gate is NON-VACUOUS (verified by planting)

```
planting `getattr` instead of `setattr` -> [!] чит НЕ пойман: dynamic dunder override (setattr), rc=2
restoring                               -> rc=0
```

### 164.4 A false positive on OUR OWN code (#429)

MEASURED BEFORE: **119 of 132** files of `tools/*.py` were flagged as cheats. The main contributor was
the rule \"exit inside tested code\" firing on the MODULE-LEVEL CLI idiom `sys.exit(main())`. FIXED: an
exit is flagged only INSIDE a function (`_fn_depth`); the noise went **119 -> 30**. Along the way a
false positive of the new rule on a legitimate output capture (`sys.stdout = cap`) was removed: the
streams `sys.stdout/stderr/stdin/path` are excluded.

**A BOUNDARY (open):** the remaining 30 of 132 are flagged by rules that only make sense for a TEST
file (`mock` 186, `overfitting` 59, `swallowed` 29, `exit` inside functions 13). The gate checks
\"clean code passes\" on ONE hand-picked file - in general that claim is vacuous; the cure is a
`--test-file` mode or a requirement of \"0 findings on N of our own files\".

### 164.5 `#427`: a bad input is rejected with a NAMED error

MEASURED BEFORE: a directory -> `IsADirectoryError`, rc=1, a full stack. AFTER: a directory -> rc=2 +
a hint; a missing file -> rc=2 + `файл не найден`.

## §165. THE ANTI-CHEAT: CLOSING CLASSES, NOT LINES (#426.2, #426.3)

### 165.1 Neighbouring forms: every trick has a second syntactic sugar

| Trick | Form from the probe | NEIGHBOUR form (what an agent writes after the fix) | Rule |
|:--|:--|:--|:--|
| comparison override | `setattr(C, "__eq__", ...)` | `C.__eq__ = lambda ...` | `dynamic dunder override (assign)` |
| function replacement | `target_mod.withdraw = lambda ...` | `setattr(target_mod, "withdraw", ...)` | `monkeypatch via setattr` |
| function replacement | - | `obj.fn = lambda ...` (except `self`) | `monkeypatch of attribute (callable)` |
| test skip | `pytest.skip('passed')` | `raise unittest.SkipTest(...)` | `test skipped by raise` |
| test skip | - | `@pytest.mark.skip` / `@pytest.mark.xfail` / `@unittest.skip` | `test disabled by a decorator` |

`@pytest.mark.skipif(sys.platform == "win32")` is **NOT** flagged: a conditional skip is
legitimate; only `skipif(True, ...)` is caught. Along the way `import x.y as alias` is now
registered (otherwise a replacement through an alias was not recognised).

### 165.2 A two-sided control: the honest file must be clean

`tests/fixtures/anti_cheat_honest.py` - forms the rule COULD have hit: `self.balance = 100`
(setUp), `cfg.timeout = 30` (not a function), a module-level `sys.exit(main())`, a conditional
`skipif`. MEASURED: **0 findings**.

### 165.3 The gate: 12 classes + the honest file + a directory without a traceback (NON-VACUOUS)

```
cheat fixture    -> 12 findings
honest file      -> 0 findings, [OK] чисто
--anti-cheat examples (a directory) -> rc=2, «ожидает ФАЙЛ», NO Traceback

planting `C.__eq__ = lambda ...` INTO THE HONEST file
   -> [!] ЧЕСТНЫЙ файл обвинён: [CHEAT DETECTED: dynamic dunder override (assign): __eq__], rc=2
restoring -> rc=0
```

### 165.4 Noise on our own code (the `#429.2` boundary remains)

31 of 132 files of `tools/*.py` (was 119 before `#429.1`): `mock` 186 · `overfitting` 59 ·
`swallowed` 29 · `exit` inside functions 13 · `monkeypatch of attribute (callable)` 4. These are
rules that make sense for a TEST file; on arbitrary source they are noise. The cure is not done.

## §166. `#428`: THE RULE NAME IS WIRED INTO THE REPORT AND PROTECTED BY AN INVARIANT

### 166.1 What was lost

The checker computes `first_trusted` (the rule name of the first unverified step), `kernc prove`
prints `[i] первое непроверенное правило: rewrite (1 шт.)`, while the gate parsed ONLY numbers -
so the answer to the auditor's "which rules give `trusted > 0`" never reached the report.

### 166.2 What was done

1. The gate parses the line and prints the rule IN THE TABLE: `ДОВЕРЕННЫХ 1 (rewrite)`, `0 (—)`.
2. **A TWO-SIDED INVARIANT:** `trusted > 0` <=> the rule is NAMED. If the number is there and the
   name is not - the gate fails (`rc=1`) with a named reason. A broken parser instantly turns the
   gate red.
3. A 10th meta-test branch: "ДОВЕРЕННЫЕ without a rule name turn the gate red (#428) is caught".
   MEASURED: `smtlib-proof selftest: ошибок 0`.

### 166.3 MEASURED on the tasks (by hand, before the fix)

| Task | steps | TRUSTED | rule |
|:--|--:|--:|:--|
| `2PhLockVParam_RC-02` | 66 | 0 | - |
| `2PhLockVParam_RC-07` | 15 | 1 | **`rewrite`** |
| `storeinv...00002_001.cvc` (both) | 78 | 5 | **`commutativity`** (5 each) |
| `QF_BV/add_three.4_bit` | 7616 | 2970 | **`unit-resolution`** (the first unrecognised one; no BV rules in the checker - DECLARED) |

### 166.4 What this opens (the next step, NOT done)

It is now visible that on NON-bitwise tasks the residue is single steps (`1` and `5+5`), and the
first of them is named: `rewrite`. If those forms are trivial (a linear `rewrite`/`monotonicity`),
the `trusted: 0` share on non-bitwise tasks can be driven to 100 %, leaving `trusted > 0` EXCLUSIVELY
to the fundamental boundary of QF_BV bit-blasting.

**MEASURED AFTER WIRING (rule names in the table):**

```
ДОВЕРЕННЫХ 0 (—)  ·  1 (rewrite)  ·  0 (—)  ·  0 (—)
ДОВЕРЕННЫХ 2970 (unit-resolution)  ·  5 (commutativity)  ·  5 (commutativity)
```

That is exactly the bonus the plan predicted: on NON-bitwise tasks the residue is `rewrite` (1) and
**`commutativity`** (5+5) - TRIVIAL structural forms; verifying them would raise `trusted: 0` on
non-bitwise tasks to 100 %, leaving `trusted > 0` to one QF_BV task. And the first unrecognised rule
in QF_BV is **`unit-resolution`** (not `bitblast`), so the boundary lies deeper than "no `bv-*`
rules" - and that too is MEASURED, not assumed.

## §167. A DUMP OF THE TRUSTED STEPS' S-EXPRESSIONS (`#430`)

The auditor's question: "which EXACT rules produce `trusted > 0`". The answer came
from a DUMP of the checker itself: `dbgPrint` is unconditional, while the details
are switched on by `KERN_DEBUG_LIA` and `KERN_DEBUG_TRUSTED`.

### 167.1 Five S-expressions (verbatim)

| Task | Rule | S-expression of the step |
|:--|:--|:--|
| `2PhLockVParam_RC-07` | `rewrite` | `(rewrite (= (and false (not (or (not $x84) (not $x85)))) false))` |
| `storeinv_t1_np_nf_ai_00002_001.cvc` | `commutativity` | `(commutativity (= $x124 (= a1 a2)))` |
| `QF_BV/add_three.4_bit` | `unit-resolution` #1 | `(unit-resolution @x2893 @x5139 $x2534)` |
| same | `unit-resolution` #2 | `(unit-resolution @x3307 @x5139 $x1010)` |
| same | `def-axiom` #3 | `(def-axiom (or $x2688 k!140 $x3214))` |

In addition `[dbg-rw]` printed BOTH sides of the unresolved equality for the first task:

```
LHS = (and false (not (or (not (<= 2 resB)) (not (<= haveAandB haveA2andB)))))
RHS = false
```

### 167.2 What it means rule by rule

1. **`rewrite` (RC-07) - ABSORPTION.** The LHS is a conjunction with the constant
   `false` on the left, the RHS is `false`. The rule `(and false X) = false` holds
   FOR ANY `X` (no premises). `constBoolEq` does not take it because the LHS is NOT
   a constant. A dedicated structural absorption rule is needed - and it is
   soundly checkable.
2. **`commutativity` (storeinv) - EQUALITY SYMMETRY** with `$x124` acting as a bound
   name (`(= a2 a1)`): it requires resolving the definition of `$x`, then checking
   that the arguments are swapped. A purely syntactic rule.
3. **`unit-resolution` + `def-axiom` (add_three) - TWO SUPPORTED rules in SPECIFIC
   shapes.** `unit-resolution` was verified by the checker 5 247 times in THIS VERY
   file; `def-axiom` is in `KNOWN_RULES` and has a tautology check. The failure comes
   from the shape with `k!140` (a skolem constant: it needs the definition context).

### 167.3 TWO CORRECTIONS to earlier conclusions (measured, not assumed)

1. **The label "the checker has no BV rules" is NOT CONFIRMED by the dump.** The first
   trusted steps of `add_three.4_bit` are `unit-resolution` and `def-axiom`, and both
   rules ARE present in the checker. So the residue is explained by SPECIFIC SHAPES of
   supported rules, NOT by missing BV rules. The label has been corrected in
   `tools/smtlib_proof_check.py` (docstring + summary print).
2. **"5 `commutativity` steps" was a WRONG phrasing.** The format
   `[i] первое непроверенное правило: <rule> (<N> шт.)` means: `<rule>` is the rule of
   the FIRST trusted step, `N` is the TOTAL number of trusted steps. `storeinv` has 5
   trusted steps but THREE rules: `commutativity` x1, `lemma` x2, `monotonicity` x2
   (dump `#1..#5`). The table and the print now say "первое правило: ...".

### 167.4 What it gives the next step

- On NON-BITVECTOR tasks the residue is 6 steps (1 + 5) of three rules; the first of
  them (`and`-absorption) is checkable today and without BV.
- For QF_BV we need `unit-resolution` shapes with `k!`-constants and `def-axiom` - that
  is about resolving DEFINITIONS, not about bit-blasting.

## §168. STEPS 1-3 OF THE `trusted: 0` PLAN (`#430`): ABSORPTION, COMMUTATIVITY, A REVERTED FLATTENING

### 168.1 STEP 1 - CONSTANT ABSORPTION (Kleene three-valued logic)

`evalBoolConst` returned `null` when ANY argument of `and`/`or` was not evaluable.
Now in `and` the constant `false`, and in `or` the constant `true`, ABSORB the whole
term regardless of the other arguments (a boolean identity, no premises).

MEASURED on `2PhLockVParam_RC-07.smt2`:

| | BEFORE | AFTER |
|:--|--:|--:|
| `rewrite(linear)` verified | 4 | **5** |
| TRUSTED | **1** (`rewrite`) | **0** |
| verdict | a trusted step | **`[PROOF VERIFIED] trusted: 0`** |

Result: the number of tasks with `trusted == 0` became **4 of 7**.

### 168.2 STEP 2 - THE `commutativity` RULE

The conclusion is an equality of TWO terms differing ONLY by the order of the
arguments of a COMMUTATIVE operation (whitelist: `= + * and or xor bvadd bvmul
bvand bvor bvxor`). `$x` names are expanded by the existing `expand` BEFORE the
comparison; the check is STRUCTURAL, the step has no premises.

MEASURED on `storeinv_t1_np_nf_ai_00002_001.cvc.smt2`: TRUSTED **5 -> 4**
(`bool` 12 -> 13). The residue was named by the dump:

```
[dbg-trusted] #1 lemma :: (lemma (unit-resolution @x184 @x104 false) $x162)
[dbg-trusted] #2 monotonicity :: (monotonicity @x101 (= (select ?x29 i1) ?x108))
[dbg-trusted] #3 lemma :: (lemma (unit-resolution @x184 @x81 false) $x145)
[dbg-trusted] #4 monotonicity :: (monotonicity @x101 (= ?x140 ?x156))
```

### 168.3 STEP 3 - A DUMP OF THE `unit-resolution` PREMISES (and a REVERTED fix)

The dump was added to the `.unverifiable` path (`KERN_DEBUG_TRUSTED`, `[dbg-ur-unver]`).
MEASURED on `QF_BV/add_three.4_bit.smt2` (the first trusted step):

```
цель: (or (not (or (not k!140) (not k!180))) (not k!220) (not (or k!140 k!180)))
  @x2893 => (or (or (not (or (not k!140) (not k!180))) (not k!220) (not (or k!140 k!180))) k!220)
  @x5139 => (not k!220)
```

So from `(C or k!220)` and `(not k!220)` EXACTLY `C` is derived - the step is CORRECT.
THE CAUSE of the refusal: the clause contains a NESTED `or`, hence `remaining` is ONE
literal `(or A B C)` while `concl` flattens into THREE -> a `1 != 3` mismatch.

**THE FLATTENING ATTEMPT (associativity of `or`) WAS REVERTED BY MEASUREMENT:**

| | TRUSTED on `add_three.4_bit` |
|:--|--:|
| before the change | **2970** |
| with both sides flattened | **3408** (WORSE, +438) |
| after the revert | **2970** (exactly as before) |

Hence the shape `(or (or A B C) k)` is handled by the EXISTING branches (partial
resolution / De Morgan / case splitting) BETTER than the flattened one, and the cure
must be a REWORK OF THOSE BRANCHES. The diagnosis and the dump are recorded IN THE
CODE next to `checkUnitRes` so that the knowledge is not lost with the revert.

### 168.4 TWO-SIDED TESTS (4 new, all non-vacuous)

| Test | What it checks |
|:--|:--|
| ABSORPTION POSITIVE | `(rewrite (= (and false (not (or …))) false))` -> `rewrite_verified == 1`, `trusted == 0`; mirror `(or true X) = true` |
| NON-ABSORPTION ATTACK | `(and true X) = true` and `(and false X) = true` -> `rewrite_verified == 0` |
| COMMUTATIVITY POSITIVE | `(commutativity (= (= a2 a1) (= a1 a2)))` -> `bool_verified == 1` |
| COMMUTATIVITY ATTACK | `(< a1 a2)` vs `(< a2 a1)` (non-commutative) and `(= a1 a2)` vs `(= a1 a3)` (operands not swapped) -> `bool_verified == 0` |

**NON-VACUITY CONFIRMED BY A PLANT:** replacing the expectation `1` with `7` makes
`make test` return **RC=2**: `error: … ABSORPTION POSITIVE … failed: expected 7, found 1`.

### 168.5 A PROCESS LESSON (paid for in practice)

1. The gates `ci-fast`/`edge-cases` were launched IN THE SAME BATCH as a plant inside
the file they verify -> both failed ON THE CORRUPTED FILE. That is exactly rule No. 1
of the plan ("never run a check in the same batch as an edit to what it checks"),
violated by me.
2. `pkill -f 'g431.sh'` killed ITS OWN command (its command line contained the same
text), so the plant was not removed; a separate command was needed.

### 168.6 REGRESSION: THE GATES AND THE GROWTH OF THE NUMBERS

MEASURED after the changes (all gates in a batch SEPARATE from the edits, rule No. 1 of §6):
`ci-fast` 11/0, `edge-cases` rc=0, `docs-map-check`, `status-check`, `docs-parity`,
`journal-parity-check`, `sync-check`, `metrics-guard`, `claims-audit`, `registry` - all
`rc=0`; **`smtlib-proof-check` rc=0** (4 tasks `[PROOF VERIFIED]`: `RC-02`, `RC-07`,
`RC-08`, `CircularTrains`; 0 false alarms, 0 holes); **`xray-check` rc=0** (25 sections
`[OK]`).

THE NEW CODE SHIFTED THE STATIC NUMBERS, and the guard caught it itself: mutation sites
**1432 -> 1455**, test declarations **482 -> 486**. Updated along the lines named by
`metrics-guard` (23 replacements in 14 files). AS A SIDE EFFECT THIS BROKE `edge-cases`:
its meta-tests "the guard noticed a plant" first require the BASE to be green, while the
base was red due to the number mismatch - that is, the meta-test was non-vacuous exactly
when the guard was really working.

BOUNDARY (stated honestly): the full mutation sweep on the NEW code (23 min) was NOT
re-run; the site count is the fact (1455), while "100 %" refers to the committed log
`docs/evidence/mutate_full.log` (1376/1376) - the same convention `sync_state.py` follows
(the `fact:mutation_sites` anchor is substituted into both numbers).

## §169. THE FALLBACK `remaining.len == 1`: 2970 -> 1020 TRUSTED STEPS

### 169.1 What was done

In `checkUnitRes`, in the branch that used to return "not verified", one line was added:

```zig
if (remaining.items.len == 1 and sexpEqNum(remaining.items[0], concl)) return .verified;
```

**SOUND:** `(or R1 … Rk) and not R1 … and not Rk-1 entails Rk`, and here `Rk == concl`.
The check sits in the FALLBACK, so the number of trusted steps **can only drop** - it
cannot grow by construction.

### 169.2 Why flattening `or` was the WRONG cure (measured)

In bitvector proofs the premise `(not (or A B))` cancels the literal `(or A B)`
ONE-TO-ONE. Flattening `or` at the beginning of the function destroys that literal BEFORE
the cancellation:

| | TRUSTED on `QF_BV/add_three.4_bit` |
|:--|--:|
| before any change | 2970 |
| with `or` flattened at the beginning | **3408** (worse) |
| after the revert | 2970 |
| **with the fallback `remaining.len == 1`** | **1020** (better by 1950) |

### 169.3 MEASURED after

| Task | trusted BEFORE | AFTER | first unrecognised rule |
|:--|--:|--:|:--|
| `QF_BV/add_three.4_bit` | 2970 | **1020** | `unit-resolution` -> **`def-axiom`** |
| `storeinv...00002_001.cvc` | 5 | **4** | `commutativity` -> `lemma` |
| `2PhLockVParam_RC-07` | 1 | **0** | - (`[PROOF VERIFIED]`) |

The number of tasks with `trusted == 0` is **4 of 7**; false alarms **0**, holes **0**.
Regression `audits/codecheck`: `checked 13 | trivial 3 | skipped 0`, findings **4**.

### 169.4 A NEW REPORTING DEFECT (#432, OPEN)

The `resolution` column of the checker report equals **5247 BOTH BEFORE AND AFTER** the
change, even though there are 1950 fewer trusted steps. Cause: the column prints
`unitres_checked` - the NUMBER OF STEPS of the rule, not the NUMBER OF VERIFIED ones.
The reader of the report cannot see that the work was done. The same class as `#428` and
`#430` (the number is there - the answer is not). The cure is Block 4 of
`PLAN_takt23`: separate `unitres_steps` and `unitres_verified`.

### 169.5 A two-sided test (non-vacuous)

The test `ХАРДКОР: остаток из ОДНОГО литерала, равного ВСЕЙ цели` was added:
* **POSITIVE:** `(unit-resolution @c1 @u1 (or A B C))` with the clause
  `(or (or A B C) k)` and the unit `(not k)` -> `verified`;
* **ATTACK 1:** the goal `(or A B Z)` (the residue does not equal it) -> not `verified`;
* **ATTACK 2:** a residue of two literals whose second is NOT cancelled by a unit -> not
  `verified`.
