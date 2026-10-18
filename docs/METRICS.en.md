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
