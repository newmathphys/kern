# Full Spectrum 70 — window 1: blocks 02 and 04 (20 of 20 confirmed)

Two KERN modes that had been shown on a single example each are now run over a
corpus of business cards. Every card is checked **twice**: the KERN verdict
(symbolic) and an **independent physical oracle** (CPython really executes the code).

**Law of integrity:** `confirmed == total`. If a single card is not confirmed, the
runner exits with `rc=1` and writes no showcase at all.

Corpora: `02_auto_heal_cegis.json`, `04_state_machines.json`.

## Cards

| # | block | card | sphere | business subject | KERN | physical oracle | status |
|---|-------|------|--------|------------------|------|-----------------|--------|
| 1 | 02 | `heal_conversion_zero` | Logistics | fulfilment ratio with zero attempts | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 2 | 02 | `heal_avg_check_empty` | Fintech | average ticket for an empty basket | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 3 | 02 | `heal_delivery_share_zero` | Delivery | free-delivery share with zero orders (expression divisor) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 4 | 02 | `heal_quota_floor_zero` | SaaS quotas | whole quota units per seat with zero seats (//) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 5 | 02 | `heal_sla_window_zero` | Payments/SLA | minutes inside the escalation window with a zero window (%) | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 6 | 02 | `heal_discount_rate_zero` | Marketplace | discount rate when the coupon fully covers the subtotal | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 7 | 02 | `heal_tax_rate_zero` | Taxes | effective tax rate at zero turnover | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 8 | 02 | `heal_fill_rate_zero` | Warehouse/buffer | fill rate of a zero-capacity buffer | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 9 | 02 | `heal_burn_rate_zero` | Crypto treasury | burn rate at zero profit | T (1,0), 1 crash-paths before → 0 after | python3 rc 1 → 0 · 1 guard(s) · normal inputs exact | OK |
| 10 | 02 | `heal_multi_site_metrics` | Analytics/BI | two division sites in one return (counter and bonuses) | T (1,0), 2 crash-paths before → 0 after | python3 rc 1 → 0 · 2 guard(s) · normal inputs exact | OK |
| 11 | 04 | `inv_double_refund` | Escrow | double refund for the same order | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 32 concrete violation(s) found · 375 safe sequences, 0 violation(s) | OK |
| 12 | 04 | `inv_ship_after_cancel` | Goods receipt/warehouse | shipment after cancellation and from an empty warehouse | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 8 concrete violation(s) found · 30 safe sequences, 0 violation(s) | OK |
| 13 | 04 | `inv_wallet_double_debit` | Wallet | two consecutive debits drive the balance negative | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 44 concrete violation(s) found · 192 safe sequences, 0 violation(s) | OK |
| 14 | 04 | `inv_coupon_reactivation` | Marketplace | re-activating a single-use coupon | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 16 concrete violation(s) found · 16 safe sequences, 0 violation(s) | OK |
| 15 | 04 | `inv_frozen_withdrawal` | Compliance | withdrawal from a frozen account | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 10 concrete violation(s) found · 60 safe sequences, 0 violation(s) | OK |
| 16 | 04 | `inv_credit_limit` | Credit | a series of microloans exceeds the credit limit | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 17 concrete violation(s) found · 243 safe sequences, 0 violation(s) | OK |
| 17 | 04 | `inv_subscription_bypass` | Subscriptions | expired -> active without payment | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 26 concrete violation(s) found · 81 safe sequences, 0 violation(s) | OK |
| 18 | 04 | `inv_double_release` | Resources/mutex | double release of a resource | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 23 concrete violation(s) found · 81 safe sequences, 0 violation(s) | OK |
| 19 | 04 | `inv_double_vote` | Quorum | one participant votes twice | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 16 concrete violation(s) found · 16 safe sequences, 0 violation(s) | OK |
| 20 | 04 | `inv_escrow_reference` | Escrow | reference guarded automaton: PROVEN + guard removal breaks the proof | [PASS] reference, 0 UNKNOWN + [FAIL] after guard removal | 57 violation(s) on the unguarded twin · 204 safe sequences, 0 violation(s) | OK |

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

TOTAL: cards 20 | confirmed by KERN **and** the physical oracle 20 | rc=0
