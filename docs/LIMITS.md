# KERN'S LIMITS — WHAT IT DOES **NOT** PROVE

This document exists because honesty sells better than marketing: every verifier has limits,
and the only difference is whether they are NAMED or hidden. Below are ALL measured limits,
with numbers and a way to reproduce each one.

## 1. `PROVEN` ≠ «the proof was checked»

The word `PROVEN` in `audits/EVIDENCE.md` is the **solver's** verdict. The proof checker
verifies the derivation SEPARATELY, so every `PROVEN` row must carry the trusted-step count
(defect `#474`):

| Marker | Meaning |
|:--|:--|
| `trusted 0` | solver and checker agree — the proof is checked |
| `[PROOF PARTIAL] trusted N` | HONEST LIMIT: N steps rely on solver axioms |
| `trusted ?` | the checker reported no counter (`ДОКАЗАНО (допущено)` — a weaker claim) |

**Measured over the corpus (after `#479`/`#481`):** 44 formulas → **11** `trusted 0`, **10**
`PARTIAL`, **23** without a counter; of the 19 `PROVEN` rows — 7 `trusted 0`, 7 `PARTIAL`, 5
without a counter. `trusted 0` is emitted ONLY for an accepted proof (`rc == 0`); otherwise the
row is marked `⚠ чекер ОТВЕРГ вывод` (`#481`). For `QF_BV` partiality is essential: the derivation relies on bit-blaster
axioms `k!` — a free unprovable constant — so a strict offline check without a solver is
**impossible**. MEASURED on `hex_index_deepjit_hex_hi`: `ДОВЕРЕННЫХ 15`.

**Proof depth (measured):** for a 32-bit alignment bit-blast Z3 proof has **depth 14 113**
(1.29 MB). The parser limit is target-split: **16 384** native (2 271 of headroom) and
**4 096** on wasm — a browser stack is tiny (`#479`). Beyond the limit the report honestly says
«proof DEEPER than the parser limit» instead of crashing.

**Why BV is still not proof-carrying (numbers, `#480`):** with the limit lifted the same file
parses into **21 758 steps**, of which **19 865 are trusted** (`def-axiom`, the `k!` axioms), and
«premises» are **794** against 3 contract assertions — because in a bit-blast the `asserted`
steps are BIT-BLAST CLAUSES, not premises. CLOSED BY MEASUREMENT (`#480`): the `?x` abbreviations
in the proof are bit-level `mkbv` terms over hundreds of `k!` (`?x17516 = (mkbv k!960 k!970 …)`),
so matching 794 clauses to 3 assertions is conceptually impossible. Two fixes (an abbreviation
lookup for atoms and a pre-pass collecting the map) left it at `1/794` and were REVERTED.
Conclusion: BV does not become certifiable without a DRAT/LFSC-emitting solver (cvc5 / Bitwuzla).

**Consequence for «proof-carrying artifacts»:** they are proof-carrying for LIA and Boolean
invariants; for BV they are `PARTIAL` with a named count. The way forward is a solver with
complete DRAT/LFSC certificates (cvc5 / Bitwuzla), not Z3 axioms.

## 2. Floating-point arithmetic is not modelled (QF_FP)

`f32`/`f64`/`float`/`double` are NOT supported: such functions get a NAMED skip
`вещественная арифметика (f32/f64) — модель QF_FP не поддерживается` (`#472`). Before that
fix they silently fell into `i64`, and `debt / equity` (f64/f64) was reported as a
division-by-zero panic although IEEE-754 yields `inf`/`NaN`. **Measured:** 138 such skips on
`TheAlgorithms/Rust`, 4 on `DeepJIT`, 6 on KERN's own Zig core.

### `QF_S`: strings are not modelled — the checker REFUSES, and names the rule (`#515`)

The tamper fuzzer runs five theory banks. Four of them are adversarially verified; the QF_S
(sanitizer) bank is a **named skip**, because the proof checker has no rule for the string theory
lemma and therefore rejects the INTACT proof itself (`rc=1` on a correct proof). This is
**fail-closed**, not a hole: on that theory a tampered step is indistinguishable from a valid one,
so the fuzzer is inapplicable.

**Measured** (`make proof-tamper`; dump via `kernc check-proof tests/fixtures/qfs_sanitizer.smt2
tests/fixtures/qfs_proof.txt`):

```
[ПРУФ-ЧЕКЕР] шагов 39 | … | ДОВЕРЕННЫХ 1 | дыр 0
[i] первое непроверенное правило: th-lemma (структурно) (1 шт.)
[!] ОТВЕРГНУТО: остались непроверенные шаги (trusted)
```

The one trusted step, verbatim from the `KERN_DEBUG_TRUSTED=1` dump:

```
((_ th-lemma seq) @x78 (unit-resolution (def-axiom (or $x91 $x57)) @x312 $x57) false)
```

So the boundary is the theory `seq` (`str.++`, `seq.unit`, `(_ Char …)`) inside `th-lemma`, not a
«structural rewrite» that could be patched cheaply. Before `#515` the refusal named only the COUNT
and not the rule, so the report said «refused» without saying why; now the rule is printed in both
the `prove` and the `check-proof` paths.

## 3. Loop invariants are not modelled (Belnap N)
`while`/`for` are analysed as ONE iteration with the loop condition as a guard. A full
invariant (needs CHC/Horn) is not derived, therefore:
* an index depending on a loop-modified variable yields `[BOUNDS UNKNOWN]` — that is **N**
  (uncertainty), not a finding (`#315`, `#473`);
* findings inside a loop body are not accused without a witness.

## 4. Known false accusations are counted, not hidden

`#476` (CLOSED): the class had SIX causes, each measured and fixed separately — literal vs
symbolic length never tied (`476a`), no bounds for `for .. in range(a, b[, step])` (`476b`),
`d[k] = v` treated as a read (`476c`), `append` growing a literal list (`476d`), a `dict` has
no «index» (`476e`), and one finding counted twice (`476f`). MEASURED: on
`QuixBugs/correct_python_programs` **21 → 4**. `EXPECTED_KNOWN_FP` is now **0** and the
fixture `cmark_autolink.c` moved to `precision_clean` as a NEGATIVE control, so any
regression of this class turns the gate RED.

`#495` (CLOSED, found by TROPHY HUNTING on real code, then diagnosed by delta-minimisation):
a FALSE `[OVERFLOW PATH]` on `closing--` in `cmark-gfm::autolink_delim`. THE PROPOSED CAUSE
WAS WRONG: reassigning the loop bound (`link_end = i`) does not matter — copies without it
reproduce AND copies with it do not. The real cause had TWO parts, both in the inc/dec
detector: it took the INITIALIZER as an EXACT value although the variable is mutated earlier
(`closing++` in a loop), and it ignored guards entirely. MEASURED: `gcc -fsanitize=
undefined,address` on the real function reports **no UB**.

**THE RECALL COST OF `#495` IS NOW MEASURED, NOT «DOCUMENTED»** (`#498c`). The first fix
banned ANY `if/while/for/switch` before the `x++` — and that silenced the very pattern the
detector exists for. MEASURED probes (`tools/kern_contracts.py --xray`):

| probe | before `#498c` | after `#498c` |
|:--|--:|--:|
| `int flag=0; if (flag) {flag=1;} int x=2147483647; x++;` | **0 findings** | **1 finding** (pattern restored) |
| `for (…s+=i…) ; int x=-2147483648; --x;` | **0 findings** | **1 finding** |
| `int x=2147483647; if (x==10) return; x++;` (the guard DOES touch `x`) | 0 | **0** (unchanged: no accusation) |
| `cmark_autolink.c` (the `#495` fixture) | 0 | **0** (`#495` does not regress) |

The rule is now NARROW (measured, not guessed): a finding is suppressed only when the
BRANCH OR LOOP CONDITION MENTIONS THE VARIABLE ITSELF (then the path can narrow the value);
mutations of the variable are caught by a SEPARATE write counter — that counter is what
actually killed the `cmark` false accusation. Cost of the whole `#495`+`#498c` pair on the
official corpus, MEASURED: SV-COMP `signedintegeroverflow-regression` (`make svcomp-baseline`)
**TPR 1.00, FPR 0.00** (10/10 unsafe caught, 0 false alarms on 5 safe — identical to the
pre-`#495` number in `docs/evidence/svcomp_baseline.log`), and
`make svcomp-witness-check` → 37 tasks, 11 UNSAFE confirmed by an external validator,
16 SAFE clean on the enumerated witnesses, **0 false alarms, 0 missed confirmations**
(`docs/evidence/svcomp_after_495.log`). Limits of this number are named there: 4 UNSAFE
tasks are not observable by the compiler/run, and the witness space is bounded.

**Precision on third-party code is measured by machine** (`#475`): `precision_clean` → 0
findings, `precision_buggy` → 5/5, `precision_known_fp` → 0 (retarget fired). The external
corpus `QuixBugs/correct_python_programs` is compared to a NAMED baseline of **4** unique
accusations — and all four are triaged: `kth` (`arr[0]` on an empty list), `rpn_eval`
(`/` by a popped value) and `to_base` (`b == 0`) are REAL crashes on reachable inputs, and
`find_in_sorted` is a closure with an early return (class `#200` below). Target: 0.

**Not every refusal is a defect** (`#491`): `Unsupported` (a node outside the BV subset) and
`SyntaxError` (a foreign language) are EXPECTED exits. MEASURED on our own `kern/src`:
**321** such exits used to print `[!] внутренняя ошибка`; now they are ONE named note with the
reason breakdown, and the report shows **0** internal errors.

## 5. Interprocedural invariants are not checked

Length, non-zeroness and ranges guaranteed by the CALLER are not modelled (`#200`): if
`len > 0` is guaranteed outside, the divisor is still considered suspicious — but we do NOT
accuse (a skip is safer than a false accusation).

## 6. What is checked by WHAT (how to reproduce)

| Limit | Command |
|:--|:--|
| `trusted` next to `PROVEN` | `make evidence-trust` (+ `--selftest`) |
| precision/recall of `--xray` | `make xray-precision` |
| a subprocess without a timeout | `make spawn-check`, `make spawn-selftest` |
| memory of subprocesses | `make audits-mem-check` |
| arithmetic of the corpus | `make audits` |
| **which layers of `--delta` run INSIDE the archive** (`#516`) | `./kerna --delta base head` — the Z3 layer (`--diff-equiv`) works and prints `DIVERGED` with a counterexample; the LIVE layer and the grid probe need a separate `.py` and are named skips in stderr. Not a silent «behaviour is the same». |

## 7. Facts (machine-checked)

core <!-- fact:core_tests -->460 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->491 ·
CHECK targets <!-- fact:check_targets -->192 · can-fail cases <!-- fact:canfail_cases -->237 ·
anchors <!-- fact:anchors -->194 · registry targets <!-- fact:registry_targets -->253 ·
META <!-- fact:meta_targets -->46 · Lean theorems <!-- fact:lean_theorems -->147 ·
QuixBugs SMT <!-- fact:quixbugs.smt -->6 · QuixBugs differential <!-- fact:quixbugs.differential -->40
