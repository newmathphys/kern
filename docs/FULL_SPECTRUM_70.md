# Full Spectrum 70 — window 1: blocks 01-07 (70 of 70 confirmed)

Every mechanism below had been shown on a single example each; here each one is
run over a corpus of business cards. Every card is checked **twice**: the KERN
verdict (native Zig / symbolic) and an **independent oracle** that is not a copy
of the engine's tables (bit-pair semantics for B4, CPython execution for code).

**Law of integrity:** `confirmed == total`. If a single card is not confirmed, the
runner exits with `rc=1` and writes no showcase at all.

Corpora: `01_belnap_b4.json`, `02_auto_heal_cegis.json`, `03_unsat_explain.json`, `04_state_machines.json`, `05_concolic_branches.json`, `06_kimg_ed25519.json`, `07_rlvr_reward.json`.

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
| 21 | 03 | `unsat_fee_corridor` | Fees/fintech | impossible fee corridor min_fee > max_fee with two innocent clauses | `--verify-doc`: core of 3 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 22 | 03 | `unsat_vip_discounts` | Marketplace | mutually exclusive VIP discounts: floor 30% and cap 10% | `--verify-doc`: core of 2 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 23 | 03 | `unsat_dead_sla` | SLA/support | dead SLA: 4 hours against a 6-hour review and sla >= review | `--verify-doc`: core of 3 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 24 | 03 | `unsat_aml_vip` | Compliance | AML withdrawal cap 5000 against VIP minimum 10000 | `--verify-doc`: core of 3 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 25 | 03 | `unsat_warehouse_temp` | Warehouse | impossible temperature tolerance: no warmer than -5 and no colder than 4 | `--verify-doc`: core of 2 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 26 | 03 | `unsat_cpu_quota` | Orchestrator | CPU quota collision: quota 2 with a pool of 8 and quota >= pool | `--verify-doc`: core of 3 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 27 | 03 | `unsat_delivery_window` | Logistics | impossible delivery window: start by 9, finish from 18, start >= finish | `--verify-doc`: core of 3 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 28 | 03 | `unsat_tax_deduction` | Taxes | deduction deadlock: deduction by 100, required from 500, deduction >= required | `--verify-doc`: core of 3 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 29 | 03 | `unsat_quorum` | Quorum | impossible quorum: at most 5 of at least 9 members, quorum >= members | `--verify-doc`: core of 3 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 30 | 03 | `unsat_age_seniority` | HR/eligibility | age floor vs seniority: age by 25 with seniority from 10 and age >= seniority + 18 | `--verify-doc`: core of 3 clause(s) localized | UNSAT set · every core element necessary · noise innocent · revived model eval OK | OK |
| 31 | 04 | `inv_double_refund` | Escrow | double refund for the same order | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 32 concrete violation(s) found · 375 safe sequences, 0 violation(s) | OK |
| 32 | 04 | `inv_ship_after_cancel` | Goods receipt/warehouse | shipment after cancellation and from an empty warehouse | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 8 concrete violation(s) found · 30 safe sequences, 0 violation(s) | OK |
| 33 | 04 | `inv_wallet_double_debit` | Wallet | two consecutive debits drive the balance negative | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 44 concrete violation(s) found · 192 safe sequences, 0 violation(s) | OK |
| 34 | 04 | `inv_coupon_reactivation` | Marketplace | re-activating a single-use coupon | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 16 concrete violation(s) found · 16 safe sequences, 0 violation(s) | OK |
| 35 | 04 | `inv_frozen_withdrawal` | Compliance | withdrawal from a frozen account | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 10 concrete violation(s) found · 60 safe sequences, 0 violation(s) | OK |
| 36 | 04 | `inv_credit_limit` | Credit | a series of microloans exceeds the credit limit | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 17 concrete violation(s) found · 243 safe sequences, 0 violation(s) | OK |
| 37 | 04 | `inv_subscription_bypass` | Subscriptions | expired -> active without payment | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 26 concrete violation(s) found · 81 safe sequences, 0 violation(s) | OK |
| 38 | 04 | `inv_double_release` | Resources/mutex | double release of a resource | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 23 concrete violation(s) found · 81 safe sequences, 0 violation(s) | OK |
| 39 | 04 | `inv_double_vote` | Quorum | one participant votes twice | [FAIL] naive + [PASS] guarded, 0 UNKNOWN | 16 concrete violation(s) found · 16 safe sequences, 0 violation(s) | OK |
| 40 | 04 | `inv_escrow_reference` | Escrow | reference guarded automaton: PROVEN + guard removal breaks the proof | [PASS] reference, 0 UNKNOWN + [FAIL] after guard removal | 57 violation(s) on the unguarded twin · 204 safe sequences, 0 violation(s) | OK |
| 41 | 05 | `concolic_antifraud_ladder` | Anti-fraud | stepped scoring: magic amount 1337 at score > 87 | `--concolic`: 9 run(s), 6/6 branches, dead 0, unexplored 0 | AST-instrumented: 6 branch(es), 2/2 target(s) hit by real witness vectors, 8 vector(s) | OK |
| 42 | 05 | `concolic_promo_threshold` | Promo codes | exact basket threshold: exactly 1000 gives 15%, otherwise item-count tier | `--concolic`: 10 run(s), 6/6 branches, dead 0, unexplored 0 | AST-instrumented: 6 branch(es), 2/2 target(s) hit by real witness vectors, 8 vector(s) | OK |
| 43 | 05 | `concolic_customs_cascade` | Customs | duty cascade: zones 3 and 2 open only above 10000 | `--concolic`: 13 run(s), 8/8 branches, dead 0, unexplored 0 | AST-instrumented: 8 branch(es), 2/2 target(s) hit by real witness vectors, 9 vector(s) | OK |
| 44 | 05 | `concolic_pressure_valve` | Industry | emergency valve: narrow pressure window and extreme temperatures -20 / 40 | `--concolic`: 10 run(s), 6/6 branches, dead 0, unexplored 0 | AST-instrumented: 6 branch(es), 2/2 target(s) hit by real witness vectors, 6 vector(s) | OK |
| 45 | 05 | `concolic_shard_router` | Sharding | shard router with special key 7 -> tenant 42 | `--concolic`: 9 run(s), 6/6 branches, dead 0, unexplored 0 | AST-instrumented: 6 branch(es), 2/2 target(s) hit by real witness vectors, 6 vector(s) | OK |
| 46 | 05 | `concolic_underwriting_4levels` | Underwriting | credit underwriting: four nested levels score/income/debt/age | `--concolic`: 15 run(s), 8/8 branches, dead 0, unexplored 0 | AST-instrumented: 8 branch(es), 2/2 target(s) hit by real witness vectors, 16 vector(s) | OK |
| 47 | 05 | `concolic_roaming_zones` | Billing | roaming by zone: zone 2 splits at 60 minutes | `--concolic`: 10 run(s), 6/6 branches, dead 0, unexplored 0 | AST-instrumented: 6 branch(es), 2/2 target(s) hit by real witness vectors, 6 vector(s) | OK |
| 48 | 05 | `concolic_iceberg_order` | Exchange | Iceberg order validator: price > 0, quantity from 1000, visible part by 10 | `--concolic`: 10 run(s), 6/6 branches, dead 0, unexplored 0 | AST-instrumented: 6 branch(es), 2/2 target(s) hit by real witness vectors, 12 vector(s) | OK |
| 49 | 05 | `concolic_sla_anomaly` | Monitoring | SLA anomaly detector: latency > 500 and errors > 10, else rare threshold 50 | `--concolic`: 9 run(s), 6/6 branches, dead 0, unexplored 0 | AST-instrumented: 6 branch(es), 2/2 target(s) hit by real witness vectors, 6 vector(s) | OK |
| 50 | 05 | `concolic_deductible_steps` | Insurance | multi-step deductible: large claim from 100000 and history 0 / < 3 | `--concolic`: 13 run(s), 8/8 branches, dead 0, unexplored 0 | AST-instrumented: 8 branch(es), 2/2 target(s) hit by real witness vectors, 9 vector(s) | OK |
| 51 | 06 | `kimg_pristine_integrity` | Delivery/integrity | reference image: header and Merkle root agree, objects intact | `pristine`: rc=0, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 52 | 06 | `kimg_payload_bitflip` | Attack/bit-rot | one payload bit flipped: KERN names the exact tampered object | `payload_flip`: rc=2, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 53 | 06 | `kimg_magic_corrupt` | Attack/format | corrupted KIMG magic -> image does not parse | `magic_corrupt`: rc=2, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 54 | 06 | `kimg_version_corrupt` | Attack/version | major version swapped without re-signing -> UnsupportedVersion | `version_corrupt`: rc=2, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 55 | 06 | `kimg_hdrsize_corrupt` | Attack/header | header_size modified (128 -> 64) -> BadHeaderSize | `hdrsize_corrupt`: rc=2, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 56 | 06 | `kimg_truncated` | Network/truncation | image tail truncated: table/payload bounds violated | `truncated`: rc=2, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 57 | 06 | `kimg_empty` | Attack/empty buffer | empty file instead of an image -> size refusal | `empty`: rc=2, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 58 | 06 | `kimg_foreign_key` | Key rotation | signed with OUR key: OpenSSL validates it, KERN rejects it (trust root is the owner) | `foreign_key`: rc=0, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 59 | 06 | `kimg_signature_bitflip` | Attack/signature | one byte flipped inside the 64-byte Ed25519 signature -> signature invalid, binding intact | `sig_flip`: rc=0, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 60 | 06 | `kimg_stale_owner_cert` | Compliance/stale artifact | a genuine owner certificate for ANOTHER image: signature valid, binding MISMATCH | `stale_binding`: rc=0, markers matched | own header/table parse + BLAKE3 per object + Ed25519 via OpenSSL | OK |
| 61 | 07 | `rlvr_div0_vs_linear` | Fintech formula | division by zero in a generated formula vs a proven linear one | rewards div0=-1.0, linear=1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 62 | 07 | `rlvr_offbyone_vs_precise` | SLA clamp | off-by-one at the x=0 boundary vs an exact clamp | rewards offbyone=-1.0, precise=1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 63 | 07 | `rlvr_weak_spec_reward` | Reward relativity | a weak contract rewards a constant, a strong one punishes the same constant | rewards constant_weak=1.0, constant_strong=-1.0, linear_good=1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 64 | 07 | `rlvr_partial_guard_vs_full` | Balance/guard | partial guard (large amounts only) vs a full clamp | rewards partial=-1.0, full=1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 65 | 07 | `rlvr_syntax_broken_vs_valid` | Parsing | syntactically broken LLM answer vs a valid one: no reward for the broken one | rewards broken=None, valid=1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 66 | 07 | `rlvr_upper_bound` | Cap/overflow | going past the upper bound 1000 vs clamping at it | rewards unbounded=-1.0, clamped=1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 67 | 07 | `rlvr_fee_leaky_vs_closed` | Fees | leaky computation (amount-1 at 0) vs sign-closed | rewards leaky=-1.0, closed=1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 68 | 07 | `rlvr_requires_removed` | Precondition removal | dropping requires on the same body collapses the reward (+1.0 -> -1.0) | rewards with_requires=1.0, without_requires=-1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 69 | 07 | `rlvr_rank_three` | Ranking | three candidates on one task: proven > violated > cheat | rewards proven=1.0, violated=-1.0, cheat=-2.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |
| 70 | 07 | `rlvr_reference_vs_sign_mutation` | Sign mutation | reference result > 0 vs mutation (x-1) under the same spec | rewards reference=1.0, mutated=-1.0 | independent exec: witness violates ensures · proven holds on domain · monotone | OK |

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

## What block 03 proves (contradictory specs, `--verify-doc`)

Each card is a clause document whose conjunction is **unsatisfiable**. KERN prints
`[FAIL] CONFLICT B(1,1)` and `[CONFLICT B(1,1)] Minimal conflicting clauses: [...]`
and exits with `rc=1`. The core is obtained by greedy deletion, so it is
**irreducible, not necessarily minimum-cardinality** — that is stated, not hidden.

The oracle recomputes the mathematics from scratch (its own Python→z3 translator,
not `expr_smt`): the full set is UNSAT, removing **any** core element makes it SAT,
removing any **noise** clause leaves it UNSAT, and the model of the relaxed
specification is physically evaluated against every remaining predicate (`eval`),
so the revived specification has a real witness vector.

`--explain` is exercised as a **secondary, passport-only** surface: its printed
cyclomatic complexity, SMT branch count and division-crash lines must equal an
independent AST recount. It does **not** localize conflicts (measured).

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

## What block 05 proves (concolic branch coverage, `--concolic`)

Narrow nested branches (`x == magic`, four-level ladders, anti-fraud rules) are
synthesised concretely: KERN prints `[CONCOLIC] <fn>: concrete runs N, branches
covered c/t (dead 0, unexplored 0)`. Measured boundary: **the engine does not print
the input vectors**, only the summary counts.

The oracle therefore does the physical work itself: it instruments the card's AST
with its own markers, executes the real function over the declared finite domain,
collects the `(line, taken)` set and a witness vector for every target line, and
requires `covered == 2 × |if|`, `dead == 0`, `unexplored == 0`. A needle property is
enforced: the trivial all-zero input must **not** already pass every target.

## What block 06 proves (.kimg integrity and Ed25519 attestation)

`kernc check-integrity` gives `rc=0` on an intact image and `rc=2` on damage,
naming the exact failure: `BadMagic`, `UnsupportedVersion`, `BadHeaderSize`,
`ОБЪЕКТ <i> ПОВРЕЖДЁН ... PayloadTampered`, `Образ слишком мал`.
`kernc attest sign` signs with ANY 32-byte seed, while `attest verify` checks the
**owner key baked into the binary** — and always exits with `rc=0`: the verdict is
textual (`подпись=НЕВЕРНА|ok`, `привязка=ok|НЕ СОВПАЛА`). That gap is measured and
named, not papered over.

The oracle parses the 128-byte header and the 96-byte object table itself,
recomputes **BLAKE3 of every object**, verifies the certificate signature with
**OpenSSL Ed25519** under both our key and the owner key, and compares
`SHA-256(image)` with the certificate's `contract_digest` (binding). A foreign key
card shows the strong case: the signature IS valid under our key (OpenSSL says so)
and invalid under the owner key — so KERN enforces the right trust root instead of
rejecting everything.

## What block 07 proves (verifiable RLVR reward)

`--rlvr-reward` prints an exact scalar: `+1.0` verified (`trusted: 0 | holes: 0`),
`-1.0` refuted (with a counterexample), `-2.0` reward hacking (`sys.exit` inside a
function), `0.0` abstain (no annotations, or a body outside the closed fragment —
measured: `x * 2` and `part * 100 // total` abstain, `x + x` proves). A
syntactically broken answer is a fatal `SyntaxError` with **no reward at all**
(fail-closed).

The oracle re-reads `requires`/`ensures` itself, executes every candidate in real
Python, and proves the reward is deserved: the counterexample violates the
postcondition at an input that satisfies the precondition; the proven candidate
keeps it across the whole declared domain; the cheat really contains `sys.exit`;
the broken file really does not parse. Monotonicity and determinism are checked.

## Honest boundaries

- `kernc belnap` is a **pure lattice calculator** over four values. Certainty and
  conflict predicates are **not** exposed as separate operations: no such native
  predicate exists in `Bit`/`Eq2` today, so the CLI does not invent one; `--bits`
  gives `pos`/`neg`, and a caller can derive "definite" or "conflict" from them.
- The `--verify-doc` core is irreducible (removing any element revives the spec),
  but it is not guaranteed to be minimum-cardinality.
- `--explain` is a function passport, not a conflict localizer; it is verified as
  such and no more.
- `--concolic` prints only counts (no vectors) and is capped at 64 concrete runs
  per function, with `assign`/`if`/`return` and linear conditions only.
- `attest verify` always exits `0`; its verdict is textual only, so the gate
  matches markers instead of rc (rc is not a signal here).
- `--rlvr-reward` returns `+1.0` only for proofs inside the linear fragment;
  `//` and variable-by-variable `*` abstain (`0.0`) instead of pretending.
- A weak contract really does reward a constant (`return 0` with `result == 0`
  earns `+1.0`): the reward is spec-relative, and the card says so.
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

TOTAL: cards 70 | confirmed by KERN **and** the physical oracle 70 | rc=0
