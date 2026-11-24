# KERN Roadmap — v2.5 status (English mirror)

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->460 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->502 · CHECK <!-- fact:check_targets -->221 · cases <!-- fact:canfail_cases -->268 · anchors <!-- fact:anchors -->226 · registry <!-- fact:registry_targets -->302 · META <!-- fact:meta_targets -->58 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

> This is a **condensed English mirror** of [`ROADMAP.md`](ROADMAP.md) (which stays the
> full, detailed document in Russian). It records the final state, not plans.

## Status: all 8 echelons / 40 items closed

| Echelon | Items | Status |
|:--|:--|:--|
| 1 — Core (builtin_lia, verifyModel, #123, let-bomb, shrinking, Hamming, prlimit) | 1–8 | ✅ |
| 2 — `.kimg` / `kernx` (Proof-Carrying, Evidence Decay, Merkle chain, Bit-Rot) | 9–12 | ✅ |
| 3 — Autopilot (`--xray`, `--gen-tests`, `--infer-requires`, `[SUGGESTED FIX]`, `--simplify`, `--explain`, `--pr-summary`) | 13–19 | ✅ |
| 4 — Mathematics (loops, bounds, IEEE-754, QF_S, state invariants) | 20–24 | ✅ |
| 5 — Mass adoption (7 languages, presets, arbitrage, double-spend, FFI, SQL/RLS, pricing) | 25–31 | ✅ |
| 6 — AI shield (anti-cheat, MCP audit, 2-safety, Belnap swarm) | 32–35 | ✅ |
| 7 — Paradigms (FinOps firewall, RAG conflicts, RLVR, bug hunter) | 36–39 | ✅ |
| 8 — Packaging (WASM, `--html`, `grep`, MCP-8, fuzz corpus, `install.sh`) | 40 | ✅ |

## Closed debts (measured)

| Debt | Result |
|:--|:--|
| `--concolic` | 9 concrete runs, **6/6 branches**, dead 0; `canfail` 1/0 |
| Translation validation | `-O2` asm (`mov/sar/andn`) ↔ spec: **PROVEN, trusted: 0**; corrupted → REFUTED |
| Evolutionary fuzzer | 100 individuals, **0 crashes, 0 false accepts**; it found **#155** |
| `--full-file` | 16 modules at **100 %**; plus the whole population (below) |
| `opt-diff` cache | **90 000 ms → 47 ms** (×1900) |
| `--heal` | `.bak` + `tmp → fsync → re-check → replace` |
| **Full population mutation sweep** | **1345 / 1345 = 100.0 %**, 0 survivors, 23 min |

## Defects found while closing these debts

| # | Essence |
|:--|:--|
| **#155** | unresolved `@xN` in `verifyThLemmaArith` → `.structural_only` → a forged proof was **accepted**. Now `.bad` |
| **#156** | SIGTERM/SIGINT did not roll back canfail/mutator patches → a diversion could stay in the tree |
| **#157** | `write_atomic` lost the file mode: after a rollback 29 scripts lost `+x` (`100755 → 100644`) |

## 11. Bug-hunt trunks (state as of 2026-11-24)

These are not echelons 1–8: there the tool proved ITSELF. Here it works on foreign code, and the
only currency is a merged patch. Totals: **23 public reports, 0 false**, 1 PR merged (`zed`,
~60k ★), 3 in review, 2 closed by their authors as intended behaviour.

| Trunk (`tools/api_hunt.py` + `tools/law_hunter.py`) | What it looks for | Live result |
|:--|:--|:--|
| `eq-hash` | numeric `Eq`, bitwise `Hash` (`-0.0 == 0.0`, different hashes) | `zed` (merged), `surrealdb`, `databend`, `bevy`, `kiss3d` |
| `eq-ord` | `derive(Ord)` over rational fields → lexicographic order | `scheme.rs`, `Woxi`, `abacus`, `gluesql` |
| `lru-effects` | side effect inside a memoised function (clock under `@cache`) | `dagster` |
| `z3-alloc` | heap-size overflow: `malloc(w * h * … )` in 32-bit `int` | `iio` → PR #24 |

**The freshness filter is `pushed_at >= "2025-06-01"`**, never repository age. Age cut mature
libraries: a live project older than two years is exactly the one that gets patches.
`has_issues == False` is **not** a reason to skip either: private Security Advisories work with the
Issues tab switched off. The `z3-alloc` trunk carries **21** calibrations (the last one: the witness
is built from genuinely tainted factors, a local `channels = 1` no longer yields a silent
`65536 × 65536`, and the assumption is printed inside the witness).

**The intentionality gate comes BEFORE a report is sent.** The last two large reports were closed
not because the measurement was wrong but because the author considered the behaviour intended
(`typst` — "intentional, not planned"; `gleam` — "does not demonstrate any problem"). Three checks
before sending: (1) is there a test pinning the current behaviour; (2) is there an explanatory
comment above the disputed code; (3) does `CONTRIBUTING`/`docs` say `intentional`/`by design`. For C
parsers the equivalent is `if (w > MAX_DIM)` in the caller or an explicit format limit (16-bit
header). On any "yes" the report changes shape: not "a bug", but "here is a divergence — is it
intended?".

**Status of `iio`.** PR [#24](https://github.com/mnhrdt/iio/pull/24) is open and waiting for the
author; do not nudge for a week. The `imscript` patch (line offsets +48) stays local and is **not**
opened until the first one is answered — two PRs into two of his repositories in one day reads as
pressure.

## What is left before the release


1. **Release v2.5.1** (owner-only): merge `v2.5-dev → main`, push, re-upload the asset +
   `SHA256SUMS`, run the online `make artifact-check`.
2. Sync README/landing hashes after the asset is uploaded (currently v2.4.0 on purpose,
   otherwise the links would 404).
3. Nothing else in code: canonical gate 40/40, full sweep 1345/1345, `canfail`
   268 non-vacuous / 0 vacuous, Lean 147 theorems / 0 sorry, QEMU 393/8/0.
