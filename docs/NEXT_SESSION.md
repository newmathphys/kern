# Resuming work on KERN: handoff at commit `08eb5cd`

> **I cannot open sessions myself, and I keep no memory between them.** Only what
> is written in this repository survives. This file exists so a new session
> resumes from measured facts instead of from a summary.
>
> **Read first, in this order:** `docs/STATUS.md` (generated: state and counts) →
> this file (open work) → **`docs/PLAN_takt22.md` (the ACTIVE plan, not started)** →
> `docs/CAPABILITY_MATRIX.md` (what is proven and what each proof does NOT show).

> **Facts (EN/RU, kept in sync by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->480 · CHECK <!-- fact:check_targets -->182 · cases <!-- fact:canfail_cases -->222 · anchors <!-- fact:anchors -->183 · registry <!-- fact:registry_targets -->238 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff

## Where we are

| Check | Value |
|:--|:--|
| Branch / tree | `main` = `08eb5cd`, clean |
| Registry | <!-- fact:registry_targets -->238 targets · **<!-- fact:check_targets -->182/<!-- fact:check_targets -->182 CHECK** · <!-- fact:canfail_cases -->222 non-vacuous cases |
| Release | `v2.8.0` published (4 assets, `artifact-check` chained, `seal` valid) |
| Open technical defects | **0** (per `docs/STATUS.md`) |

## Open work

**All of it lives in `docs/PLAN_takt22.md` (EN) / `docs/PLAN_takt22.ru.md` (RU).**
That document is self-contained: base measurements, four answered questions, three
verified safety conditions, seven steps with acceptance criteria, boundaries, and
the working rules. Do not re-derive it — read it.

Short version of what it says:

| # | Step | Why |
|:--|:--|:--|
| 1 | **R4** in `docs_map_check.py` — compare the map's `§N` ranges with the real maximum | the map says `§1–§167` while the fact is **§168** (and `§1–§145` vs **§146**): **#404 recurred immediately** |
| 2 | **#405** — split the funnel into `checked` / `trivial` / `skipped` | **the funnel currently lies**: functions WITHOUT `if` ARE analysed (live proof: `ratio` and `add32` produce findings) yet are counted as `skipped` |
| 3 | **Dump the `no reason` bucket** (×2 on cmark) | statically unreachable, yet measured — needs a dump, not a guess |
| 4 | **Bitwise conditions via BV** + a `free_syms_in_path` flag | `& \| ^ << >>` over `Int` is unsound; `SAT` checks must refuse a path carrying free symbols |
| 5 | Ternary `?:` → `(ite …)` | `ternary: 6` in toolkit |
| 6 | `nil/null` (+49 C, +3 TS) with reset on `ptr=`, `ptr++`, `ptr+=`, `&ptr`, any call in TS | `nil/null` is the largest real reserve |
| 7 | **Mutation lock** for `canfail.py` | it mutates tracked files; one sabotage once reached `main` (`3067a1b`) |

**Correction to what this file said before.** The "no `if`" bucket was described as
"honest boundary, NOT a loss (nothing to branch on)". That is only **half** true:
there is nothing to branch on, but the obligations (overflow, division, bounds)
**are** checked there, and the counter reports those functions as `skipped` anyway.
That is defect **#405**, and it is why step 2 exists.

Both corpora are pinned by SHA (`27d942c8`, `0c3a9c33`) so "before/after" is
measured on identical bytes; the clones live in `~/.cache/kern/repos/`.


**Closed in THIS session (verification of all capabilities):**

1. **`make showcase-live-all` — every row of `docs/CAPABILITY_MATRIX.md` is now
   EXECUTED, not read.** Before this, the live showcase covered 7 of 42 matrix
   rows: a reader could verify 7 capabilities and had to take the other 35 on
   trust from prose. Measured 2026-10-28: **32 rows, 0 failures, 119 s total,
   slowest row 24.5 s.** Each row carries its external oracle and what it does
   NOT prove. The two long rows (full tree scan ~20 min, cross-architecture
   ~5 min) run only under `showcase-live-all-full`, and their commands are
   PRINTED even when skipped — nothing is hidden behind a flag.
2. **Four defects were found BY building that coverage** (they were invisible
   while the rows lived only as prose): #395 the showcase buffered its output
   (0 bytes in 87 s when redirected — a log reader cannot tell "running" from
   "hung"); #396 `quixbugs-replay` read the dataset from `/tmp` only, so after
   any cleanup the gate silently skipped (cache moved to `~/.cache/kern/repos`);
   #397 `make bridge` truncated its OWN summary line with `head -40`, so the
   Truth Gate verdict never appeared; #397.4 a wrong marker in my own showcase
   row (`false_equivalent` belongs to a different gate) made the row fail while
   the target worked.

What is deliberately NOT done (not a defect, a boundary):

- `claims-audit` is in the full contour, not in `ci-fast` — so a bare number in a
  file listed in `SURFACES` can drift until the full run (defect #394.4).
- KERN is not a scanner: it does not find bugs in foreign repositories on its own.

## Closed in the last session (with the evidence for each)

1. **Drifting timing numbers no longer read as constants.** The observed RANGE is
   written next to each snapshot in `docs/METRICS.md` §159/§163 and
   `docs/CAPABILITY_MATRIX.md`, and the stable claim is the THRESHOLD
   (0.2 s; `CT < 3.0`; `EE >= 10.0`).
2. **Two foreign proofs are now reproducible from the repository** (defect #393):
   `docs/evidence/example_why_kern/lcm_numerator.c` -> `[BV] [FAIL]` with a
   counterexample, and `docs/evidence/thealgorithms_rust/binom_step.rs` ->
   `[FAIL] binom_step: ПЕРЕПОЛНЕНИЕ типа u64`. Each has a GUARDED twin that must
   be PROVEN, so the refutation is not vacuous. Gate: `make foreign-verdicts-check`.
3. **`docs/TEN_PROOFS.md` and this file are linked** from both READMEs.
4. **`make showcase-live` states its Zig requirement FIRST** (defect #392):
   `tools/showcase_live.py` runs a preflight printing the exact version and the fix
   BEFORE the seven rows, so a missing Zig 0.17 no longer looks like a defect in the
   project. Measured: without Zig 0.17 the warning is the first line; with it the
   showcase is 7 rows / 0 failures.

5. **The C-like `--xray` skip histogram is MEASURED (defects #400, #401).** The
   summary used to claim "skipped N with explicit reasons" while printing NONE;
   reasons are now recorded, normalised into structural keys, printed, and the sum
   is checked against the counter. Measured: `cmark-gfm/src` 232 skips, 
   `toolkit/packages` 400 — sums match. Gate `tools/xray_skip_reasons_check.py`
   (called from `xray-check`), case `xray-skip-reasons`.
6. **Four FALSE `[DEAD BRANCH]` on real `cmark-gfm/src/utf8.c` removed (#401).**
   `if_derived` accumulated `(not cond)` for every exited block regardless of
   branch, so mutually exclusive branches contradicted each other (`str1 >= 160`
   AND `str1 < 160`) and the path became UNSAT. `_clike_conds_at` is nesting-aware
   now; `if_derived` is gone. Findings 4 -> 0 with coverage unchanged (76/308),
   while a genuinely dead condition is STILL found. Case `xray-nested-branch`.

## Process rules that repeatedly saved this project

1. **Verify every published number and command against the code**, not against a
   summary. Four of ten externally drafted "proofs" did not match the repository.
2. **Never batch an edit with a run of the thing being edited** — the two raced
   three times in one session and produced fake `IndentationError` / stale reads.
3. **Write large new files atomically** (`cat > file <<'EOF'` or one editor call).
   A series of `insert_line` calls into a growing file tore functions in half.
4. **`zig` in `PATH` may be the pip package `ziglang` 0.13** (it lives in
   `.venv/bin` on purpose, for `portable-bench`). Put the real Zig first, or the
   build fails with an error that blames our own `build.zig`.
5. **A new file carrying `fact:` anchors must be added to `SURFACES`** — the
   orphan-anchor guard refuses it otherwise (defect #246).
6. **A new CHECK target needs a `canfail` case and a `CASE_TARGET` entry**, and a
   new case needs the file it patches in `FAULTABLE`.

## What must NOT be claimed

- KERN is not a scanner: it does not find bugs in other people's repositories on
  its own (measured: 0 of 715 functions of foreign repos fall into the subset).
- `[BOUNDS] … length NOT known` is a candidate, not an accusation.
- SKIP / "outside the subset" is never a proof of correctness.
- The ReDoS and non-interference oracles are **measurements with thresholds**, not
  deterministic proofs.
