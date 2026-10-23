# KERN: a cybernetic loop with machine evidence

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->436 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->465 · CHECK <!-- fact:check_targets -->156 · cases <!-- fact:canfail_cases -->178 · anchors <!-- fact:anchors -->139 · registry <!-- fact:registry_targets -->202 · META <!-- fact:meta_targets -->32 · Lean <!-- fact:lean_theorems -->143 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

> This document describes **only what exists in the code**. Every claim comes with a
> file you can open and a number you can re-check with a command. No invented
> technologies — and that is deliberate.

## 1. The problem: code that is "green" but wrong

The modern development loop optimises **exit code 0**, not truth. A language model that
needs to "pass the test" can:

* override `__eq__` so comparison always returns `True`;
* call `sys.exit(0)` inside the function under test;
* replace the test with `unittest.mock` in a production module;
* hard-code the answer for one specific input.

This is not hypothetical: the repository **detects** these cases and **covers them with
counter-checks** — `tools/kern_contracts.py` (`--anti-cheat`), `make anti-cheat-check`.
We caught exactly the same class of bug in **our own** checks: nine gates turned out to be
vacuous (defects #130, #131, #132, #142, #147, #148, #151 and others) — green while the
logic was broken. Conclusion: you can trust only what has been **independently re-checked**.

## 2. The reflex arc: from "acceptor of the result" to a machine verdict

P. K. Anokhin described a functional system in which an action is compared with the
**acceptor of the result of the action** — a pre-formed image of the required outcome;
a mismatch triggers correction.

In KERN this loop is deterministic, not probabilistic:

| Link of the arc | What is in the code |
|:--|:--|
| **Acceptor** (what must hold) | contract `@kern:requires` / `@kern:ensures` |
| **Action** (what was done) | the function body translated to SMT-LIB2 |
| **Comparison** | Z3: `requires ∧ ¬ensures` → SAT/UNSAT |
| **Independent check** | `src/verifier/proof_check.zig` — our own proof checker (`trusted: 0`) |
| **Mismatch** | Z3 counterexample (minimal, `10→5→2→1→0`) |
| **Correction** | `--heal`: synthesize a guard → insert → **re-check** → `T (1,0)` |

The key difference from "LLM-as-a-judge": the verdict is produced by a **solver plus a
separate proof checker**, not by a model. A model may only propose a formula; KERN cannot
accept it on faith (§4).

## 3. V. M. Glushkov: automating proof as an engineering discipline

The idea of OGAS was to make computation **governed and verifiable** rather than trusted.
KERN implements a small version: every verdict carries evidence that can be re-checked
without trusting whoever produced it:

* `trusted: 0 | holes: 0` — no step in the proof was taken on faith
  (`src/verifier/proof_check.zig`);
* **40 adversarial forgeries** of a real 51-step proof are rejected (`make proof-tamper`);
* an **evolutionary fuzzer** corrupts proofs and verifies that no corrupted individual is
  accepted (`make evo-fuzz-check`) — it is exactly what found defect #155;
* **400** core tests, **122** CHECK targets each proven able to fail.

## 4. Belnap B₄: honest handling of contradiction

Two-valued logic is forced to "choose": either accept the doubtful or reject the true.
The Belnap lattice B₄ distinguishes four states: `N (0,0)` — no evidence, `T (1,0)` —
confirmed, `F (0,1)` — refuted, `B (1,1)` — **contradiction**.

In code (`src/next/truth.zig`):

* `JOIN_K(T, F) = B` — contradiction is **preserved**, not silenced;
* `JOIN_K(B, T) = B` — absorption: new confirmations do not "overwrite" the conflict
  (covered by `test-next`);
* allowance `e = 1` **only** for `T` (`allowance`); `B` and `N` close the gate;
* **Evidence Decay**: a changed file resets `p` (`T → N`);
* **Scoped Epoch Retraction**: fixed code plus a new `T` proof opens a new epoch, while
  the old `F` remains in the immutable audit log (`resolveAcrossEpochs` + Lean 4 theorems).

This is why a matrix audit of third-party repositories yields a table of zeros: without a
contract there is no acceptor, and a "contradiction" without evidence is `N`, not `B`.

## 5. Bret Victor and explorable explanations

Understanding comes from **being able to turn the knobs**. That is why KERN has:

* `--html` — a self-contained "Explorable Proof Canvas": input sliders, branch
  re-computation, the B₄ square, a function passport (0 external CDNs);
* `docs/kernc.wasm` — the **real core** (85 KB, 5 exports) right in the browser, no
  server: `JOIN_K`, Hamming check, Fourier–Motzkin and `verifyProof`.

## 6. Sovereignty and reproducibility

Ken Thompson's "Reflections on Trusting Trust" showed that you can trust only what you can
rebuild and verify. KERN's practice:

* a static 6 MB binary `kernc` (musl), sha256 in `SHA256SUMS`;
* a SLSA attestation **signed with Ed25519** (`kern.intoto.sig`, verified by
  `tools/slsa_provenance.py --check`);
* **1376 mutants: 1376/1376 killed (100.0 %)** over all 21 files with no sampling;
  the canonical gate (40 sites) yields the same verdicts;
* release reproducibility: `make artifact-check` compares README, the local build and the
  uploaded asset.

## 7. What is **not** here — and why

* **no probabilistic risk scoring**: admitting `N` by a "degree of trust" is forbidden —
  it would destroy the meaning of the gate (`fail-closed`);
* **no promises about "quantum verification"**: a classical AST has no quantum state;
  everything claimed is measured by commands;
* **no "checks any code"**: the extractor works on a subset and **must** print its
  coverage (`checked N / M`), and outside the subset — `SKIP` with a reason.

---

### How to verify this document

```bash
make proof-tamper        # 40/40 forgeries rejected
make evo-fuzz-check      # 0 crashes, 0 false accepts
make audits              # real functions from Zig/TigerBeetle/Ghostty/musl
./formal/check.sh        # Lean 4: 0 errors, 0 sorry
python3 tools/registry.py    # CHECK targets and their coverage
```
