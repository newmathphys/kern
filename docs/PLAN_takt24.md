# TACT 2.4 — FIXING THREE FALSE-ACCUSATION CLASSES (`#471`, `#472`, `#473`)

**Status:** done. `HEAD` before the tact: `2ea0a6d6`.
**Why:** hunting third-party code (5 languages, 6 corpora) gave **56 % precision** on
`TheAlgorithms/Rust`: 18 findings, 8 of them false. A false accusation is the worst outcome
(lesson `#178/#183`), so precision comes before coverage.

## 1. Measured BEFORE and AFTER (same corpora, same call)

| Corpus | checked | skipped | findings BEFORE | findings AFTER |
|:--|--:|--:|--:|--:|
| `TheAlgorithms/Rust` | 356 → 331 | 77 → 191 | **18** | **10** |
| `QuixBugs` (Python) | 70 → 70 | 14 → 14 | **62** | **42** |
| `cmark-gfm` (C) | 221 → 221 | 25 → 25 | **5** | **5** |
| `DeepJIT` (C++20) | 76 → 75 | 19 → 23 | **1** | **1** |
| `kern/src` (Zig) | 155 → 154 | 27 → 33 | **0** | **0** |

The funnel identity `Σ checked + trivial + skipped == total` holds in every corpus — no
invisible functions. On `QuixBugs` the set of REAL findings is byte-identical
(31 `[BOUNDS PATH]` + 6 `[CRASH PATH]` + 5 `[SMELL]`): exactly class N left the counter.

## 2. The three defects

* **`#471`** — the guard was lost in THREE places: (a) Python: the scan at `ast.If` walked the
  whole construct, `orelse` included, with the direct guard instead of `(not cond)`;
  (b) C-like: the body of `while` was analysed without the loop condition; (c) C-like: the
  `else` branch got no negation at all.
* **`#472`** — `f32`/`f64` silently fell into the integer domain → a false
  "division-by-zero panic". Now a named skip: QF_FP is not modelled.
* **`#473`** — `[BOUNDS UNKNOWN]` (Belnap N) was counted as a finding under a second label.

## 3. What the tact itself taught (record it, do not repeat)

**The first version of `#471c` was wrong and MUTED real findings.** It ADDED `(not cond)` to a
path that already carried the direct `cond` (`if_blocks` registers `if/else` as ONE block).
That produced `cond ∧ ¬cond` = UNSAT and `modular_exponential` — a genuine `modulus == 0` —
disappeared from the report. Caught by comparing the finding LISTS before/after, not the
counter. Rule: **a guard fix must be verified by the list of findings, not only by their count.**

## 4. Gates that now protect this

* `make xray-check` — block `#471a/b/c + #472 + #473` over
  `tests/fixtures/xray_crash_guards/{guards.py,guards.rs}`: **5 silent** cases and
  **3 TP controls** — exactly `находок 3`.
* can-fail cases `xray-guard-else`, `xray-while-guard`, `xray-float-skip` — each disables
  exactly one fix and must turn the gate red (231 → **234** cases).

## 5. Left in the plan (next tacts)

1. **`#474`** — `audits/EVIDENCE.md` prints `PROVEN` for BV while the proof checker says
   `[PROOF PARTIAL] trusted: 15` (MEASURED on `hex_index_deepjit_hex_hi`). BV rows need a
   `trusted` column; `PROVEN` without `trusted: 0` is a forbidden word.
2. **Mutation sweep** — cut at 704/1597 (machine powered off). Restart on a clean tree, then
   `docs/evidence/mutate_full.log` 1345 → **1597** and `README` 1376 → 1597, with the kill
   split `test / compile / timeout`.
3. **Precision gate** `make xray-precision`: `QuixBugs/correct_python_programs` (50 files) →
   **exactly 0** findings; `TheAlgorithms/Rust` → precision ≥ 0.90.
4. **`spawn` choke point** — 168 `subprocess.run` sites versus 15 with a limit (class `#470`).
5. **`premises_unbound`** — unsigned premises: until they bind, there is no automatic
   certificate for BV (handwritten `.smt2` stays a workaround).
6. **Docs:** `docs/LIMITS.md` ("what KERN does not prove"), `CAPABILITY_MAP`
   (189 CHECK → which property), two coverage metrics (`checked/total` vs
   `checked/(checked+skipped)`).

## 6. Positioning (decided in this tact)

Not an "antivirus" (it promises "catches everything" while precision is 56 % → ≈ 90 % after
this tact) and not a "prover for everyone". The face is: **an admission gate for
AI-written code** — "may this code go further", with four Belnap states (`T/F/B/N`) and an
artifact. The B2B differentiator: **proof-carrying artifacts** — honestly: for LIA/Boolean;
for QF_BV a `[PROOF PARTIAL]` with a named count of trusted steps.

## 7. Facts of the tact (machine-checked)

core <!-- fact:core_tests -->460 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->491 ·
CHECK targets <!-- fact:check_targets -->189 · can-fail cases <!-- fact:canfail_cases -->234 ·
anchors <!-- fact:anchors -->192 · registry targets <!-- fact:registry_targets -->248 ·
META <!-- fact:meta_targets -->44 · Lean theorems <!-- fact:lean_theorems -->147 ·
QuixBugs SMT <!-- fact:quixbugs.smt -->6 · QuixBugs differential <!-- fact:quixbugs.differential -->40
