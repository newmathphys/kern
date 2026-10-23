# KERN — CAPABILITIES WITH PROOF

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->402 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->465 · CHECK <!-- fact:check_targets -->154 · cases <!-- fact:canfail_cases -->176 · anchors <!-- fact:anchors -->138 · registry <!-- fact:registry_targets -->198 · META <!-- fact:meta_targets -->30 · Lean <!-- fact:lean_theorems -->143 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

> English mirror of [`CAPABILITIES.md`](CAPABILITIES.md). Every claim below is
> **verified against the code and against real runs**. Where a claim turned out to be
> inaccurate, that is stated explicitly. Nothing is presented as proven without evidence.
>
> **Legend:** ✅ confirmed · ⚠️ confirmed with a caveat · ❌ incorrect

---

## 1. Finding logic bugs (QuixBugs)

**Claim:** "KERN detects **40/40** QuixBugs bugs by **live execution** — not by proof; the dataset's own tests are not a KERN metric (#231)."

**Status: ⚠️ the RESULT is right, the METHOD is not.**

| | |
|:--|:--|
| ✅ Result | **40/40** divergences, each confirmed by replaying the real function (`tools/quixbugs_check.py`) |
| ❌ Method | this is **NOT** a symbolic proof |

**How it actually works:** the bugs are caught by **really executing** the official
QuixBugs test cases:
```python
spec = importlib.util.spec_from_file_location(name, path)
spec.loader.exec_module(m)          # load the buggy module
run_cases(fn, cases, timeout=1.0)   # run the tests + timeout (hangs)
```
This is a **dynamic run**, not a Z3 proof. The difference matters: a dynamic run only
catches the bugs for which a test case exists.

**Symbolic proof** is used in the other checks (§2, §4, §5).

---

## 2. Proving the equivalence of optimisations (Alive2 / Hacker's Delight)

**Claim:** "KERN proves the correctness of optimisations and finds a counterexample for a
false signed shift."

**Status: ✅ CONFIRMED** (`src/smt_bench.zig`, 8 contracts)

| Contract | Expectation | Meaning |
|:--|:--|:--|
| `x*2 == x<<1` (u32) | `unsat` | equivalent ✅ |
| `x*2 == x+x` (Int) | `unsat` | equivalent ✅ |
| `x+0 == x` (Int) | `unsat` | equivalent ✅ |
| `(x & -x) == 0 ⇔ x == 0` (u32) | `unsat` | equivalent ✅ |
| `x & 0 == 0` (u32) | `unsat` | equivalent ✅ |
| `gcd(x,x) == x` (x>0) | `unsat` | equivalent ✅ |
| **`x/2 == x>>1` (signed)** | **`sat`** | **false optimisation**, counterexample `x=-1` ✅ |
| **there exists `x+1 < x` (u32)** | **`sat`** | overflow, counterexample ✅ |

**Result 8/8.** The proof covers the **whole value domain** (2³² combinations), not a sample.

---

## 3. Acting as a gateway for external models (Admission Gate)

**Claim:** "KERN stands between the LLM and production: unverified code → `e=0`."

**Status: ⚠️ CONFIRMED, but without improving pass@1.**

| Metric | Value |
|:--|--:|
| Precision of blocks | **100 %** (all 55 blocked samples really failed, **0 false positives**) |
| Recall (how many failures were found) | 70.5 % |
| **Effect on pass@1** | **0** (0.524 → 0.524) |

**Honestly:** the static gate does **not** raise pass@1 — it fires before the tests run.
Its value is a **zero false-positive rate**: it never blocks working code. Actually
filtering out logic errors requires **execution** (the Execution Runner), not static
analysis.

---

## 4. Locating the exact offending line (UNSAT Core)

**Status: ✅ CONFIRMED** (`src/verifier/unsat_core.zig`)

```
Input:  premises line_10 (x>=0), line_12 (x<=100), goal line_25 (x<0)
Output: guilty lines = [line_10_non_negative, line_25_post_bug]
        (line_12 is NOT in the core — minimality was checked)
```
Uses `(assert (! … :named …))` + `(get-unsat-core)`.

---

## 5. Synthesising code from a specification (CEGIS / SyGuS)

**Status: ✅ CONFIRMED** (`src/verifier/cegis.zig`)

| Check | Result |
|:--|:--|
| Synthesis for the spec `x*8` | **`(bvshl x (_ bv3 32))`** — proven over the whole domain (`unsat`) |
| Check that `x*8 ≢ x<<2` | **`sat`** — counterexample found |
| Grammar enumeration | 4 checks, 3 counterexamples rejected |

Every candidate is **verified** through Z3; only `unsat` is accepted.

---

## 6. Memory safety and portability

**Claim:** "Merkle + SHA-256, ARM64 without Bus Error, PowerPC big-endian, 0.0001 ms."

**Status: ⚠️ CONFIRMED, one number is stale.**

| Guarantee | Check | Status |
|:--|:--|:--|
| Byte substitution in the image | `MerkleRootMismatch` | ✅ |
| **Payload** substitution | `PayloadTampered` (`SHA-256(payload) == digest`) | ✅ |
| ARM64 (strict alignment) | QEMU: **<!-- fact:cross_arch_passed -->394 passed / <!-- fact:cross_arch_skipped -->8 skipped / 0 failed** (`docs/evidence/cross_arch.log`, 2026-10-19) | ✅ run on the CURRENT suite (<!-- fact:cross_arch_passed -->394 passed + <!-- fact:cross_arch_skipped -->8 skipped) |
| POWERPC64 (**big-endian**) | QEMU: **<!-- fact:cross_arch_passed -->394 passed / <!-- fact:cross_arch_skipped -->8 skipped / 0 failed** (same log) | ✅ same run |
| Random access (1M objects) | **0.0006 ms** (target < 0.005) | ⚠️ was 0.0001 before the integrity FIX |
| Zero-copy | slice addressing without copying | ✅ |

**Throughput note:**
- **RAW addressing** (no verification): 55–76 GB/s;
- **safe read** (+SHA-256): 164–231 MB/s.

The difference is the price of checking integrity on every read.

---

## 7. Finding vulnerabilities (ReDoS / Path Traversal)

**Status: ✅ CONFIRMED** (`src/verifier/redos.zig`, `string_theory.zig`)

| Attack | Result |
|:--|:--|
| `(a+)+$` — catastrophic backtracking | **vulnerable** (found symbolically) |
| `(a\|a)*` — ambiguity | **vulnerable** |
| `(a\|b)*` — safe | not vulnerable ✅ |
| Path traversal `..` when stripping `/` | **VULNERABILITY** (counterexample exists) |
| Null-byte injection | **REACHABLE** |

---

## 8. Proving probabilistic properties (DTMC / PCTL)

**Status: ✅ CONFIRMED** (`src/verifier/dtmc.zig`)

```
Model: 3 transmission attempts, channel reliability 0.9
Question: P(total failure)?
Answer:   P = 0.1³ = 0.001   (f64 with a 1e-9 tolerance: in binary floating point
                          0.1³ is 0.0010000000000000002, that is NOT 0.001.
                          The exact identity 1/10³ = 1/1000 holds only in
                          RATIONAL arithmetic — see defect #328)
```
Both the threshold (`P ≤ 0.001`) and the reachability of the failure state are checked.

---

## 9. Protecting against side-channel attacks (Constant-Time)

**Claim:** "Spread 1.01× — practically perfect constant-time."

**Status: ⚠️ CONFIRMED, the threshold in the test is looser.**

| Check | Value |
|:--|:--|
| Static taint analysis (`noninterference.zig`) | branch/index on a secret → **leak** ✅ |
| Measured constant-time | in practice **~1.0×** |
| **Threshold in the test** | `ct_ratio < 3.0` (headroom for scheduler noise) |
| Control: early exit | **depends** on the position of the difference ✅ (the check is not vacuous) |

**Honestly:** the test allows a spread of up to 3×. The measured value is close to 1.0×,
but that is not a "1.01× guarantee".

---

## 10. Proving loops without unrolling (Abstract Interpretation)

**Status: ✅ CONFIRMED** (`src/verifier/abstract_interp.zig`)

| Loop | Invariant | Status |
|:--|:--|:--|
| `x:=0; while(x<10) x+=1` | **`[0,9]`**, exit `x>=10` | ✅ |
| `x+=2` (step 2) | **`[0,9]`** | ✅ |
| growing counter | **widening → +∞** (termination guarantee) | ✅ |

**Important:** it works **without Z3** — pure interval arithmetic.

---

## 11. Weak memory models (Litmus SB / MP)

**Status: ✅ CONFIRMED** (`src/tests/litmus_memory_test.zig`)

| Test | Check | Result |
|:--|:--|:--|
| **SB** (Store Buffering), `SeqCst` | outcome `r1=r2=0` forbidden | **0 forbidden** out of 20 000 iterations ✅ |
| SB, `relaxed` | outcome possible on a weak model | reported (not a verdict) |
| **MP** (Message Passing) | `release`+`acquire` | 0 forbidden ✅ |

---

# Formal guarantees (Lean 4)

8 files, **143 theorems, 0 `errors`, 0 `sorry`**. Compiled by `./formal/check.sh`.

| Theorem | File | What it proves |
|:--|:--|:--|
| `deMorgan_andT` / `deMorgan_orT` | `KernAllMath.lean` | De Morgan's laws in the truth order |
| `contradiction_isolation` | `KernAllMath.lean` | `T ⊔ F = B` — a conflict is NOT overwritten |
| `vacuous_precondition_impossible` | `KernAllMath.lean` | vacuous code (`pre ≡ False`) is rejected |
| **`fuel_bounds_influence`** | `KernAllMath.lean`, `KernDfsTermination.lean` | fuel bounds the influence zone (induction) |
| `traversal_terminates` | `KernDfsTermination.lean` | the traversal terminates on a well-founded graph |
| `ai_hallucination_yields_conflict` | `KernTalk.lean` | `human.max < ai.min ⇒ unify = B` |
| `nd_violation_yields_conflict` | `KernTalkND.lean` | a violation in at least 1 of N dimensions ⇒ global `B` |
| `convergence_guaranteed` | `KernConvergence.lean` | the iteration succeeds in a finite number of steps |
| `zero_copy_is_lossless` | `KernZeroCopy.lean` | an mmap slice does not distort bytes |
| **`no_blanket_transfer`** | `KernSemanticGap.lean` | ℤ properties do **not** carry over to i32 without a guard |
| `int32_gap` | `KernSemanticGap.lean` | `∃ x: x+1` leaves the i32 domain (guards against a false "PROVEN") |
| `int_not_le_iff` | `FarkasSoundness.lean` | integer negation used by the proof checker: `¬(l ≤ r) ↔ r - l + 1 ≤ 0` |
| `farkas_2_sound` / `farkas_3_sound` | `FarkasSoundness.lean` | soundness of a Farkas combination with `w_i ≥ 0` and remainder `c > 0` |
| `three_valued_check_sound` | `FarkasSoundness.lean` | `verified \| bad \| unverifiable` never admits a `bad` step |
| `vacuous_requires_unsound` | `FarkasSoundness.lean` | if `∀ x, ¬P x`, then `∀ x, P x → Q x` holds for any (even false) `Q` |
| `skip_preserves_belnap_join` | `FarkasSoundness.lean` | joining with a skipped witness `N (0,0)` is neutral: `JOIN_K(x, N) = x` |

> **Honestly:** two theorems used to be **tautologies** (`∃ res, f = res` holds for any
> function) — they were replaced with meaningful ones. See `docs/METRICS.md` §20.3.

---

# Epistemic honesty (self-audit)

**KERN was run through itself** (`make bridge` + the scanner + the Execution Runner).

| What KERN did | Result |
|:--|:--|
| Read its own README | 11 claims → status `verified` (the documents exist) |
| Checked them with the Gate of Truth | **`e=0` on ALL claims** — "text is not a contract" |
| Found unfinished work | 1 real blocker: `HumanEval/26` — a `# TODO: Implement me` stub |
| Found a defect **in its own scanner** | 2 false blockers (it counted its own regex patterns as TODO) |

**The main conclusion of the self-audit:**

> When KERN was run through itself, the Gate of Truth returned `e=0`
> **for every textual claim in the README**. Text is not a contract.
> KERN trusts only machine formulas and reproducible runs.

This is exactly why this project has **not a single number without the command** that
reproduces it. The difference between "written" and "proven" is the subject of the project.

---

# Summary

| # | Capability | Status |
|:--:|:--|:--|
| 1 | Bug finding (QuixBugs) | ⚠️ **40/40**, but by **execution**, not by proof (#231) |
| 2 | Equivalence of optimisations | ✅ 8/8 symbolically |
| 3 | Gateway for LLMs | ⚠️ 100 % precision, but pass@1 does not grow |
| 4 | UNSAT Core | ✅ with a minimality check |
| 5 | Code synthesis (CEGIS) | ✅ `(bvshl x 3)`, verified |
| 6 | Integrity + portability | ⚠️ x86_64 (host) **402 / 402**; QEMU ARM64/POWERPC64 — **<!-- fact:cross_arch_passed -->394 passed / <!-- fact:cross_arch_skipped -->8 skipped / 0 failed** (2026-10-19); access **0.0006 ms** |
| 7 | ReDoS / Path Traversal | ✅ counterexamples found |
| 8 | Probabilities (DTMC) | ✅ 0.1³ = 0.001 in f64 with a 1e-9 tolerance (exact only in rational arithmetic, #328) |
| 9 | Constant-Time | ⚠️ in practice ~1.0×, test threshold 3.0 |
| 10 | Loops (Abstract Interp) | ✅ `[0,9]` without Z3 |
| 11 | Weak memory models | ✅ 0 forbidden outcomes |

**Principle:** where proof is impossible (execution facts, physical quantities) KERN
honestly says `e=0` instead of passing off a wish as a proof.


## Contract classes and hypothesis diagnosis (v2.6.0)

| | |
|:--|:--|
| ✅ `[advisory]` | `# @kern:ensures result >= x + y  [advisory]` — the promise is still recorded and checked, but a violation does not block |
| ✅ Verdict | `T_advisory` is a **separate** verdict; it is **never** added to the proven count `T` (`proven 1 | T_advisory 1`) |
| ✅ Lock | the class is part of the fingerprint (`fn:ensures:advisory`), so flipping `hard -> advisory` without updating the lock breaks `make contracts-lock-check` |
| ✅ Gate | `make advisory-check` proves three things: advisory does not block, `T_advisory` never becomes `T`, `hard` still blocks |
| ✅ `explain --hypotheses` | read-only hint about the missing `requires` (`kern_contracts.py explain --hypotheses FILE`) |
| ✅ Honesty | a candidate that makes `requires` contradictory is **rejected out loud**; for bodies obtained by unrolling a loop/recursion no hypotheses are emitted at all (#295) |
| ❌ NOT | the tool **never** edits the file and **never** weakens `ensures` |
| ✅ Gates | `make explain-hypotheses-check` (read-only, determinism, non-vacuity) and `make hypotheses-corpus-check` (every hypothesis is replayed on a copy to `T`) |
