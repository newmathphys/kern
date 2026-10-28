# CWE coverage — paired CWE-twins benchmark (our own fixtures)

Status: **measured** by `make cwe-twins-check`. Every number below is produced by
that command; none of them is typed by hand.

## What is measured, and how

> 🔴 **PROVENANCE OF THE FIXTURES — READ THIS FIRST.** The twins are **OUR OWN
> synthetic pairs** in [`audits/cwe_twins/`](../audits/cwe_twins/), modelling nine
> MITRE CWE classes. The **official NIST SARD files** (`CWE190_*_bad.c` /
> `_good.c` with their own annotation) were **not downloaded** and **do not
> participate** in the run. The gate was therefore renamed
> `cwe-juliet-check` → **`cwe-twins-check`**: the old name could be read as "we
> ran Juliet", which would overstate the claim. The metric **formulas** below
> (Youden index, SV-COMP score) are the official ones — but they are computed
> over **our nine pairs**, not over SARD.

The NIST SARD **Juliet Test Suite** checks a tool with **twin pairs**: `bad` is
vulnerable code, `good` is *the same code with the correct defensive guard*. A
tool must catch `bad` **and not accuse `good`**. A lone `bad` sample proves only
sensitivity; the pair proves accuracy.

KERN's twins live in [`audits/cwe_twins/`](../audits/cwe_twins/) and are driven
through KERN's **own engines** — no mocks, no hand-written verdicts:

| CWE | Class | Engine | `bad` must show | `good` must show |
|:--|:--|:--|:--|:--|
| **CWE-190** | Integer Overflow | `kern_contracts.py` | `[FAIL]` (counterexample) | `[PASS] ДОКАЗАНО` |
| **CWE-191** | Integer Underflow | `kern_contracts.py` | `[FAIL]` | `[PASS] ДОКАЗАНО` |
| **CWE-369** | Divide By Zero | `kern_contracts.py` | `[FAIL]` | `[PASS] ДОКАЗАНО` |
| **CWE-682** | Hardware `idiv` trap (`INT_MIN / -1`, `INT_MIN % -1`) | `kern_contracts.py` | `[FAIL]` | `[PASS] ДОКАЗАНО` |
| **CWE-680** | Integer Overflow to Buffer Size | `kern_contracts.py` | `[FAIL]` | `[PASS] ДОКАЗАНО` |
| **CWE-125/193** | Out-of-Bounds / Off-by-One | `--xray` | `[BOUNDS PATH]` | no finding |
| **CWE-22** | Path Traversal | `kernc prove` (QF_S) | `НЕ доказано` | `ДОКАЗАНО` |
| **CWE-89/285** | SQL / RLS tenant bypass | `--verify-sql` | `[FAIL] <fn>:` | `[PASS] <fn>:` |
| **CWE-208** | Timing side-channel on a secret | `--noninterference` | `[FAIL] <fn>:` | `[PASS] <fn>:` |

## The two world metrics

| Metric | Formula | Required | Measured |
|:--|:--|:--|:--|
| **Juden Index** (NIST SARD) | `J = TPR − FPR` | `1.00` | **1.00** (`1.000 − 0.000`) |
| Confusion matrix | — | `TP 9/9 · TN 9/9 · FP 0 · FN 0` | **9/9 · 9/9 · 0 · 0** |
| **SV-COMP score** | `+1` per caught `bad`, `+2` per proven `good`, `−16` per FP, `−32` per FN | `27 / 27`, penalty `0` | **27 / 27**, penalty **0** |

> The SV-COMP penalties are what make the benchmark honest: accusing a
> **guarded** `good` twin costs 16 points, and missing a real `bad` costs 32.
> A tool that shouts at everything scores far below zero — measured on the
> self-test: one false accusation drops the score from 27 to 9.

## What this gate does NOT claim

- It is **not** the full NIST Juliet Suite (thousands of cases). It is **nine**
  MITRE CWE classes, one `bad`/`good` pair each, on KERN's own engines. The
  "9/9" figures apply to these nine classes and do **not** transfer to all of SARD.
- **CWE-680 and CWE-190 share one type-range obligation**; the context (the result
  feeds an allocation size) is what separates them — exactly as NIST SARD
  separates them. The overlap is named here, not hidden.
- The gate does **not** judge the *quality* of a guard, only that the engine
  proved it. A weak-but-provable guard passes.
- `«ВНЕ ПОДМНОЖЕСТВА»` and `«НЕ РЕШЕНО»` are **not** accepted as proof for a
  `good` twin: they count as a failure, because "we could not decide" is not
  "the code is safe".

## Registry facts this page is consistent with

<!-- fact:core_tests -->451 core tests · <!-- fact:next_tests -->53 next tests ·
<!-- fact:catalog -->480 catalog · <!-- fact:check_targets -->180 CHECK ·
<!-- fact:canfail_cases -->218 can-fail cases · <!-- fact:anchors -->179 anchors ·
<!-- fact:registry_targets -->236 registry targets ·
<!-- fact:meta_targets -->41 meta · <!-- fact:lean_theorems -->147 Lean theorems ·
QuixBugs: <!-- fact:quixbugs.smt -->6 SMT-provable ·
<!-- fact:quixbugs.differential -->40 differential pairs.

## Reproduce

```bash
make cwe-twins-check          # self-test (4 branches) + the real run
python3 tools/cwe_twins_check.py --selftest
```
