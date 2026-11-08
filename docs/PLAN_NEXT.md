# PLAN FOR TOMORROW — prove that KERN works

State at the end of 2026-11-07: `HEAD == origin/main == 86fef8ee`, clean tree, attestation verified
with the external key, **`KERN CI` green** (job `verify` success, step CAN-FAIL success,
`ВАКУУМНЫХ 0` — both blind cases `#514` closed), open technical defects **0**, release `v2.8.2`
published by `release.yml` (the tag is 3 commits behind `HEAD` — see T1 below).

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

## P1. Proof on unfamiliar code — MEASURED: 0.375 → **1.00** (target met on TWO slices)

BLIND RUN on three repositories that were never in the cache
(`docs/evidence/blind_p1_2026-11-07.log`): curl `155f6f76` (lib/), redis `5b69ba2c` (src/),
tigerbeetle `68958eb7` (src/); deterministic selection = first 25 files by name per corpus;
0 edits to the analyzer before the run.

| corpus | files | functions | findings | TP | FP | precision |
|:--|--:|--:|--:|--:|--:|--:|
| curl/lib | 25 | 81 | 0 | — | 0 | n/a (no accusations, and no noise) |
| redis/src | 25 | 552 | 7 | 3 | 4 | 0.43 |
| tigerbeetle/src | 22 | 187 | 2 (1 duplicated) | 0 | 1 | 0.00 |
| **total** | | | **9** | **3** | **5** | **0.375** |

AFTER the fixes (same SHAs, same selection rule) — precision **1.00**:
`#500`/`#501` closed roots A and B, `#502` closed the duplicate; re-measure gave redis **4 TP / 0 FP**,
tigerbeetle **0**, curl **0**. The EXTENDED slice (60 files per corpus, 177 files, **2160 functions**)
gave **8 findings, 8 TP, 0 FP**. All 8 are «UB in the signature domain» (`LONG_MIN`/`INT_MIN`) — no
caller in the tree passes such values; they are NOT renamed into «bugs». The extended slice also
exposed and closed four more roots: `#501b` (unknown macro type), `#503` (`switch` not modelled),
`#504` (BV form ignored local types), plus the dedupe. Named boundary: precision 1.00 is measured on
**the slice**, not on the whole corpus — see T4.

EVERY finding is triaged line-by-line in the log. Three roots are NAMED (no fix applied yet):
A) a STRUCT FIELD is modelled as a constant (`s->flags`, `fe->mask`, `batch.status`) although it is
written above in the same function, by a CALLEE, or through a pointer -> UNSAT on REACHABLE
branches -> false DEAD BRANCH (3 of 5 FPs);
B) unsigned types in the BOUNDS detector (`size_t` treated as signed, short-circuit `op[0]=='('`
not taken as a non-empty guard) — 2 FPs;
C) the same finding printed twice (tigerbeetle).

NEXT: delta-minimise each root to <=15 lines, add a TWO-SIDED control in `xray-precision`
(FP -> 0 AND the TP stays found), then re-measure on the SAME three SHAs.

RE-MEASURE AFTER THE FIX (`#500`+`#501`), SAME three SHAs, SAME 25-file slice:
curl 0 · redis 7 -> **4** · tigerbeetle 2 -> **0**; **TP 4, FP 0 -> precision 1.00** (target met
on this slice). The four survivors are all «UB in the SIGNATURE domain» (no in-tree caller passes
`LONG_MIN`/`INT_MIN`/`oplen <= 0`), named as such — not upgraded to «bugs». One verdict was
REVISED explicitly in the log (`ACLSetUser`: `oplen` is a separate `ssize_t` argument, so
`op[0]=='('` does not prove `oplen >= 1`). No recall cost measured (SV-COMP TPR 1.00 / FPR 0.00
unchanged). Two-sided control added: `precision_clean/field_guard_write.c` (trap -> 0) and
`precision_dead_field/dead_after_kind.c` (real dead branch -> exactly 1).

EXTENDED SLICE (60 files per corpus), after `#501b`/`#502`/`#503`/`#504`: same SHAs, same
deterministic rule. curl/lib **0** findings (161 functions) · tigerbeetle/src **0** (315) ·
redis/src **8** findings on 1684 functions — and ALL EIGHT are «UB in the SIGNATURE domain»
(no in-tree caller passes such values). **Precision 8/8 = 1.00, FP = 0 over 2160 functions.**
The four new roots were closed the same way (minimisation + do/after): `#501b` unknown index type
(`GETHOSTNAME_TYPE_ARG2` → skip with a reason) · `#502` double counting (two different checks with
the same condition → one accusation; fixture `precision_dedupe`, 2 → 1) · `#503` `switch` is not
modelled, so `case`s were treated as straight-line code and a LIVE branch was declared dead
(fixture `precision_clean/switch_repeated_cond.c`, 1 → 0) · `#504` the BV form ignored LOCAL types,
so `long long value < 0` became `bvult value 0` (always false) → false DEAD BRANCH in redis/config.c
(fix: local types feed the BV signedness/width choice ONLY, never `path_conds` — otherwise a free
name makes SAT refuse and real findings are lost, measured on `num_enum_vals + 1`).
Recall cost measured after everything: SV-COMP TPR 1.00 / FPR 0.00, xray-overflow-check rc=0,
xray-precision rc=0 (traps 0/1/1, buggy 5/5, known_fp 0, external base 4).

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
4. **PUBLISHED** (no `gh` needed): `release.yml` runs on the `v*` tag on GitHub's servers, rebuilds
   the archive, runs `action-check REAL=1` and publishes 5 assets. Measured on `v2.8.2`:
   `kerna-dist-v2.8.2.tar.gz` 25 211 700 B, `sha256sum -c` → «ЦЕЛ», internal sums → «ЦЕЛ»,
   `./kerna --doctor` → OK, `./kerna --delta` on a divergent pair → `DIVERGED` with a counterexample
   (`#513` closed: `kernc` is now `-Dcpu=baseline`, so it no longer dies with SIGILL on a CPU
   without AVX-512). Release notes are no longer silently substituted: a missing
   `docs/RELEASE_NOTES_<tag>.md` makes the job fail (`#507`).
   **Open housekeeping:** the tag `v2.8.2` points at `6b13fa7a` while `HEAD` is `86fef8ee`
   (the 3 extra commits are gate/test only — `#514` — and do not enter the binary). T1 below.

## Tomorrow (local plan, 2026-11-08) — in this order

| # | Task | Done when (measurement) |
|:--|:--|:--|
| ~~**T1**~~ ✅ | Tag moved to the sealed commit (`d5262868`), `release.yml` republished; will be moved again after `#515` (the CLI message is inside `kernc`, so it must be in the archive too) | `git rev-parse 'v2.8.2^{commit}'` = `HEAD`; asset `sha256sum -c` «ЦЕЛ» |
| ~~**T2**~~ ✅ | QF_S: `#515` — the refusal now NAMES the rule. Boundary chosen deliberately: strings are NOT modelled, the boundary is written into `LIMITS` (§2) with the exact dump `((_ th-lemma seq) @x78 … false)` | `make proof-tamper` rc=0 (`ПРИНЯТО 0`), reason = `ДОВЕРЕННЫХ 1 | первое правило: th-lemma (структурно)`; LIMITS carries the dump |
| ~~**T3**~~ ✅ | `--live` in the appliance done as `#516`: the message now names what actually runs (Z3 layer only) and what is a named skip; plus `#517` (a missing/invalid path is a refusal, not «no divergence»). Written into `README-RUN.txt` + `LIMITS` §6 | packaged archive: real pair → `DIVERGED`; `/nope_base` → `rc=2` «путь НЕ СУЩЕСТВУЕТ»; file instead of dir → `rc=2`; `audit-delta --selftest` 12/12 |
| ~~**T4**~~ ⚠️ | P1 on the WHOLE corpus (942 files, 2942 functions) — DONE with the fixed analyzer. **40 findings, 6 proven FP → precision 0.85; the 0.90 threshold was NOT met on the full corpus.** Progress vs the first full run: curl 4→1, redis 43→36, tigerbeetle 9→3. Six roots closed (`#520`–`#525`), each with an 8–12 line repro and a two-sided control | numbers + per-line triage in `docs/evidence/blind_p1_2026-11-07.log`. Remaining FP named: redis `memtest.c` ×2 (BV path), redis `server.c` (interprocedural field mutation), tigerbeetle `marzullo.zig`/`replica.zig` (local rewritten inside a LOOP), one Python test file. That is task **T4b** |
| ~~**T5**~~ ✅ | `--delta` on a REAL PR: redis `0e618fa` «Fix NULL deref in `usUntilEarliestTimer`». Found and fixed `#518` (a truthful `[UNKNOWN]` was reported as a tool error) | both directions → `rc=0` and the line «НЕ РЕШЕНО (Belnap N) … это НЕ „поведение то же“»; boundary named: a NULL deref is outside `CRASH PATH` (division by zero), so the gate does not block — and does not pretend otherwise. Receipt in `docs/evidence/field_trials_v2.8.2.log` |
| **T6** | One FULL local `python3 tools/canfail.py` to completion (~2 h on this machine; today it was verified by CI) | `ИТОГ: … ВАКУМНЫХ 0 … ГРЯЗНЫХ 0` with the log committed |
| **T7** | The actual DoD: give the 27 MB archive to ONE external person with the receipt file | their numbers = ours, or the divergence is filed as a defect |

Rule for tomorrow: no new languages/theories and no «improvements» before T1–T2 are closed.

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
