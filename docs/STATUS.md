# KERN — current status (generated)

> Built from `docs/facts.json`, `tools/registry.py` and the defect journal by
> `tools/gen_status.py`; gated by `make status-check`. Hand edits fail the gate.
> There is deliberately no "snapshot date" in the file — a stored date goes
> stale by itself. The date is the commit that last regenerated it:
> `git log -1 docs/STATUS.md`.

## Verification registry

| Class | Count | Meaning |
| --- | --- | --- |
| Targets, total | <!-- fact:registry_targets -->239 | every goal this repository claims to verify |
| CHECK | <!-- fact:check_targets -->183 | must be able to fail |
| MEASURE | 1 | cannot fail — therefore not a proof |
| BUILD | <!-- fact:build_targets -->11 | L0 only: it compiles |
| EXTERNAL | 3 | third-party / cross-architecture |
| META | <!-- fact:meta_targets -->41 | harness, generators, guards |

Can-fail cases: **<!-- fact:canfail_cases -->223**, of which
**183/183** CHECK targets have a non-vacuous "can fail" proof.

## Measured facts

| Fact | Value |
| --- | --- |
| Core Zig tests | <!-- fact:core_tests -->451 (443 passed + 8 skipped, 0 failed) |
| KERN-Next tests | <!-- fact:next_tests -->53 |
| Full test catalog | <!-- fact:catalog -->480 |
| Lean 4 | <!-- fact:lean_theorems -->147 theorems in 8 files, 0 sorry |
| Mutations killed | <!-- fact:mutation_sites -->1427 / 1427 across 21 files |
| Cross-architecture | <!-- fact:cross_arch_passed -->443 passed / <!-- fact:cross_arch_skipped -->8 skipped / 0 failed |
| QuixBugs | <!-- fact:quixbugs.smt -->6/40 formal SMT · <!-- fact:quixbugs.differential -->40/40 live differential (29 value + 10 crash + 1 hang) · <!-- fact:quixbugs.explored -->0 EXPLORED |
| Literal anchors | <!-- fact:anchors -->183 |
| Version | `v2.8.0` |

## Defect journal

Numbered entries: **325**.

| Explicit status | Count |
| --- | --- |
| Fixed | 193 |
| Fix submitted upstream (our patch in someone else's repo) | 1 |
| Real defect found by KERN in a third-party repo | 1 |
| Documented limitation (we live with it; it is not a defect) | 0 |
| Decision: considered and not adopted | 0 |
| Rows in the earlier journal format (category column, no status) | 130 |

**Open technical defects: 0**

> The journal spans two table generations: earlier rows carry a *category*
> (`gate`, `kernel`, ...) and no status at all, later rows carry an explicit
> status. Only explicit statuses are counted, and an entry counts as *open*
> only when its status **starts with** `ОТКРЫТ`. Earlier rows are never
> re-interpreted: assigning them a status would invent data.

Highest defect number in the journal: **<!-- fact:max_defect -->408**.
Every entry names its cause and its fix; entries are never deleted.

## External state

| Item | Where |
| --- | --- |
| Pull request `TheAlgorithms/C#1595` | <https://github.com/TheAlgorithms/C/pull/1595> |
| Pull request `TheAlgorithms/Rust#1075` | <https://github.com/TheAlgorithms/Rust/pull/1075> |
| Last observed review state of both | `docs/evidence/external/verification.log` |
| Release assets and signatures | <https://github.com/newmathphys/kern/releases> |

> Review state is not duplicated here: it changes without the tree changing,
> so it lives in the evidence log above, dated at the moment it was observed.

## Where to read more

- **What it is and why**: `README.md`
- **What it can do, with live output**: `docs/ALL_CAPABILITIES_LIVE_GUIDE.md`
- **Honest boundaries** (what it does *not* do): `README.md`, section "Honest status"
- **Defect journal**: `docs/CAPABILITY_STATUS.md`
- **Evidence, verbatim runs**: `docs/evidence/`
- **Roadmap and open work**: `docs/PLAN_v2.6.4.md`, `docs/ROADMAP.md`
