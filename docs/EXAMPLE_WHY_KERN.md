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

## Why this matters

An AI agent (or a junior) writes `lcm` and runs `lcm(2,3)` — green. The same
function overflows on large inputs, silently, in production. KERN is the only
check in the chain that answers **"is it true for every input"** instead of
"did these three examples pass".

The same pipeline found two real defects in released code:

- `TheAlgorithms/C#1595` — `math/catalan.c`: `SIGFPE` on `n = 0` (22.5k ★)
- `TheAlgorithms/Rust#1075` — `binom(0, 2)`: `u64` underflow (26k ★)

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
| Core tests | <!-- fact:core_tests -->436 |
| Next tests | <!-- fact:next_tests -->53 |
| Test catalog | <!-- fact:catalog -->465 |
| CHECK targets | <!-- fact:check_targets -->158 |
| can-fail cases | <!-- fact:canfail_cases -->180 |
| Literal anchors | <!-- fact:anchors -->141 |
| Registry targets | <!-- fact:registry_targets -->206 |
| Lean theorems | <!-- fact:lean_theorems -->143 |
| QuixBugs (SMT) | <!-- fact:quixbugs.smt -->6 |
| QuixBugs (differential) | <!-- fact:quixbugs.differential -->40 |
| META targets | <!-- fact:meta_targets -->34 |
