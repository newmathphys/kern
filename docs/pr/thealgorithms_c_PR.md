# Pull request — TheAlgorithms/C: `math/catalan.c`

Ready to submit. Fork `https://github.com/TheAlgorithms/C`, apply
[`catalan_fix.patch`](catalan_fix.patch) (`patch -p1` from the repository root),
push a branch, open the PR with the text below.

The patch was verified against the upstream revision
`e5dad3fa8def3726ec850ca66a7f51521f8ad393`: it applies cleanly with `patch -p1`
on a fresh checkout, and after applying, `n = 0` returns `1.00` instead of dying
with SIGFPE.

---

## Title

```
Fix SIGFPE on n=0 and silent wrong output from n=11 in math/catalan.c
```

## Body

`math/catalan.c` has two defects. The first was reported before (#686, opened
2020-10-19, closed 2021-02-17) but the file still contains it.

### 1. Crash on `n = 0`

`factorial` initialises its accumulator as `fac = x` (line 9). For `x = 0` the
loop body never runs, so `factorial(0)` returns `0` — while `0!` is `1`. Line 25
then computes `f1 / (f2 * f3)` with **integer** division, so with `n = 0` the
divisor `factorial(1) * factorial(0)` is `1 * 0 = 0`:

```
$ gcc -O0 -o catalan math/catalan.c     # compiles clean, exit 0
$ echo 0 | ./catalan
Floating point exception (core dumped)  # SIGFPE, exit code 136
$ echo 5 | ./catalan
42.00                                   # correct, exit 0
```

### 2. Silent wrong output from `n = 11`

`f1 = factorial(2 * n)` must fit in `long int`. `20! = 2 432 902 008 176 640 000`
fits; `22! = 1 124 000 727 777 607 680 000` does not. Beyond that the product
overflows and the program prints garbage **with exit code 0**:

| n | correct Catalan | printed | exit code |
|--:|--:|--:|--:|
| 10 | 16796 | `16796.00` | 0 |
| **11** | **58786** | **`-65.00`** | 0 |
| **12** | **208012** | **`-2.00`** | 0 |
| **13** | **742900** | **`0.00`** | 0 |
| 20 | 6564120420 | `0.00` | 0 |

A silent wrong answer is worse than a crash: nothing signals that the number is
meaningless.

### Note for reviewers — the obvious fix is wrong

Changing `fac = x` to `fac = 1` does **not** work. The loop multiplies by
`(x-1), (x-2), …, 1`, so it is `fac = x` that yields `x!`. With `fac = 1` the
function returns `(x-1)!` and `n = 5` prints `126.00` instead of `42.00`.

### The fix

Keep `fac = x`, handle `x == 0` explicitly, and guard the range that the
factorial formula cannot serve:

```diff
     long int fac;  // fac stores x factorial
+    if (x == 0)
+        return 1;  // 0! = 1
     fac = x;
...
     scanf("%d", &n);
+    if (n < 0 || n > 10)
+    {
+        printf("n must be in [0, 10]: (2n)! overflows long int beyond that\n");
+        return 1;
+    }
```

### Verification after the patch

```
n=0   -> 1.00
n=1   -> 1.00
n=2   -> 2.00
n=5   -> 42.00
n=10  -> 16796.00
n=11  -> "n must be in [0, 10]: (2n)! overflows long int beyond that"   exit 1
n=-1  -> "n must be in [0, 10]: (2n)! overflows long int beyond that"   exit 1
```

### How the first defect was found

Not by reading the code, and not by the program's own tests: by stating a
contract and letting a solver refute it. The divisor obligation
`factorial(n+1) * factorial(n) > 0` was refuted with the counterexample
`n = 0, result = 0`, and the counterexample was then reproduced by `gcc` on the
unmodified file — see [KERN](https://github.com/newmathphys/kern), which also
documents the case in `docs/SHADOW_AUDIT_EXAMPLE.md`.

The second defect (the overflow) came from arithmetic reasoning about `22!`
versus `2^63 - 1`, not from the solver.
