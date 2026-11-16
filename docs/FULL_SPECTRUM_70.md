# Full Spectrum 70 — window 1: blocks 01, 02 and 04 (30 of 30 confirmed)

Every mechanism below had been shown on a single example each; here each one is
run over a corpus of business cards. Every card is checked **twice**: the KERN
verdict (native Zig / symbolic) and an **independent oracle** that is not a copy
of the engine's tables (bit-pair semantics for B4, CPython execution for code).

**Law of integrity:** `confirmed == total`. If a single card is not confirmed, the
runner exits with `rc=1` and writes no showcase at all.

Corpora: `01_belnap_b4.json`, `02_auto_heal_cegis.json`, `04_state_machines.json`.

## Cards

| # | block | card | sphere | business subject | KERN | physical oracle | status |
|---|-------|------|--------|------------------|------|-----------------|--------|
| 1 | 01 | `belnap_spec_gap_unknown` | Specifications | a forgotten tariff range yields N, not “proven” (linked with --spec-gaps) | 3 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 3 cell(s) · spec-gap markers: 1 | OK |
| 2 | 01 | `belnap_conflict_sensors` | Microservices/sensors | two sources disagree: join_k(T,F)=B, and a new T vote does not overwrite it | 3 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 3 cell(s) | OK |
| 3 | 01 | `belnap_consensus_meet` | Source consensus | shared knowledge only: meet_k(T,F)=N, meet_k(T,T)=T, meet_k(B,T)=T | 3 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 3 cell(s) | OK |
| 4 | 01 | `belnap_fail_closed_and` | Fail-safe shutdown | fail closed: and_t(F,N)=F, the ban does not wait for a dead service | 3 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 3 cell(s) | OK |
| 5 | 01 | `belnap_authority_or` | Access rights | explicit authority beats ignorance: or_t(T,N)=T, or_t(T,F)=T, or_t(B,T)=T | 3 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 3 cell(s) | OK |
| 6 | 01 | `belnap_not_unknown` | Honest ignorance | no answer does not become True: not(N)=N (unlike `not None` in Python) | 3 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 3 cell(s) | OK |
| 7 | 01 | `belnap_not_conflict` | Paraconsistency | negation does not dissolve conflict: not(B)=B (no ex falso quodlibet) | 3 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 3 cell(s) | OK |
| 8 | 01 | `belnap_acl_cascade` | ACL/escalation | Allow and Deny at once: join_k(T,F)=B, and and_t(B,T)=B — escalate, not silent allow | 3 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 3 cell(s) | OK |
| 9 | 01 | `belnap_arbitration_all16` | Three-agent arbitration | full 68-cell cascade: 4 operations x 16 pairs + not on 4 values | 68 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 68 cell(s) | OK |
| 10 | 01 | `belnap_gdpr_vs_tax` | GDPR compliance | “delete personal data” (T) vs tax retention (F): join_k=B, meet_k(B,N)=N -> manual verdict | 2 native cell(s) via kernc belnap (Zig core) | bit-pair oracle agrees on 2 cell(s) | OK |
| 11 | 02 | `heal_conversion_zero` | Logistics | fulfilment ratio with zero attempts | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 12 | 02 | `heal_avg_check_empty` | Fintech | average ticket for an empty basket | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 13 | 02 | `heal_delivery_share_zero` | Delivery | free-delivery share with zero orders (expression divisor) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 14 | 02 | `heal_quota_floor_zero` | SaaS quotas | whole quota units per seat with zero seats (//) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 15 | 02 | `heal_sla_window_zero` | Payments/SLA | minutes inside the escalation window with a zero window (%) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 16 | 02 | `heal_discount_rate_zero` | Marketplace | discount rate when the coupon fully covers the subtotal | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 17 | 02 | `heal_tax_rate_zero` | Taxes | effective tax rate at zero turnover | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 18 | 02 | `heal_fill_rate_zero` | Warehouse/buffer | fill rate of a zero-capacity buffer | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 19 | 02 | `heal_burn_rate_zero` | Crypto treasury | burn rate at zero profit | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 20 | 02 | `heal_multi_site_metrics` | Analytics/BI | two division sites in one return (counter and bonuses) | T (1,0), 2 crash-paths before → 0 after | python3 rc 1 → 0 · 2 guard(s) · normal inputs exact | OK |
| 21 | 04 | `inv_double_refund` | Escrow | double refund for the same order | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 32 concrete violation(s) found · 375 safe sequences, 0 violation(s) | OK |
| 22 | 04 | `inv_ship_after_cancel` | Goods receipt/warehouse | shipment after cancellation and from an empty warehouse | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 8 concrete violation(s) found · 30 safe sequences, 0 violation(s) | OK |
| 23 | 04 | `inv_wallet_double_debit` | Wallet | two consecutive debits drive the balance negative | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 44 concrete violation(s) found · 192 safe sequences, 0 violation(s) | OK |
| 24 | 04 | `inv_coupon_reactivation` | Marketplace | re-activating a single-use coupon | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 16 concrete violation(s) found · 16 safe sequences, 0 violation(s) | OK |
| 25 | 04 | `inv_frozen_withdrawal` | Compliance | withdrawal from a frozen account | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 10 concrete violation(s) found · 60 safe sequences, 0 violation(s) | OK |
| 26 | 04 | `inv_credit_limit` | Credit | a series of microloans exceeds the credit limit | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 17 concrete violation(s) found · 243 safe sequences, 0 violation(s) | OK |
| 27 | 04 | `inv_subscription_bypass` | Subscriptions | expired -> active without payment | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 26 concrete violation(s) found · 81 safe sequences, 0 violation(s) | OK |
| 28 | 04 | `inv_double_release` | Resources/mutex | double release of a resource | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 23 concrete violation(s) found · 81 safe sequences, 0 violation(s) | OK |
| 29 | 04 | `inv_double_vote` | Quorum | one participant votes twice | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 16 concrete violation(s) found · 16 safe sequences, 0 violation(s) | OK |
| 30 | 04 | `inv_escrow_reference` | Escrow | reference guarded automaton: PROVEN + guard removal breaks the proof | [PASS] reference, 0 UNKNOWN + [FAIL] after guard removal | 57 violation(s) on the unguarded twin · 204 safe sequences, 0 violation(s) | OK |

## What block 01 proves (native B4, `kernc belnap`)

`kernc belnap <op> <a> [b]` prints the result of a **native** function of the Zig
core (`src/core/eq2.zig`: `joinK`, `meetK`, `andT`, `orT`, `notB`). There is no
truth table in the wrapper: the CLI layer only maps an operation name to a call,
so "CLI drifted from the engine" is impossible by construction. `--bits` prints
`<symbol> <code> <pos> <neg>` with `code = pos | (neg << 1)`.

The oracle does **not** copy those tables: it recomputes B4 from evidence pairs
`(pos, neg) in {0,1}^2` — `N=(0,0)`, `T=(1,0)`, `F=(0,1)`, `B=(1,1)` — combining
knowledge component-wise (`join_k` = OR/OR, `meet_k` = AND/AND) and truth
monotonically (`and_t` = AND/OR, `or_t` = OR/AND), with `not = (neg, pos)`.
Every cell of every row is compared, including the full 68-row `--table` cascade.

## What block 02 proves (auto-repair without an LLM, `--heal`)

Each card walks the **whole arc**, not a recipe print:

1. BEFORE: the file really crashes in `python3` (`ZeroDivisionError`) and
   `--xray` reports the crash path;
2. REPAIR: `kern_contracts.py --heal` synthesises guards by itself, inserts them
   into the source and prints `T (1,0)` with `после патча: 0`;
3. AFTER: the healed file runs in `python3` without a crash, `--xray` reports zero
   crash paths, the contract re-check says `нарушено 0 / НЕ РЕШЕНО 0`, and **normal
   inputs still return the mathematically correct value** (the guard did not turn
   the function into a constant zero).

The backup `<file>.bak` is checked to hold the original, unpatched source.

## What block 04 proves (state machines over time, `--state-inv`)

Each card is a multi-step business automaton where every single method looks
harmless, but a **chain of transitions** breaks the state invariant:

1. KERN reports `[FAIL] <naive>: STATE INVARIANT VIOLATED` together with a concrete
   counterexample, and `[PASS] <guarded>: PROVEN` for the protected transition; no
   `[UNKNOWN]` is accepted as a proof;
2. the physical oracle replays real call sequences on a real object, counts the
   concrete violations it observes, and exhaustively checks that the guarded
   transition never violates the invariant on the grid of sequences.

Card 10 adds a **mutation check**: drop the guards of the reference escrow and the
KERN proof collapses to `[FAIL]`, while the physical oracle shows the balance going
negative. A proof that survives removing the guard would be worthless.

## Honest boundaries

- `kernc belnap` is a **pure lattice calculator** over four values. Certainty and
  conflict predicates are **not** exposed as separate operations: no such native
  predicate exists in `Bit`/`Eq2` today, so the CLI does not invent one; `--bits`
  gives `pos`/`neg`, and a caller can derive "definite" or "conflict" from them.
- `--heal` synthesises guards **only for division by zero** (`/`, `//`, `%`) —
  exactly what `_crash_sites` searches for. It does **not** repair list index
  out-of-range or a shifted threshold guard, so no such card is claimed here.
- `--state-inv` proves the annotated invariant on **every return path** of the
  annotated function; it is not a whole-program object invariant.
- Cards are **data** (`benchmarks/full_spectrum/*.json`). Code is materialised into
  a temporary directory, so no annotated `.py` file enters the repository tree and
  `docs/contracts.lock.json` keeps sealing exactly its own specification files

## Reproduce

```bash
.venv/bin/python tools/run_full_spectrum.py
```

Requires an interpreter with `z3` (the stock `.venv/bin/python`). Without `z3` the
runner exits with `rc=2` and an explicit message instead of a green tick.

TOTAL: cards 30 | confirmed by KERN **and** the physical oracle 30 | rc=0
