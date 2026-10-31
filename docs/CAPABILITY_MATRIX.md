# KERN capability matrix — one command, one physical oracle, one honest boundary

> **Facts (EN/RU, kept in sync by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->490 · CHECK <!-- fact:check_targets -->183 · cases <!-- fact:canfail_cases -->223 · anchors <!-- fact:anchors -->183 · registry <!-- fact:registry_targets -->239 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff · QEMU <!-- fact:cross_arch_passed -->443+<!-- fact:cross_arch_skipped -->8

**WHY THIS PAGE EXISTS.** Every capability below is listed with three things that
are **mandatory**: the **one command** that exercises it, the **external oracle**
that confirms the verdict, and the **honest boundary** — what the check does NOT
prove. A row without an external oracle would be *the model checked against the
model*, i.e. a vacuum, and is not listed as a capability here.

**WHAT COUNTS AS AN ORACLE.** Something our own code cannot forge: a live
compiler (`gcc`/`rustc`/`zig`), a live interpreter (`python3`, the real regex
engine), the operating system (real file system, real clock), or an official
ground-truth label (`:status`, `expected_verdict`). Statistical oracles are
marked as such and are never presented as proofs.

Numbers in the tables are **measurements with a date** (the run that produced
them), not permanent claims; the anchored numbers in the header are the ones kept
in sync automatically.

---

## A. Contracts and the SMT core

| # | Capability | One command | Oracle of reality | Status | What it does NOT prove |
|:--|:--|:--|:--|:--|:--|
| 1 | Python contracts (`requires`/`ensures`) | `python3 tools/kern_contracts.py <file.py>` | live `python3` (`[RUNTIME CONFIRMED]`) | verified | one function; calls outside the subset -> SKIP with a reason |
| 2 | C contracts + hardware `idiv` trap (`MIN/-1`, `-MIN`) | `make contracts` | `gcc -fsanitize=undefined` (SIGFPE/SIGABRT) | verified | pointers, structs, macros are outside the subset |
| 3 | Go / TypeScript polyglot (`int32`) | `make real-cases-check` | live toolchain for the language | verified | the `int32` subset only |
| 4 | Loops: 4 Floyd–Hoare obligations | `make loop-check` | a real loop run in Python | verified | one loop shape (`x += step`), constants |
| 5 | Overflow **inside subexpressions** (Path C) | `make xray-overflow-check` | compiler diagnostics + UBSan | verified | C-like languages |
| 6 | Explicit bit-vector mode | `@kern:bitvec32` + `make xray-overflow-check` | `gcc -Woverflow` | verified | only where BV mode is available (C-like) |
| 7 | Refactoring equivalence (`--diff-equiv`) | `make diff-equiv` | live run of BOTH versions | verified | Int theory: non-linear bodies are excluded **with the reason printed** |
| 8 | Path traversal `../`, NUL | `make oracle-string-check` | **real file system** (canary outside the root) | verified | a lexical KERNFS namespace check; host symlinks are out of scope |
| 9 | SQL / RLS tenant isolation | `make sql-policy-check` | real SQL engine semantics | verified | the predicate subset that is modelled |
| 10 | AMM fee / anti-arbitrage | `make arbitrage-check` | live integer arithmetic | verified | one fee formula class |
| 11 | **IEEE-754 NaN** | `tests/fixtures/ieee754_nan.smt2` | — | **PARTIAL, named** | it is an **Int + Bool model, NOT QF_FP**; real QF_FP measures **213 trusted steps**; a source-level `# @kern:float` does **not exist** |

---

## B. Model families: six physical oracles (plan step D)

Each of these families used to be checked **model against model**. Now each has an
external oracle, and the block "model families without oracles" is gone.

| # | Family | One command | Oracle of reality | Status | What it does NOT prove |
|:--|:--|:--|:--|:--|:--|
| 1 | DTMC / PCTL | `make oracle-dtmc-check` | Monte-Carlo: 10 000 walks, fixed seed | verified | one chain (3 states); the tolerance is statistical |
| 2 | ReDoS (catastrophic backtracking) | `make oracle-redos-check` | the **real** Python regex engine + a stopwatch | verified | 9 representative regexes; the parser subset is narrow -> SKIP, not "safe" |
| 3 | Abstract interpretation | `make oracle-absint-check` | a **real** loop run (values vs the predicted interval) | verified | linear loops of one shape; **soundness** is checked, not precision |
| 4 | CHC / Horn invariants | `make oracle-chc-check` | a **real** loop run (deterministic = the whole trajectory) | verified | one loop shape and 4 named properties; agreement is checked, not invariant quality |
| 5 | Paths (`strings path`) | `make oracle-string-check` | **real FS**: canary outside the root + a real `open()` | verified | a lexical namespace check; host symlinks are out of scope |
| 6 | **Non-interference (2-Safety)** | `make oracle-noninterference-check` | **real time**, min of N=1000, 4096-byte secret | **STATISTICAL oracle** | measures the gap between TWO implementations, not the absence of leaks in arbitrary code; **not a proof** |

Measured for #6 (2026-10-28): `CT_RATIO = 1.0003` (threshold < 3.0) versus
`EE_RATIO = 68.80` (threshold >= 10.0). The 4096-byte secret was chosen **by
measurement**: at 16 bytes the signal drowned in timer overhead (`EE_RATIO = 1.20`).
**Range across runs (re-measured 2026-10-28):** `CT_RATIO` 1.0003-1.0035, `EE_RATIO` 68.80-86.81.

---

## C. External datasets (world benchmarks, not our fixtures)

| # | Dataset | One command | Oracle of reality | Status | What it does NOT prove |
|:--|:--|:--|:--|:--|:--|
| 1 | **EvalPlus MBPP+** | `make mbpp-xray-check` | live `python3` (`ZeroDivisionError`) | 3 confirmed blind spots, 0 false | these are unhandled edge cases, **not exploitable vulnerabilities** |
| 2 | **SV-COMP** (4 categories) | `make svcomp-witness-check` | `gcc -Woverflow` + UBSan/ASan on UNMODIFIED tasks | 37 tasks, 11 witnesses confirmed, 0 false | SAFE is not proven here: only "no signal on 64 enumerated witnesses" |
| 3 | **SMT-LIB** (4 theories) | `make smtlib-proof-check` | Z3 + **our own** proof checker | 21/21 match, 3 official UNSAT at `trusted: 0` | timeouts are a resource limit, named separately |
| 4 | CWE twins | `make cwe-twins-check` | the compiler | J = 1.00, 27/27 | **our own paired fixtures, NOT the NIST SARD dataset** |
| 5 | **QuixBugs** | `make quixbugs-replay` | live differential replay | 40/40 DIVERGED, 0 false EQUIVALENT | formally (SMT) only 6/40 are solved |
| 6 | Code corpus, 4 languages | `make codecheck` | compiler + Python | `FP = 0`, `FN = 0` | hard gates hold **for this corpus**, not for arbitrary code |
| 7 | Our own tree | `--full-scan .` | live Python | 61 findings over 426 files (2026-10-27) | a **dated measurement**, not a gate |

---

## D. Container, sandbox, ABI

| # | Capability | One command | Oracle of reality | Status | What it does NOT prove |
|:--|:--|:--|:--|:--|:--|
| 1 | KIMG container (Merkle + BLAKE3) | `make storage-check` | real files, real hashes | verified | the format is read-only here; no signature inside the container |
| 2 | KIMG CLI (`fsck`/`inspect`/`diff`) | `make kimg-cli-check` | real `.kimg` files on disk | verified | three golden fixtures, not the whole format space |
| 3 | KERNFS (`no-mmap`) | `make storage-check` | real FS semantics | verified | symlinks do not exist in the format (named, not a gap) |
| 4 | KERN-X VM (shared fuel, quotas) | `make storage-check` | real bytecode runs | verified | a small opcode set |
| 5 | C-ABI | `make c-abi-test` / `make c-abi-threads` | a real C compiler, 8 threads | verified | `LP64` clarified; Windows is not supported |
| 6 | Determinism | `make determinism-check` | two live runs of the same input | verified | one input class |
| 7 | Cross-architecture | `make cross-arch` | **real QEMU** (ARM64 + PPC64 big-endian) | <!-- fact:cross_arch_passed -->443+<!-- fact:cross_arch_skipped -->8 | an emulated run, not real hardware |

---

## E. Defence against AI

| # | Capability | One command | Oracle of reality | Status | What it does NOT prove |
|:--|:--|:--|:--|:--|:--|
| 1 | Contract lock (specification tampering) | `make contracts-lock-check` | fingerprint comparison | verified | it protects the **declared** contracts; it does not prove they are true |
| 2 | Six AI traps | `make ai-traps-check` | an exact marker **and** an honest twin per trap | 6/6 caught, 6/6 twins proven | fixtures, not "any agent" |
| 3 | Anti-cheat (5 classes) | `make anti-cheat-check` | AST rules | verified | pattern classes, not intent |
| 4 | MCP injection / invisible Unicode / rug-pull | `make mcp-audit-check` | the tool schema itself | verified | schema-level, not the tool's implementation |

---

## F. Trust infrastructure

| # | Capability | One command | Oracle of reality | Status | What it does NOT prove |
|:--|:--|:--|:--|:--|:--|
| 1 | Native Zig frontend (`kernc verify-zig`) | `make native-zig-ast-check` | Z3 + our proof checker | verified | functions outside the subset are honestly not checked |
| 2 | Native theories on external files (`kernc theory`) | `make native-theories-file-check` | real values / real loop runs | verified | the listed theory forms only |
| 3 | Conformance exam (12 sections) | `make conformance-check` | the kernel's own oracle binary | 12/12, 95 checks | it checks the **kernel's** invariants |
| 4 | Proof checker vs forged proofs | `make proof-tamper` | 40 forged proofs | 40/40 rejected | the checker's rule set, not Z3 itself (Z3 is in the TCB) |
| 5 | EVM semantics | `make evm-proof-check` | SMT identities | verified | the **model** of EVM arithmetic, not a bytecode disassembler |
| 6 | Attestation | `make verify-attestation` | an **external** Ed25519 public key | verified | our own key, not a third-party builder (no SLSA L3) |
| 7 | Truth Gate on our own claims | `scan_to_kern.py .` + `kernc verify` | the kernel's own verdicts | 73 of 74 claims get `e=0` | prose is not a machine contract — that is the point |
| 8 | CLI names every implemented command | `make cli-help-parity-check` | a live run of `kernc --help` (stdout, rc=0) | verified | it checks the command LIST, not whether each option description is true |
| 9 | C-like `--xray` NAMES its skip reasons | `make xray-check` | printed reasons vs the counter (the sum must match) | 232/232 and 400/400 | it proves every skip is NAMED, not that the bucket is the right one |
| 10 | `[DEAD BRANCH]` respects the BRANCH scope | `make xray-check` | a real `cmark-gfm` file (4 false ones removed) + a genuinely dead twin | 4 -> 0 false, the true one still found | it says nothing about branches the parser cannot translate |

---

## What this page does NOT claim

- **No new CVEs.** Three real defects were found in *educational* repositories
  (`TheAlgorithms/C`, `TheAlgorithms/Rust`); no CVE was reported by KERN.
- **Not a scanner.** Measured: **0 of 715** functions in foreign repositories fall
  inside the analysable subset, so "run it on any repo" yields SKIPs, not findings.
- **Not everything is proven.** Rows marked `PARTIAL` / `STATISTICAL` say so in the
  Status column, and the boundary column says why.
- **One row is one concrete task**, not "the language is fully supported".

## Reproduce

```bash
make ci-fast                 # fast circuit
make showcase-live           # 7 rows (seconds)
make showcase-live-all       # ALL rows of THIS matrix, executed live: 32 rows, ~2 min
make showcase-live-full      # the 7 fast rows + the long corpora (minutes)
make conformance-check       # 12 sections
make oracle-noninterference-check   # the statistical oracle, honestly labelled
```

**Which mode covers what.** `showcase-live` shows 7 rows; `showcase-live-all`
executes **every row of this page** (measured 2026-10-28: **32 rows, 0 failures,
119 s total, slowest row 24.5 s**) and takes the verdict from live output, not
from this document. Two rows are deliberately NOT in that fast tier — the full
tree scan (~20 min) and cross-architecture (~5 min); `showcase-live-all-full`
runs them, and their commands are printed even when they are skipped, so nothing
is hidden. Each row states its **external oracle** and **what it does NOT prove**.

Inventory of corpora with N/M and oracles: `docs/CORPORA.md`.
Companion page with six modes in a row on one function: `docs/REAL_WORLD_CAPABILITIES.md`.
