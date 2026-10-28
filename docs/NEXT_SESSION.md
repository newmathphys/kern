# Resuming work on KERN: handoff at commit `fedce93`

> **I cannot open sessions myself, and I keep no memory between them.** Only what
> is written in this repository survives. This file exists so a new session
> resumes from measured facts instead of from a summary.
>
> **Read first, in this order:** `docs/STATUS.md` (generated: state and counts) →
> this file (open work) → `docs/PLAN_v2.7.2.md` (the plan) →
> `docs/CAPABILITY_MATRIX.md` (what is proven and what each proof does NOT show).

> **Facts (EN/RU, kept in sync by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->480 · CHECK <!-- fact:check_targets -->180 · cases <!-- fact:canfail_cases -->218 · anchors <!-- fact:anchors -->179 · registry <!-- fact:registry_targets -->234 · META <!-- fact:meta_targets -->39 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff

## Where we are

| Check | Value |
|:--|:--|
| Branch / tree | `main` = `fedce93`, clean |
| Registry | <!-- fact:registry_targets -->234 targets · **<!-- fact:check_targets -->180/<!-- fact:check_targets -->180 CHECK** · <!-- fact:canfail_cases -->218 non-vacuous cases |
| Release | `v2.8.0` published (4 assets, `artifact-check` chained, `seal` valid) |
| Open technical defects | **0** (per `docs/STATUS.md`) |

## Open work — exact locations

1. **`make showcase-live` requires Zig 0.17 in `PATH`.** Without it the
   `zig-guard` target refuses by name (`[ОТКАЗ] … rc=2`, defect #392) instead of
   blaming `build.zig`. Options: resolve `ZIG` automatically, or document the
   requirement right next to the command (it is already stated in
   `docs/TEN_PROOFS.md`).

## Closed in the last session (for the record)

- **Drifting timing numbers** no longer read as constants: the observed RANGE is
  written next to each snapshot in `docs/METRICS.md` §159/§163 and
  `docs/CAPABILITY_MATRIX.md`, and the stable claim is the THRESHOLD (defect #393
  added the reproduction of two foreign defects; the range note is in the same commit).
- **Two foreign proofs are now reproducible from the repository** (defect #393):
  `docs/evidence/example_why_kern/lcm_numerator.c` and
  `docs/evidence/thealgorithms_rust/binom_step.rs`, each with a GUARDED twin that
  must be PROVEN. Gate: `make foreign-verdicts-check`.
- **`docs/TEN_PROOFS.md` is linked** from both READMEs (together with this file).
- **Defect #394**: the handoff document itself carried bare numbers; `sync-check`
  was green while they were stale, and only `claims-audit` caught it. Fixed with
  anchors, and the guard gap is recorded in `docs/METRICS.md` §166.

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
