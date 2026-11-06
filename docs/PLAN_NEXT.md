# PLAN FOR TOMORROW — prove that KERN works

State when written: `HEAD == origin/main == f23f7713` (attests `#497`), clean tree,
`ci-fast rc=0`, `known_fp = 0`, `#495` closed, release archive built and verified as a client.

## The principle of this tact

**After the fixes the task is not to ADD, but to PROVE.** Today's green gates are SELF-checks:
the tool verifies itself with its own instruments. That is not proof of work until an
**independent person** gets **the same numbers** on **their own** machine and on **unfamiliar**
code. Everything below serves that single goal.

## P0. Reproduction receipt (half a day)

Goal: one external run that cannot be faked.

1. `git clone` into a **clean** directory outside the working folder (`/tmp/kern-repro`), **without**
   `~/.cache/kern`.
2. Run `make ci-fast`, `make tour`, `make xray-precision`, `make xray-overflow-check`, `make audits`,
   `make pcc-offline-check`, `make verify-attestation` under the **system** `python3` (not `.venv`)
   wherever that is applicable.
3. Record: each gate's `rc`, wall time, versions (`python3`, `zig`, `gcc`), `uname -a`.
4. Put the result into `docs/evidence/repro_<date>.log` and **commit** it — that is the receipt.
5. Acceptance: **every** listed gate `rc=0` on a clean clone; any divergence from today's numbers is
   a **defect**, not an «environment quirk».

## P0. The recall cost of `#495` — the only unmeasured number (2–3 hours)

The `#495` fix deliberately restricted the inc/dec detector to straight-line paths. The cost is
**not measured**.

1. Run `make svcomp-witness-check` (long, in the background) and compare with the previous baseline.
2. If recall dropped — refine the rule: allow a loop when the variable is **not modified inside it**
   (`for (…) { if (c) return; } x--;`), then measure again.
3. Acceptance: the number in `docs/LIMITS` (today it says only «recall loss documented») replaced by
   the **measured** value.

## P1. Proof on unfamiliar code (a day)

Curated corpora (`QuixBugs`, `TheAlgorithms`, `cmark`, `DeepJIT`) stop counting as proof: they were
seen during development.

1. Fresh clones of **three** repositories that were never in the cache: `tigerbeetle` (Zig),
   `redis` (C), `curl` (C). No edits in them.
2. For each: `./kerna <path> --sample N` + **triage of EVERY** finding by hand:
   TP / FP / N (uncertainty) / caller-guarded.
3. Compute **precision = TP / (TP + FP)** and publish it **together with the FPs**, not TP only.
4. Acceptance: `precision ≥ 0.90` on at least two of the three corpora; otherwise — an honest FP-class
   record in the `#495` style (fixture + counter), never silence.

## P1. Publication: what is already built (2 hours)

1. GitHub Release `v2.8.1`: `kerna-dist-v2.8.1.tar.gz` (27 MB) + `SHA256SUMS` + attestation.
2. `action.yml` (composite): downloads the release, runs `kerna` + `audit-delta` on a PR, `rc=1` on a
   new finding, `rc=2` on degraded coverage.
3. Acceptance: a sample workflow in `examples/ci/` passes on a **test** repository; without a release
   `action.yml` is **not** published (a promise without an artifact is forbidden — lesson `#497`).

## P2. Core debt (only with a budget and a measurement)

| # | What | Why not now |
|:--|:--|:--|
| `#200` | interprocedural closures (1 of the 4 remaining `QuixBugs` accusations) | research work; the win is 1 FP |
| `#480` | BV certificates without a solver | requires a different solver (Bitwuzla/cvc5, DRAT/LFSC) — a product decision |
| — | new languages/theories | forbidden by the stop-rule until `precision ≥ 0.90` on unfamiliar code |

## Discipline of the tact

1. Every claim in a report carries a **number and the command** that produced it.
2. A hypothesis is checked by **measurement before the edit** (today that refuted «obvious» causes
   three times).
3. A false accusation is counted and named; «green» without a number is not a result.
4. Sealing (`make seal`) only on a clean tree, after a green `ci-fast`.

## Definition of Done for «the project is proven to work»

- [ ] reproduction receipt from a clean machine: all gates `rc=0`, log committed;
- [ ] `svcomp`: the recall cost of `#495` **measured** and written as a number;
- [ ] three unfamiliar corpora: precision published, every FP triaged;
- [ ] release + (optional) `action.yml` with a working example;
- [ ] `LIMITS` (RU+EN) synchronised with the gates — its guard green;
- [ ] clean tree, `HEAD == origin/main`, attestation verified with the external key.

## Checkable facts (verified by `make docs-parity`)

- core tests <!-- fact:core_tests -->460
- next tests <!-- fact:next_tests -->53
- catalog <!-- fact:catalog -->491
- CHECK targets <!-- fact:check_targets -->199
- can-fail cases <!-- fact:canfail_cases -->244
- anchors <!-- fact:anchors -->203
- registry targets <!-- fact:registry_targets -->271
- META targets <!-- fact:meta_targets -->54
- Lean theorems <!-- fact:lean_theorems -->147
- QuixBugs SMT <!-- fact:quixbugs.smt -->6
- QuixBugs differential <!-- fact:quixbugs.differential -->40
