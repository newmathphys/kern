# KERN'S LIMITS — WHAT IT DOES **NOT** PROVE

This document exists because honesty sells better than marketing: every verifier has limits,
and the only difference is whether they are NAMED or hidden. Below are ALL measured limits,
with numbers and a way to reproduce each one.

## 1. `PROVEN` ≠ «the proof was checked»

The word `PROVEN` in `audits/EVIDENCE.md` is the **solver's** verdict. The proof checker
verifies the derivation SEPARATELY, so every `PROVEN` row must carry the trusted-step count
(defect `#474`):

| Marker | Meaning |
|:--|:--|
| `trusted 0` | solver and checker agree — the proof is checked |
| `[PROOF PARTIAL] trusted N` | HONEST LIMIT: N steps rely on solver axioms |
| `trusted ?` | the checker reported no counter (`ДОКАЗАНО (допущено)` — a weaker claim) |

**Measured over the corpus:** 44 formulas → **13** `trusted 0`, **11** `PARTIAL`, **20**
without a counter. For `QF_BV` partiality is essential: the derivation relies on bit-blaster
axioms `k!` — a free unprovable constant — so a strict offline check without a solver is
**impossible**. MEASURED on `hex_index_deepjit_hex_hi`: `ДОВЕРЕННЫХ 15`.

**Consequence for «proof-carrying artifacts»:** they are proof-carrying for LIA and Boolean
invariants; for BV they are `PARTIAL` with a named count. The way forward is a solver with
complete DRAT/LFSC certificates (cvc5 / Bitwuzla), not Z3 axioms.

## 2. Floating-point arithmetic is not modelled (QF_FP)

`f32`/`f64`/`float`/`double` are NOT supported: such functions get a NAMED skip
`вещественная арифметика (f32/f64) — модель QF_FP не поддерживается` (`#472`). Before that
fix they silently fell into `i64`, and `debt / equity` (f64/f64) was reported as a
division-by-zero panic although IEEE-754 yields `inf`/`NaN`. **Measured:** 138 such skips on
`TheAlgorithms/Rust`, 4 on `DeepJIT`, 6 on KERN's own Zig core.

## 3. Loop invariants are not modelled (Belnap N)

`while`/`for` are analysed as ONE iteration with the loop condition as a guard. A full
invariant (needs CHC/Horn) is not derived, therefore:
* an index depending on a loop-modified variable yields `[BOUNDS UNKNOWN]` — that is **N**
  (uncertainty), not a finding (`#315`, `#473`);
* findings inside a loop body are not accused without a witness.

## 4. Known false accusations are counted, not hidden

`#476` (OPEN): `len(<literal>)` in a guard is not unified with the literal length, so
`data = [1,2,3,4]; if 0 <= i < len(data): return data[i]` is accused with `i = -1`. The
function lives in `tests/fixtures/precision_known_fp/` and `make xray-precision` requires
EXACTLY one finding there — and will go red once the defect is fixed.

**Precision on third-party code is measured by machine** (`#475`): `precision_clean` → 0
findings, `precision_buggy` → 5/5, and the external corpus
`QuixBugs/correct_python_programs` is compared to a NAMED baseline (**21** false accusations
on 50 correct programs, target 0). That is debt stated as a number.

## 5. Interprocedural invariants are not checked

Length, non-zeroness and ranges guaranteed by the CALLER are not modelled (`#200`): if
`len > 0` is guaranteed outside, the divisor is still considered suspicious — but we do NOT
accuse (a skip is safer than a false accusation).

## 6. What is checked by WHAT (how to reproduce)

| Limit | Command |
|:--|:--|
| `trusted` next to `PROVEN` | `make evidence-trust` (+ `--selftest`) |
| precision/recall of `--xray` | `make xray-precision` |
| a subprocess without a timeout | `make spawn-check`, `make spawn-selftest` |
| memory of subprocesses | `make audits-mem-check` |
| arithmetic of the corpus | `make audits` |

## 7. Facts (machine-checked)

core <!-- fact:core_tests -->460 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->491 ·
CHECK targets <!-- fact:check_targets -->192 · can-fail cases <!-- fact:canfail_cases -->237 ·
anchors <!-- fact:anchors -->194 · registry targets <!-- fact:registry_targets -->253 ·
META <!-- fact:meta_targets -->46 · Lean theorems <!-- fact:lean_theorems -->147 ·
QuixBugs SMT <!-- fact:quixbugs.smt -->6 · QuixBugs differential <!-- fact:quixbugs.differential -->40
