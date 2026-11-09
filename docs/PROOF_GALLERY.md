# The Proof Gallery — all eight capabilities, one command each, one receipt each

KERN is not «a linter». It has eight independent muscles, and each of them is proved by an
**external oracle**, not by our own word: a live compiler, a real test runner, an offline binary, a
browser engine. Two rules for this page:

1. **Every row names the command you can run yourself** — no marketing table.
2. **Every row names its honest boundary** — what the proof does NOT show.

Run everything at once: `make showcase-live-all` → **33 rows, 0 failures** on this commit.

| № | Capability | The one command | The external oracle | The receipt |
|:--|:--|:--|:--|:--|
| **1** | **X-ray of someone else's code, no annotations** (`--xray`) | `make xray-precision` · `python3 tools/kern_contracts.py --xray DIR` | the code itself: every accusation carries a solver counterexample, triaged line-by-line | [`evidence/blind_p1_2026-11-07.log`](evidence/blind_p1_2026-11-07.log) |
| **2** | **Behavioural PR delta** (`--delta` = `--xray` + `--diff-equiv`) | `./kerna --delta BASE HEAD` · `make audit-delta-selftest` | a live call of both revisions on concrete arguments | [`evidence/field_trials_v2.8.2.log`](evidence/field_trials_v2.8.2.log) (`#508`) |
| **3** | **Mutants that survive `pytest`** | `make pytest-blind-check` | `pytest` says GREEN, then each mutant is killed with a counterexample | [`evidence/`](evidence/) + `tools/pytest_blind_check.py` |
| **4** | **L5 duel: an AI agent tries to cheat** | `make l5-duel-check` | 31 pairs: cheating patched source vs honest one (`setattr(__eq__)`, `pytest.skip`, `except: pass`, contract-lock forgery, U+200B in MCP) | [`evidence/`](evidence/) + `tools/l5_duel_check.py` |
| **5** | **Formal contracts** `QF_LIA` / `QF_BV` / `QF_AX` (McCarthy arrays) | `make audits` | Z3 + the proof checker; `trusted: 0` is required next to `PROVEN` | [`../audits/EVIDENCE.md`](../audits/EVIDENCE.md) |
| **6** | **Translator soundness** vs live toolchains | `make translator-diff-check` | real `gcc`, `rustc`, `node`, `python3` on 137 expressions + 12 traps (`#349`) | [`evidence/`](evidence/) |
| **7** | **Epistemic memory, Belnap B₄** (`kernx`) | `make kernx-polygon5-check` | two oracles disagree: `pytest` says T (`rc=0`), KERN says F (`rc=1`) → state `conflicted` | [`evidence/`](evidence/) + `agent_packet.json` |
| **8** | **Sovereign artifact without a solver** (`.kimg`) + **WASM in a browser** | `make pcc-offline-check` · `make wasm-check` | `kernc check-proof` under `PATH=""` (no Z3, no Python) + `docs/kernc.wasm` in `node` | [`evidence/`](evidence/) |

## Machine-readable index of every receipt

All claims below are indexed in `docs/capabilities_receipts.json`: for each claim it names the command, the receipt file and the markers that MUST be inside it. `make receipts-check` verifies that every file exists, is not empty, contains its markers and no forbidden one; a claim whose receipt is missing turns the gate red (proven by the `receipts-blind` case).

## The blind exam behind row 1 (the number this project is judged by)

Whole corpora, pinned SHAs, **no file cap**, zero edits to the analyzer before the run:

| corpus | SHA | files | functions checked | findings | false | precision |
|:--|:--|--:|--:|--:|--:|--:|
| `curl/lib` | `155f6f76` | 377 | 430 | 1 | 0 | 1.00 |
| `redis/src` | `5b69ba2c` | 227 | 1454 | 33 | 0 | 1.00 |
| `tigerbeetle/src` | `68958eb7` | 338 | 120 | 1 | 0 | 1.00 |
| **total** | | **942** | **2004** | **35** | **0** | **1.00** |

Every finding is triaged per line in the receipt; the remaining ones are UB **in the signature domain**
(`LONG_MIN`, `INT_MIN`, `remain_pos + 10`) — stated as such, never renamed into «bugs».

**Honest boundary of the same table:** the *cap* is on the slice, not on the corpus — 2 004 of 10 345
functions were analyzable; the rest were skipped with a NAMED reason (loops, struct fields mutated by
calls, unknown macro types). `skipped` grows as precision grows — that is the trade this project makes
on purpose: a silent accusation is worse than a named skip.

## Industrial code where KERN made **no** accusations (0 false alarms)

| corpus | SHA | files | threats found |
|:--|:--|--:|--:|
| `DeepGEMM` (CUDA/C++20) | `5081f851` | 144 | **0** |
| `FlashMLA` (CUDA) | `395cb3af` | 133 | **0** |
| `DeepEP-Ascend` (CUDA/NPU) | `4dfccac4` | 80 | **0** |
| `cmark-gfm` (`known_fp = 0`) | `27d942c8` | — | **0** |
| `actions/toolkit` | cached clone | — | **0** |

145 `[SMELL]` notes and 464 `[BOUNDS?]`/`[BOUNDS UNKNOWN]` notes were produced alongside — those are
**not** accusations; they are named uncertainties (Belnap N), and they are counted separately.

## Real defects, with patches

Six of them, each with a minimal reproduction and either an upstream link or a ready patch:
[`REAL_BUGS_FOUND.md`](REAL_BUGS_FOUND.md) (the TigerBeetle ordering defect, two `TheAlgorithms/C`
PRs, a `TheAlgorithms/Rust` PR, three EvalPlus MBPP+ blind spots, redis UB paths).
