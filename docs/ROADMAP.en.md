# KERN Roadmap — v2.5 status (English mirror)

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->441 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->470 · CHECK <!-- fact:check_targets -->163 · cases <!-- fact:canfail_cases -->195 · anchors <!-- fact:anchors -->155 · registry <!-- fact:registry_targets -->214 · META <!-- fact:meta_targets -->37 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

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

## What is left before the release

1. **Release v2.5.1** (owner-only): merge `v2.5-dev → main`, push, re-upload the asset +
   `SHA256SUMS`, run the online `make artifact-check`.
2. Sync README/landing hashes after the asset is uploaded (currently v2.4.0 on purpose,
   otherwise the links would 404).
3. Nothing else in code: canonical gate 40/40, full sweep 1345/1345, `canfail`
   195 non-vacuous / 0 vacuous, Lean 147 theorems / 0 sorry, QEMU 393/8/0.
