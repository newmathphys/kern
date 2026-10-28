# KERN CORPORA: inventory of real tasks, oracles and boundaries

> **Facts (EN/RU, synced by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->480 · CHECK <!-- fact:check_targets -->174 · cases <!-- fact:canfail_cases -->212 · anchors <!-- fact:anchors -->173 · registry <!-- fact:registry_targets -->227 · META <!-- fact:meta_targets -->39 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff · QEMU <!-- fact:cross_arch_passed -->441+<!-- fact:cross_arch_skipped -->8

**WHY THIS FILE.** "Dozens of examples per capability" is not a promise: they are
**already in the repository**. This file says WHAT exists, HOW MANY tasks, **WHAT
confirms** the verdict and **WHAT it does not prove**. All three columns are
mandatory: a row without an oracle does not enter tables 1-2.

**ORACLE RULE.** An oracle is an **external** arbiter that cannot be faked by our
own code: a real compiler (`gcc`/`rustc`/`zig`), a real interpreter (`python3`),
or an official ground truth (`:status`, `expected_verdict`).
**A model checked against a model is a vacuum**, so such rows are moved to
section 4 with an explicit label.

---

## 1. Available OFFLINE right now (oracle: a real compiler/interpreter)

| Corpus | Tasks | What it checks | Oracle | Command |
|:--|--:|:--|:--|:--|
| **evalplus MBPP+** | **378** (264 `pass/pass`, **43 `pass/fail`**, 70 `fail/fail`) | `--xray` finds crashes in solutions that passed **BOTH MBPP AND the 80x MBPP+** | **live Python** (`ZeroDivisionError`) | `make mbpp-xray-check` |
| **SV-COMP** (cache) | **37** `.c` in 4 categories | UNSAFE witness validation + SAFE | **`gcc -Woverflow`** and **`-fsanitize=undefined,address`** | `make svcomp-witness-check` |
| **SMT-LIB** (cache) | **23** `.smt2` in 4 theories | proof-checking official UNSAT proofs | **Z3 + our own proof checker** (`trusted: 0 \| holes: 0`) | `make smtlib-proof-check` |
| `audits/cwe_twins` | **8** `.c` | `bad`/`good` pairs over 9 CWE classes | **compiler** | `make cwe-twins-check` |
| `audits/smt2` | **28** | QF_LIA/QF_BV core fixtures | **Z3** | `make audits` |
| `audits/codecheck` | **33** (4 languages: Python/Zig/C/Rust) | `TP/TN/FP/FN/UNKNOWN` matrix, hard gate **`FP = 0`** | **compiler + Python** | `make codecheck` |
| `tests/fixtures` | **25** | contracts, `.kimg` fixtures, theories, Zig frontend | mixed | `make test` |
| `examples/` | **53** | demos of every mode (heal, hypotheses, guardrail, noninterference, polyglot, EVM) | mixed | `make demo-all` |
| **our own tree** | **426** files / **1558** functions | self-application of `--xray` | **live Python** | `--full-scan .` |

---

## 2. Requires NETWORK (external repositories; the clone cache is empty now)

Measured earlier, but **reproduction requires cloning** - hence a separate table
rather than "available now".

| Corpus | Tasks (measured) | What it gives | Oracle |
|:--|--:|:--|:--|
| `TheAlgorithms/C` `math/` | **66** functions (26 checked under the old filter) | contracts on real C | `gcc` |
| `TheAlgorithms/Python` `maths/` | **470** functions | contracts on real Python | live Python |
| `TheAlgorithms/Rust` | **423** files | `u64`/`i32` overflow | `rustc` |
| **NIST Juliet SARD** `CWE190/s01` | **51** `.c` | `bad`/`good` pairs from NIST | compiler |
| **QuixBugs** | **40** tasks | real algorithmic bugs | live replay |
| **CyberSecEval** (Meta) | **1916** (8 languages) | CWE labels + `line_number` (ground truth of the faulty line) | - (measurement cut short, #381) |

**Three live contributions to external repositories** (real findings, not fixtures):
`TheAlgorithms/C#1595` (`catalan.c`, SIGFPE at `n=0`) ·
`TheAlgorithms/C#1596` (`lcm.c`, `50000*50000` -> `-35899`) ·
`TheAlgorithms/Rust#1075` (`binom(0,2)` - `u64` panic).

---

## 3. What these corpora do NOT prove

| Claim that must NOT be made | Why |
|:--|:--|
| "KERN finds all bugs in a repository" | measured: **0 of 715** functions in foreign repositories fall into the subset |
| "CVEs were found" | `catalan`/`lcm`/`binom` are **educational** repositories; not a single new CVE |
| "An MBPP+ blind spot is a vulnerability" | it is an **unhandled edge case** in AI-generated code, not an exploitable vulnerability |
| "40/40 QuixBugs is a formal proof" | it is **live differential replay**; formally (SMT) only **6 of 40** |
| "A SAFE task is proven" | SV-COMP checks **the absence of a signal on the enumerated witnesses**, not unreachability |

---

## 4. Model-only families: the oracle is still internal (boundary stated)

Six families are checked **against a model**, not against reality. Publishing their
examples as "proof" is **not allowed** until a physical oracle exists (plan step D);
until then they carry this label.

| Family | Oracle status |
|:--|:--|
| `chc` (loop invariants) | needs a **concrete loop run** checking the invariant at every iteration |
| `dtmc` (probabilities) | needs **Monte-Carlo** against the analytic `P` |
| `redos` | needs a **stopwatch** on a pathological string |
| `absint` | needs **interval vs concrete values** comparison |
| `string` (QF_S) | needs a **real attempt to open a file** outside the root |
| `noninterference` | will remain a **noisy statistical** oracle - and will be labelled so |

---

## 5. Reproduction

```bash
# offline part (section 1) - no network
make mbpp-xray-check svcomp-witness-check smtlib-proof-check cwe-twins-check codecheck

# external corpora (section 2) - clone first
git clone --depth 1 https://github.com/TheAlgorithms/C ~/.cache/kern/repos/C
git clone --depth 1 https://github.com/TheAlgorithms/Python ~/.cache/kern/repos/Python
```
