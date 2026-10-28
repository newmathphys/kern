# Why KERN: one real example, 30 seconds

This page shows the whole point of KERN on **someone else's code**. Nothing here
is a mock-up: every command is reproducible, every number was measured.

## The code (not ours)

`TheAlgorithms/C` (22.5k ★), file `math/lcm.c`, line 20 — **verbatim**:

```c
int gcd(int a, int b) {
    if (a == 0) return b;
    return gcd(b % a, a);
}

int lcm(int a, int b) { return (a * b) / gcd(a, b); }
```

`lcm` is taught as `a*b / gcd(a,b)`. It is correct **mathematically** and wrong
**in `int`** — but nothing in the file says so, and no test in the repository
covers large inputs.

## The contract (one line of intent)

We do not touch their code. We add two comment lines above the expression:

```c
/* SOURCE: TheAlgorithms/C @ math/lcm.c, line 20 — expression VERBATIM:
       int lcm(int a, int b) { return (a * b) / gcd(a, b); }
   Here we check the NUMERATOR `a * b` (i32) — what KERN can reason about.
   The call gcd(a,b) is an inter-procedural barrier and is reported separately. */
// @kern:requires a >= 0 and b >= 0
// @kern:ensures result >= a
int lcm_numerator(int a, int b) { return a * b; }
```

## KERN's answer

```
$ python3 tools/kern_contracts.py lcm_core.c
  [FAIL] lcm_numerator: КОНТРАКТ НАРУШЕН
         [КОНТРПРИМЕР] a = #x643b3fbb, b = #x5a724dfe, result = #x643a7a8a
```

`a = 1681908667`, `b = 1517634558` — and the product does not fit in `i32`.

## Ground truth: the real compiler

The counterexample is not a paper claim. Their own function, compiled by `gcc`:

```
$ gcc -O0 -fsanitize=undefined -fno-sanitize-recover=all -o lcm_probe lcm_probe.c
$ ./lcm_probe
lcm_probe.c:24:16: runtime error: signed integer overflow:
    1681908667 * 1517634558 cannot be represented in type 'int'
```

**The defect is real, and it is in code that has been read by millions.**

## What just happened, in one line

| | |
|:--|:--|
| Tests | check a few inputs → `lcm(2,3)` passes → "green" |
| **KERN** | checks **all** inputs of `int` → finds the exact pair where it breaks |

## What KERN does NOT do here

- It did **not** read the repository. It was given one expression and one rule.
- It did **not** fix anything. The rule came from a human.
- The call to `gcd` is **out of scope** and is reported honestly:
  `SKIP — вне подмножества: узел Call`. Without extracting the arithmetic core,
  `lcm` as a whole is not checkable — and KERN says so instead of guessing.

## Try it yourself (3 commands)

```bash
git clone --depth 1 https://github.com/TheAlgorithms/C ~/.cache/kern/repos/C
# paste the file from the "contract" section above, then:
python3 tools/kern_contracts.py lcm_core.c
```

## Other real cases (same pipeline, different repositories)

| # | Repository | What was checked | Verdict | Ground truth |
|:--|:--|:--|:--|:--|
| 1 | **TheAlgorithms/C** `math/lcm.c` | numerator `a * b` (i32) | **FAIL** `a = #x643b3fbb, b = #x5a724dfe`; and `a = b = 50000` prints **`-35899`** where the true LCM `50000` fits in `int` | `gcc -fsanitize=undefined` → `signed integer overflow: 50000 * 50000`; also `SIGFPE` at `0, 0`. PR [#1596](https://github.com/TheAlgorithms/C/pull/1596) |
| 2 | **TheAlgorithms/C** `math/catalan.c` | divisor `factorial(n+1) * factorial(n)` | **FAIL** `n = 0` → divisor is `0` | `gcc` → **SIGFPE, rc=136**; PR [#1595](https://github.com/TheAlgorithms/C/pull/1595) |
| 3 | **TheAlgorithms/Rust** `binomial_coefficient.rs` | `n - i` (u64) under `i < k` | **FAIL** `n = 0, i = 1, k = 2` → `-1` | `rustc` debug → `attempt to subtract with overflow` (rc=101); PR [#1075](https://github.com/TheAlgorithms/Rust/pull/1075) |
| 4 | **TheAlgorithms/Rust** `binary_exponentiation.rs` | `result_pow *= n` (u64) inside the loop | **FAIL** `r = #xffffffffd7ffbfff, n = #x6aaa` | silent wrap — the function returns a value that is not the power |
| 5 | **mahmoud/boltons** commit `5eb6cc0` | two revisions of the index check (`--diff-equiv`, **no contract at all**) | **DIVERGED** `k = -1, n = 0`: old accepts, new rejects | live Python replay of both revisions |
| 6 | **madler/zlib** `zcalloc.c` | allocation size `items * size` (u32) | **REFUTED** `items = #x8e0ff0f1, size = #x5ffeffef, result = #xffffffff` | the classic pre-heap pattern: the size wraps, a small buffer is allocated, then overfilled |
| 7 | **ziglang/zig** `std/mem.zig` | `alignForward` = `addr + alignment - 1` (u32) | **REFUTED** `addr = 4294967295, alignment = 2, result = 4294967296` | arithmetic at the very top of the `u32` range |
| 8 | **tigerbeetle/tigerbeetle** `src/stdx/stdx.zig` | `divCeil` against `(n + d - 1) / d` | **PROVEN** — 98 steps, `holes: 0`, the certificate re-checked by KERN's own proof checker | — |
| 9 | **ghostty-org/ghostty** `src/renderer/size.zig` | `@max(1, cols)` — "the grid is never empty" | **PROVEN** (after defect #118: the proof checker learned the `def-axiom`/`trans*` rules instead of trusting the solver) | — |
| 10 | **openjdk / J. Bloch (2006)** | `mid = (low + high) / 2` | **REFUTED** `low = #x00000804, high = #x7ffff7fc, result = #xc0000000` | the famous nine-year bug; invisible in `Int`, visible only in QF_BV |

**Six repositories, five languages (C, Zig, Rust, Python, Java), ten cases** — and two
upstream pull requests. Case 5 needs no contract: it compares two revisions and
shows the semantic change a real fix introduced.

**Read the verdicts honestly.** `PROVEN` means the obligation is unsatisfiable *and*
KERN's own proof checker re-checked Z3's certificate. `REFUTED` on the real (not
`…Buggy`) functions means a **safety** obligation fired — overflow or a zero divisor.
That is a boundary of applicability, not an accusation: KERN says "this expression
overflows for these inputs", not "your project is broken". The `…Buggy` controls exist
because a checker that cannot say **no** is worthless.

### Why case 4 is stated carefully

`result_pow *= n` overflowing is **expected** for exponentiation — the honest
claim is not "here is a bug in their code", but "the function silently wraps and
does not document the limit; KERN shows the exact inputs". The distinction
matters: a false accusation is worse than a miss.

### What these cases are not

None of them is a CVE, and none was found by scanning a repository. In every
case a human wrote the rule (or chose the two revisions), and KERN decided for
**all** inputs. Measured on the same pipeline: **0 of 715** functions in foreign
repositories fall inside the subset — a repository-wide scan produces zeros.



## Why this matters

An AI agent (or a junior) writes `lcm` and runs `lcm(2,3)` — green. The same
function overflows on large inputs, silently, in production. KERN is the only
check in the chain that answers **"is it true for every input"** instead of
"did these three examples pass".

## The boundary, stated plainly

KERN is not a scanner. It will not find bugs in a repository on its own:
measured, **0 of 715** functions in foreign repositories fall inside its
subset. It is a **scalpel plus a turnstile**:

- **scalpel** — you state the rule, it decides for **all** inputs;
- **turnstile** — it refuses to let an agent weaken the rule
  (`make contracts-lock-check` → `rc=2`).

---

## Facts (synchronised by `make sync`)

| Fact | Value |
|:--|:--|
| Core tests | <!-- fact:core_tests -->451 |
| Next tests | <!-- fact:next_tests -->53 |
| Test catalog | <!-- fact:catalog -->480 |
| CHECK targets | <!-- fact:check_targets -->175 |
| can-fail cases | <!-- fact:canfail_cases -->213 |
| Literal anchors | <!-- fact:anchors -->174 |
| Registry targets | <!-- fact:registry_targets -->228 |
| Lean theorems | <!-- fact:lean_theorems -->147 |
| QuixBugs (SMT) | <!-- fact:quixbugs.smt -->6 |
| QuixBugs (differential) | <!-- fact:quixbugs.differential -->40 |
| META targets | <!-- fact:meta_targets -->39 |
