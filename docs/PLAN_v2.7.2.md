# PLAN v2.7.2 — Stage 1–2 (core and semantics) cleaned to zero

Status: **COMPLETED** (opened and closed 2026-10-25, version `v2.7.2`).

This plan is the follow-up to [`PLAN_v2.6.4.md`](PLAN_v2.6.4.md). It was opened
because the v2.7.1 cycle left **fourteen** defects that were diagnosed and
recorded, but deliberately not fixed "on the run". The goal was to clean the
core-and-semantics stage to zero before touching external benchmarks.

---

## §0 State at the start of this cycle

| Closed | How it is proven |
|:--|:--|
| **#343** version drift in the JSON report | `_kern_version()` reads `server.json`; `version_check.sh` verifies the **12th surface** — the actual `--json` output |
| **#344/#341** `define-fun` expansion + constant arithmetic | `evm-proof-check`: `посылок 1/1 \| ДОВЕРЕННЫХ 0 \| дыр 0` on all three EVM identities |
| Release v2.7.1 | signed tag; 4 assets including `kern.intoto.jsonl` and `.sig` |

Registry at the start: **<!-- fact:registry_targets -->214 targets ·
<!-- fact:check_targets -->163 CHECK · <!-- fact:canfail_cases -->195 can-fail cases**.

### The defect this cycle starts with

**#349 — `evalConstInt` divided two different ways.** The constant reducer added
in #344 computed `div`/`mod` as *floor* for **any** sign of the divisor, while
SMT-LIB2 defines them **Euclidean** for sort `Int`. Measured in Z3:
`(div 1 (- 2)) = 0`, `(mod 1 (- 2)) = 1`, `(div (- 7) (- 2)) = 4` (not `3`).
Three consequences, all of them soundness:

1. `(= (div 1 (- 2)) (- 1))` was accepted as **proven** — a false identity;
2. `@mod(a, b)` with `b < 0` **panics** in Zig ("modulus is negative"), so the
   checker crashed on input it is obliged to read;
3. the overflow guard `-@divFloor(a, -b)` was **dead code**: the literal
   `-9223372036854775808` (MIN) was never parsed at all (the modulus `2^63` does
   not fit `i64`), so the test "passed" for the wrong reason.

The panic was caught by plan review **before** any code was written; the dead
guard was found while implementing the fix.

---

## §1 Work order and acceptance criteria

Order matters: each step is `test → code → can-fail case → registry → sync →
gates → commit`. `abs/min/max` came before the `ValueSemantics` refactor so that
the refactor could be checked against a *measured* baseline.

| Step | What | Acceptance (numbers) |
|:--|:--|:--|
| 1 | `evalConstInt`: Euclidean `div`/`mod` for `b < 0`, explicit MIN parsing, checked `std.math.add/sub/mul`, `q == minInt → null`, **four Lean theorems** (§95.4) | 8+ points, negative tests mandatory; `evm-proof-check` still `trusted: 0`; `lean` rc=0, `0 sorry` |
| 2 | `CHARTER.md` / `.ru.md`: L4/L5 → **PROVEN**, §3 rewritten as history, new gate `charter-text-check` | charter text == `charter-check` output; non-vacuous case |
| 3 | `--xray tools/` → **0** (empty-`.kimg` guard, `@deal.pre` modelled) | `0 [BOUNDS PATH]`, `0 [CRASH PATH]`; two-sided fixture in `xray-check` |
| 4 | `abs` / `-x` / `min` / `max` in `arith-semantics-check` | **0 mismatches** on 180 points incl. `i32` edges; non-vacuity control (naive `abs` differs in 4) |
| 5 | `ValueSemantics`: `signed_min_div_trap`, `signed_min_neg_trap`, `allow_bv_fallback`, `bounded_ints` | **KILL CRITERIA**: `codecheck` `TP=6, TN=6, FP=0, FN=0`; `contracts` 11 proven / 4 violated — unchanged |
| 6 | `#342`: `# @kern:lang evm` frontend | with the directive `2 PASS`; **without** it the same code violates the contract (otherwise the directive changes nothing) |

---

## §2 Kill criteria

* **Step 5** is a *description move*, not a rule change. If any verdict moved,
  the refactor would be reverted, not adjusted. Measured: no verdict moved.
* **Step 6** must be **two-sided**: a directive that cannot change a verdict is
  not a frontend, it is a comment. The gate fails if the no-directive run does
  not violate.
* **Step 3** must stay two-sided in the same sense: a detector that never
  accuses is blind, and one that always accuses lies (lesson of #178).
* **Step 1** negative tests are mandatory: `(= (div 1 (- 2)) (- 1))` and
  `(= (div (- 7) (- 2)) 3)` **must be rejected**. A test that cannot fail proves
  nothing — that is exactly the #345 lesson.

---

## §3 What is deliberately NOT in this cycle

| Out of scope | Why it is named instead of quietly skipped |
|:--|:--|
| EVM **bytecode** disassembler (`0x6080...`) | The frontend accepts *expressions and contracts*, not bytecode. `#342` was about "no parsing path sets `lang=evm`" — that is closed; a disassembler is separate work |
| Full `while` loop invariants (`#315`) | The CHC/Horn engine works in the core but is not wired into the automatic walk; today the verdict degrades to an honest `UNKNOWN` with the reason named |
| Variable exponent `a ** b` / `pow` (`#307`) | Not in the decidable linear/BV subset |
| Exact rational probabilities in `dtmc.zig` | `f64` with error `2.17e-19` is documented as such (#328); an integer `num/den` mode is not implemented |
| Interprocedural contracts, separation logic, differential Datalog | No implementation; no claim. Listed here so the absence is visible |

---

## §4 Result

| Metric | Value |
|:--|:--|
| Defects closed | **14** (#312, #322, #325, #335, #342, #344/#341, #345–#353) |
| Lean 4 | **<!-- fact:lean_theorems -->147 theorems, `0 sorry`** |
| can-fail harness | **<!-- fact:canfail_cases -->195 non-vacuous / 0 vacuous / 0 case errors** |
| Self-scan `--xray tools/` | **0 `[BOUNDS PATH]`, 0 `[CRASH PATH]`** |
| Registry | **<!-- fact:registry_targets -->214 targets, highest defect number <!-- fact:max_defect -->362** |
| CHECK targets | **<!-- fact:check_targets -->163**, each with a non-vacuous case |

The cycle is closed. The next cycle starts from the §3 "out of scope" list above,
in the order the evidence justifies.
