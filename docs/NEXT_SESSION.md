# Resuming work on KERN: handoff at commit `fedce93`

> **I cannot open sessions myself, and I keep no memory between them.** Only what
> is written in this repository survives. This file exists so a new session
> resumes from measured facts instead of from a summary.
>
> **Read first, in this order:** `docs/STATUS.md` (generated: state and counts) →
> this file (open work) → `docs/PLAN_v2.7.2.md` (the plan) →
> `docs/CAPABILITY_MATRIX.md` (what is proven and what each proof does NOT show).

> **Facts (EN/RU, kept in sync by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->480 · CHECK <!-- fact:check_targets -->179 · cases <!-- fact:canfail_cases -->217 · anchors <!-- fact:anchors -->178 · registry <!-- fact:registry_targets -->233 · META <!-- fact:meta_targets -->39 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff

## Where we are

| Check | Value |
|:--|:--|
| Branch / tree | `main` = `fedce93`, clean |
| Registry | 233 targets · **179/179 CHECK** · 217 non-vacuous cases |
| Release | `v2.8.0` published (4 assets, `artifact-check` chained, `seal` valid) |
| Open technical defects | **0** (per `docs/STATUS.md`) |

## Open work — exact locations

1. **Drifting timing numbers are still presented as constants.**
   - `docs/METRICS.md:10529` — `Разделение ~1400×`
   - `docs/METRICS.md:10545` — `Python взрывается за 1.44 с`
   - `docs/METRICS.md:10668-10669` — `CT_RATIO 1.0003`, `EE_RATIO 68.80`
   - `docs/CAPABILITY_MATRIX.md:55-57` — the same two ratios
   Re-measured today: ReDoS `1.4237 с` (was `1.44`), `CT_RATIO=1.0035` (was
   `1.0003`), `EE_RATIO=86.8099` (was `68.80`). §159 already says "замер
   машинно-зависим", but the **range** is not written. Add the observed range and
   keep the **thresholds** as the stable claim (0.2 s; `CT < 3.0`; `EE >= 10.0`).

2. **Two of the ten proofs have no reproducing command** — only a snapshot:
   `docs/evidence/example_why_kern/lcm.log` (C, PR #1596) and
   `docs/evidence/thealgorithms_rust/binomial_coefficient.rs` (Rust, PR #1075).
   Either add targets that actually print those verdicts, or state "snapshot, not
   a command" (already done in `docs/TEN_PROOFS.md`).

3. **`docs/TEN_PROOFS.md` is not linked from the READMEs.** It is registered in
   `docs-parity` (19 pairs) and in `SURFACES`, but a reader will not find it.

4. **`make showcase-live` requires Zig 0.17 in `PATH`.** Without it the
   `zig-guard` target refuses by name (`[ОТКАЗ] … rc=2`, defect #392). Consider
   resolving `ZIG` automatically, or documenting the requirement next to the command.

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
