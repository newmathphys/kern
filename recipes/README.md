# Production recipes: KERN inside a real service

> **Full-spectrum polygon (70 / 70):** [`docs/FULL_SPECTRUM_70.md`](../docs/FULL_SPECTRUM_70.md) · [RU](../docs/FULL_SPECTRUM_70.ru.md) — 7 blocks, every card confirmed by KERN *and* an independent oracle. The same corpus is the 34th CI stage: `make full-spectrum-check` (byte-exact showcase comparison, `--selftest`, canfail).

This directory is the practical half of the project: **how a team embeds KERN in one
line and which accident it prevents** — as opposed to `benchmarks/showcase_100/`, which
proves the engines on isolated tasks.

## Inventory of the CLI (what actually exists today)

`tools/kern_contracts.py` exposes **51 flags**. They are not all equal in maturity, and
this table says honestly what has been exercised and what has not:

| Engine | Flag | Shown in evidence? |
|:--|:--|:--|
| Contracts (`@kern:ensures`, 4 macros, tuples) | positionals, `--fn` | ✅ `SHOWCASE_100`, `GIANTS_AUDIT` |
| Refactor equivalence + alpha-norm + QF_NIA + implicit `None` | `--diff-equiv` | ✅ 60 real bugs on public corpora |
| Bounds / UB / C-like memory | `--xray`, `--xray-json` | ✅ `TIME_MACHINE`, cJSON, `MOUSE` |
| Test cheating (assert removal, `except: pass`) | `--anti-cheat` | ✅ `LIVE_LLM_TRIAL` (9/10) |
| MCP tool firewall | `--audit-mcp`, `--mcp-lock` | ✅ `SHOWCASE_100` (5 cards) |
| Belnap blind zone (N) | `--spec-gaps` | ⚠️ measured once: a tariff grid with ages 18..20 missing returns `SKIP — путь без return`, i.e. the hole is visible; **no recipe yet** |
| Belnap conflict (B) | contract mode, `JOIN_K` | ⚠️ only `JOIN_K(T,F)=B` in `SHOWCASE_100`; `MEET_K`, consensus, node degradation unused |
| State machines (multi-step races) | `--state-inv` | ❌ implemented, never demonstrated |
| Auto-repair (synthesis, no LLM) | `--heal` | ❌ implemented, never demonstrated |
| Concolic (paths a fuzzer misses) | `--concolic` | ❌ implemented, never demonstrated |
| UNSAT-core localisation | `kernc unsat-core <file.smt2>` (native `verifier/unsat_core.zig`) | ✅ `make unsat-core-check`: core `{a2 a3 a4}` with noise dropped, removing any element → SAT, line numbers printed; `--explain` is a passport, not a localizer (measured) |
| 2-Safety / tenant isolation | `--noninterference` | ✅ `SHOWCASE_100` (5 cards) |
| Reward for model training | `--rlvr-reward` | ❌ implemented, never demonstrated |
| Proof-carrying delivery | `.kimg`, `--trust-score`, Ed25519, `kernc.wasm` | ✅ `docs/playground/` |
| SQL / pricing rewrites | `--verify-sql`, `--verify-pricing` | ❌ never demonstrated |
| Loop invariants | `--loops`, `--infer-requires` | ❌ never demonstrated |

The honest summary: **the binary mode (PROVEN / COUNTEREXAMPLE) is what our public
evidence rests on; seven deep engines are implemented but unproven in public.**

## Planned set of stands (not built yet — this is a plan, not a claim)

| # | Stand | Engine it would prove |
|:--|:--|:--|
| 01 | Marketplace split (seller + fee + cashback + partial refund) | `conserves_sum`, `non_negative` |
| 02 | SaaS pricing ladder with seats and proration | `monotonic`, `idempotent` |
| 03 | Webhook idempotency (pending → paid → refunded → paid) | `--state-inv`, `idempotent` |
| 04 | Tick-size normalisation and store-share maths | anti-arbitrage law, `idempotent` |
| 05 | AI refactor in a PR gate | `--diff-equiv` |
| 06 | Anti-cheat shield for autonomous agents | `--anti-cheat` |
| 07 | MCP tool firewall | `--audit-mcp`, `--mcp-lock` |
| 08 | IAM / medical / banking access arbiter | full `B₄`: N, B, `JOIN_K`, `MEET_K` |
| 09 | Multi-tenant analytics isolation | `--noninterference` |
| 10 | Firmware packet parser (`uint8_t` TLV) | `--xray`, QF_BV |
| 11 | Auto-repair without an LLM | `--heal` / CEGIS |
| 12 | Crypto notary of a release | `.kimg`, Ed25519, `kernc.wasm` |

## Format of every recipe (when written)

1. **Situation** in three lines: what the business does.
2. **Buggy service code** that passes its own unit tests (the trap).
3. **One command** that exposes the hole, with a real counterexample.
4. **One-line fix** under a mathematical seal (`PROVEN`, `trusted: 0`).
5. **Copy-paste snippet** for `pre-commit` / `.github/workflows/kern.yml`.

## Status

No recipe directory is shipped yet: writing them without running each stand end-to-end
would produce exactly the kind of "green badge" this project spent its whole history
rejecting. The first one to build is **01 (marketplace split)** — its laws are already
proven in `GIANTS_AUDIT` and `SHOWCASE_100`, so the recipe only needs the service
wrapper, not new engine work.
