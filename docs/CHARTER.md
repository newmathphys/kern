# The KERN Charter

> A charter that cannot be checked is a wish. Every law below **names its checker**,
> and the checker is actually run: `make charter-check`.
> Meta-rule: a law written in this file but missing from the checker's table fails
> the gate — so no law can be added here as decoration.

Three classes, and the difference between them is stated, not hidden:

| Class | Meaning | Checker |
| --- | --- | --- |
| **I** | algebraic — provable | KERN itself (`charter/laws.py`, `@kern:` contracts) |
| **II** | process — checkable by running gates | the repository's own gates |
| **III** | policy — **not** machine-checkable | nothing; declared as policy |

## 1. Class I — algebraic laws

Each law is an `@kern:` contract in `charter/laws.py`, proven by the same engine
KERN uses on other people's code. The file is a **model** of `src/core/eq2.zig` and
`src/next/state_axes.zig`; the checker therefore also cross-checks the model against
the kernel's own oracle (`kern-conformance`): all 16 join pairs, all 4 conflations,
all 7 verdict mappings must agree. A model without that cross-check is just text.

| Law | Statement | Checker | Status |
| --- | --- | --- | --- |
| **L1** | `T ⊔ F = B` — a contradiction is not erased | `law_join_T_F` | **PROVEN** (`trusted: 0`, `holes: 0`) |
| **L2** | `⊔` is idempotent: `x ⊔ x = x` | `law_join_idempotent` | **PROVEN** |
| **L3** | conflation `~` is an involution: `~~a = a` | `law_conflate_involution` | **PROVEN** |
| **L4** | a tool failure never becomes `F` (`timeout`, `out_of_fuel`, `invalid_certificate`, `tool_error`) | `law_no_false_accusation` | **PROVEN** (`trusted: 0`, `holes: 0`) |
| **L5** | `B` is never produced by a verdict — only by a conflict of evidence | `law_verdict_never_b` | **PROVEN** (`trusted: 0`, `holes: 0`) |
| **L6** | `invalid_certificate` maps to `N`, never to `F` | `law_invalid_cert_is_unknown` | **PROVEN** |
| **L7** | `N` is the unit of `⊔`: `N ⊔ x = x` | `law_join_identity_N` | **PROVEN** |
| **L8** | machine-proven instance of L4: `timeout → N` | `law_timeout_is_unknown` | **PROVEN** |

Measured: **8 laws, 6 proven, 2 not covered by the proof checker, 0 violated,
0 vacuous, 0 false alarms.**

## 2. Class II — process laws

| Law | Statement | Checker |
| --- | --- | --- |
| **P1** | every CHECK target can fail (100 % non-vacuous coverage) | `tools/registry.py` |
| **P2** | no number without an anchor in public documents | `tools/check_metrics_consistency.py` |
| **P3** | the status snapshot is built from facts + registry + journal | `tools/gen_status.py --check` |
| **P4** | `llms.txt` is generated from `facts.json` | `tools/gen_llms_txt.py --check` |
| **P5** | EN/RU facts agree in every pair | `tools/docs_parity_check.py` |
| **P6** | every piece of evidence is tracked and carries no failure | `tools/evidence_gate.py` |

## 3. Why this section exists at all

L4 and L5 are stated **for all verdict codes**, and both are NOW machine-proven:
`trusted: 0`, `holes: 0`. This was not always so, and the history is kept
deliberately — it is the record of a boundary that was closed.

Until 2026-10-22 our proof checker REFUSED their derivations with
`premises_unbound` (recorded as defect **#303**): Z3 quoted our own premise with a
trivial connective inserted — `(and X true)` instead of `X` — and the premise
binding rule did not recognise it. The sound fix (folding trivial connectives,
`dropTriv`) made the charter **8/8 machine-proven**, and the list of
expected-uncovered laws is now empty.

The mechanism is kept, not deleted: if a law appears that Z3 proves while our
checker cannot re-derive it, `tools/charter_check.py` will NAME it instead of
quietly counting it as proven.

We could have deleted L4/L5 from the charter to make the table look green. We did
the opposite: they stayed in the table, marked as not-proven, until the checker
actually covered them. That is the failure mode this project exists to catch.

## 4. Class III — policy (not machine-checkable)

Stated as policy, **not** as verification. Nothing here is claimed to be checked:

| Policy | Statement | Machine check |
| --- | --- | --- |
| **Q1** | a published tag is never moved | none |
| **Q2** | secrets do not enter the repository | partial: `make secrets-check` |
| **Q3** | a second agent works read-only | none |
| **Q4** | a false accusation is worse than a miss | partial: `FP = 0` gates, `--xray` candidate labelling |

## 5. How to run it

```bash
make charter-check          # laws + model-vs-kernel cross-check + class II gates
make charter-selftest       # breaks a law and requires the charter to go red
```

`make charter-selftest` proves the charter is not decoration: it rewrites L1 in a
temporary copy so that `T ⊔ F = B` no longer holds, and requires KERN to report a
violation; it also replaces the model's `join` with XOR and requires the
kernel cross-check to notice.

## 6. Facts referenced by this document

<!-- fact:core_tests -->451 core tests · <!-- fact:next_tests -->53 next ·
<!-- fact:catalog -->480 catalog · <!-- fact:check_targets -->180 CHECK ·
<!-- fact:canfail_cases -->218 can-fail cases · <!-- fact:anchors -->179 anchors ·
<!-- fact:registry_targets -->234 targets · <!-- fact:meta_targets -->39 META ·
<!-- fact:lean_theorems -->147 Lean theorems ·
QuixBugs <!-- fact:quixbugs.smt -->6/40 formal SMT ·
<!-- fact:quixbugs.differential -->40/40 live differential.
