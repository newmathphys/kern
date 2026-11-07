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

## P0. The recall cost of `#495` — MEASURED (`#498c`, done)

The `#495` fix restricted the inc/dec detector to straight-line paths. Its cost is no longer
«documented», it is MEASURED:

1. `make svcomp-witness-check` after `#495`: **37 tasks, 11 UNSAFE confirmed by an external
   validator, 16 SAFE clean on the enumerated witnesses, 0 false alarms, 0 missed confirmations**
   (`docs/evidence/svcomp_after_495.log`).
2. `svcomp_baseline.py`: **TPR 1.00 / FPR 0.00** (10/10 unsafe, 0 false alarms on 5 safe) —
   identical to `docs/evidence/svcomp_baseline.log`.
3. BUT the probes showed a real hole: an UNRELATED `if (flag) {…}` before
   `int x = 2147483647; x++;` produced **0 findings** — the blanket ban silenced the very
   SV-COMP pattern the detector exists for. The rule is NARROWED (`#498c`): a finding is
   suppressed only when the branch/loop CONDITION mentions the variable; mutations are caught by
   a separate write counter. MEASURED after: unrelated `if` -> **1 finding**,
   `if (x==10) return; x++;` -> **0**, `cmark_autolink.c` -> **0**.
4. Acceptance met: the number in `docs/LIMITS` (RU+EN) is measured, not promised.

## P1. Publication (Step 2 of the ROI plan — built and gated, release PENDING credentials)

1. `action.yml` (composite) works from the RELEASE ARCHIVE: downloads
   `kerna-dist-v<ver>.tar.gz` + `SHA256SUMS`, verifies SHA-256 BEFORE extracting,
   `./kerna --doctor`, then runs `audit-delta` base->head: `rc=1` only on findings THIS change
   introduced, `rc=2` on degraded coverage, `rc=3` on a bad artifact.
2. `make action-check` proves the steps by EXECUTION (local `file://` release source, no network):
   8-case matrix + 7 negative controls; `make action-check REAL=1` runs 5 of them on the real
   27 MB archive.
3. `examples/ci/kern-gate.yml` is the copy-paste workflow; its inputs are checked against
   `action.yml` (a wrong input turns the gate red).
4. Publication is prepared in `.github/workflows/release.yml` (archive + `SHA256SUMS` for BOTH
   assets + `action-check` BEFORE publishing). Publishing itself needs `gh` and credentials that
   this machine does not have; the exact command is:
   ```
   gh release create v2.8.1 --title "KERN v2.8.1" --notes-file docs/RELEASE_NOTES_v2.8.1.md \
     kernc-x86_64-linux-musl SHA256SUMS dist-release/kerna-dist-v2.8.1.tar.gz \
     kern.intoto.jsonl kern.intoto.sig
   ```

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

- [x] reproduction receipt from a clean clone: **7/7 gates `rc=0`** with the documented
   prerequisites (`pip install -r requirements.txt`), log committed: `docs/evidence/repro_2026-11-07.log`.
   A BARE clone (no solver) reddens 5 gates WITH A NAMED CAUSE — and that run is what exposed `#499`;
- [x] `svcomp`: the recall cost of `#495` **MEASURED** — 37 tasks / 0 false alarms / 0 missed;
  TPR 1.00 FPR 0.00, and the rule NARROWED (`#498c`) so an unrelated `if` no longer hides the pattern;
- [ ] three unfamiliar corpora: precision published, every FP triaged;
- [ ] release published (the artifact is built and gated locally; needs `gh` + credentials);
- [x] `action.yml` works from the release archive and is proved by execution (`make action-check`),
  with `examples/ci/kern-gate.yml` checked against it;
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
