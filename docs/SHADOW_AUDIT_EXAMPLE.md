# Shadow-audit case study: two real defects in `TheAlgorithms/C`

What this is: a worked example of the recipe in
[`CONTRACT_ANY_PROJECT.md`](CONTRACT_ANY_PROJECT.md), run against a real,
widely-used repository. **Two** distinct defects were found in one 28-line file,
both reproduced on the untouched upstream source.

| | |
|:--|:--|
| Repository | [`TheAlgorithms/C`](https://github.com/TheAlgorithms/C) |
| Commit | `e5dad3fa8def3726ec850ca66a7f51521f8ad393` |
| File | `math/catalan.c` (28 lines) |
| Found by | KERN contract check + `gcc` ground truth |
| Upstream status | a bug report exists (**issue #686**, opened 2020-10-19, closed 2021-02-17) and the defect is **still in the file** |
| Fix submitted | **[PR #1595](https://github.com/TheAlgorithms/C/pull/1595)** — opened 2026-10-21, one file, `+7 −0` |

## The source (verbatim, lines 5–15 and 21–26)

```c
long int factorial(int x)  // long int for more than 10 factorial
{
    int i;
    long int fac;  // fac stores x factorial
    fac = x;                                    /* line 9 */
    for (i = 1; i < x; i++)  // loop to calculate x factorial
    {
        fac = fac * (x - i);
    }
    return fac;
}
...
scanf("%d", &n);
f1 = factorial(2 * n);
f2 = factorial(n + 1);
f3 = factorial(n);
C = f1 / (f2 * f3);  // formula for catalan number for n   /* line 25: INTEGER division */
```

## Defect A — crash on `n = 0`

For `x = 0` the loop body never runs, so `fac = x` leaves `0`: **`factorial(0)`
returns 0**, where mathematics requires 1. Then `f3 = factorial(0) = 0`, and line
25 is integer division, so the divisor `f2 * f3` is zero.

KERN's verdict on the extracted obligation (`ensures result > 0` over the
divisor, loop unrolled to the two inputs that decide it):

```text
  [FAIL] catalan_divisor: КОНТРАКТ НАРУШЕН
         [КОНТРПРИМЕР] n = 0, result = 0
         [RUNTIME CONFIRMED] контрпример перепроверен конкретным вычислителем тела
```

Ground truth on the **untouched upstream file**:

```text
$ gcc -O0 -o catalan math/catalan.c        # rc=0, compiles clean
$ echo 0 | ./catalan
Исключение в операции с плавающей точкой (образ памяти сброшен на диск)
rc=136                                     # 128 + 8 = SIGFPE
$ echo 5 | ./catalan
42.00                                      # correct, rc=0
```

## Defect B — silent wrong answers for `n >= 11`

`f1 = factorial(2n)` must fit in `long int` (64-bit here). `20!` fits
(2 432 902 008 176 640 000); `22!` does not (1.12e21 > 2^63-1). So for `n >= 11`
the product overflows, and the program prints garbage **with exit code 0**:

| `n` | true Catalan | what the program prints | rc |
|--:|--:|--:|--:|
| 9 | 4862 | `4862.00` | 0 |
| 10 | 16796 | `16796.00` | 0 |
| **11** | **58786** | **`-65.00`** | 0 |
| **12** | **208012** | **`-2.00`** | 0 |
| **13** | **742900** | **`0.00`** | 0 |
| 20 | 6564120420 | `0.00` | 0 |

A silent wrong answer is worse than a crash: nothing in the output signals that
the number is meaningless.

## The fix — and a warning about the obvious wrong fix

**Do not** simply change `fac = x` to `fac = 1`.** The loop multiplies by
`(x-1), (x-2), …, 1`, so it is `fac = x` that produces `x!`. With `fac = 1` the
function returns `(x-1)!` and the program silently produces wrong results for
every `n >= 1`:

```text
$ echo 5 | ./catalan_fac1      # after the WRONG fix
126.00                          # should be 42.00
```

The correct minimal fix keeps `fac = x` and handles `x == 0` explicitly, plus a
range guard for the overflow:

```diff
     long int fac;  // fac stores x factorial
+    if (x == 0)
+        return 1;  // 0! = 1: without this factorial(0) = 0 and the formula divides by zero
     fac = x;
...
     scanf("%d", &n);
+    if (n < 0 || n > 10)
+    {
+        printf("n must be in [0, 10]: (2n)! overflows long int beyond that\n");
+        return 1;
+    }
```

Verified after the fix:

```text
n=0  -> 1.00        n=1  -> 1.00       n=2  -> 2.00
n=5  -> 42.00       n=10 -> 16796.00
n=11 -> "n must be in [0, 10]: ..."    rc=1
n=-1 -> "n must be in [0, 10]: ..."    rc=1
```

## Honest scope

- **The counterexample is ours, the crash is theirs.** The obligation was checked
  on an extraction (loop unrolled to `n = 0` and `n = 1`, exact for those inputs);
  the SIGFPE was then reproduced by compiling the **unmodified** upstream file.
- **KERN did not read the repository.** It was given one function and one rule.
  Finding the second defect (the overflow) needed arithmetic reasoning about
  `22!` vs `2^63-1`, not a solver.
- **No claim of a security impact.** This is an educational program reading one
  integer from stdin; the impact is a crash and wrong output.
- **Upstream already has a closed report.** Issue #686 ("[BUG] Catalan program
  doesn't work", closed 2021-02-17) shows the defect was noticed; the file still
  contains it. The minimal fix was submitted as
  **[PR #1595](https://github.com/TheAlgorithms/C/pull/1595)** — the full text is
  in [`pr/thealgorithms_c_PR.md`](pr/thealgorithms_c_PR.md), the patch in
  [`pr/catalan_fix.patch`](pr/catalan_fix.patch).

## Sweep of the whole `math/` directory (all KERN modes)

After the case study above, `--xray` was run over `TheAlgorithms/C/math/` — every
C file, no annotations. Four candidates came out; each was then checked by hand.

| Finding | File | Verdict after review |
|:--|:--|:--|
| `off-by-one: i <= size` in `count` | `prime_sieve.c:44` | **AMBIGUOUS CONTRACT, not a defect** — the doc block says "upto which" (inclusive) while the test comment says "array size" (exclusive); the test uses `size = 10`, the one value that cannot distinguish them. See below and defect **#320** |
| `off-by-one: i <= MAX_SIZE` | `prime_sieve.c:23` | not a memory error — `int arr[1000005]` is oversized for `MAX_SIZE = 1000000` |
| `off-by-one: j <= MAX_SIZE` | `prime_sieve.c:27` | same: index reaches 1000000, the array holds 0..1000004 |
| `division by zero: x == 0` | `cartesian_to_polar.c` | **FALSE ALARM** — the division is under `if (x != 0)` (line 28, division on line 32); this is defect **#318** |

### Correction (defect #320): this candidate was **withdrawn**

An earlier revision of this document called `prime_sieve.c:44` a **REAL logic
defect** and printed `count(arr, size=10) = 5`. Re-running the check against the
**real** prime array produced by the same program does not support that:

```
indices:  0=0 1=0 2=1 3=1 5=1 7=1 10=0 11=1 13=1
count(arr, 3)       = 2      vs "first 3 elements"       = 1      DIFFER
count(arr, 7)       = 4      vs "first 7"                = 3      DIFFER
count(arr, 10)      = 4      vs "first 10"               = 4      same   <- the test uses 10
count(arr, 11)      = 5      vs "first 11"               = 4      DIFFER
count(arr, 13)      = 6      vs "first 13"               = 5      DIFFER
count(arr, 97)      = 25     vs "first 97"               = 24     DIFFER
count(arr, 1000000) = 78498  vs "first 1000000"          = 78498  same
```

The `5` came from a **synthetic** array (with `arr[10] = 1`), not from the real
one. On the real array `count(arr, 10) = 4`, because 10 is not prime.

Worse, the source is **self-contradictory about the contract**:

| Where | Wording | Reading |
|:--|:--|:--|
| doc block of `count` | `@param size denotes **upto which** prime numbers are to be found out` | **inclusive** → `i <= size` is **correct** |
| test comment | `const int size = 10; /* **array size** */` | **exclusive** → off-by-one |

The two readings differ exactly when `size` is itself prime — and the test happens
to use `size = 10`, which is not. So the test **cannot** detect the difference, and
the code is not demonstrably wrong under its own documentation.

**Verdict: an ambiguous contract, not a defect.** No upstream report will be
opened for it. The harness that produced the table above is committed at
[`../docs/evidence/prime_sieve/`](../docs/evidence/prime_sieve/) so the numbers can
be re-derived instead of believed.

This is the reason for principle 7 in [`PLAN_v2.6.4.md`](PLAN_v2.6.4.md): a numeric
claim in a document must ship with a harness that reproduces it.


### The false alarm, honestly reported

`--xray` accuses `atan(y / x)` of dividing by zero although the enclosing
`if (x != 0)` guards it. A minimal reproducer is committed with defect **#318**:

```c
int f(int x, int y) { if (x != 0) { return y / x; } return 0; }
```

This is exactly the trade-off the project keeps documenting: a scanner that
reports guarded code as vulnerable is a scanner nobody trusts. It is filed as a
defect, not dismissed as noise.

### What this sweep does and does not show

- **Does:** KERN can be pointed at an unannotated C directory and produce
  candidates; one of them was a genuine logic defect, confirmed by hand.
- **Does not:** prove the absence of other defects. Most functions are outside
  the analysed subset, and `0 findings` would mean "nothing proven and nothing
  refuted inside the subset", not "clean code".
- **Does not:** replace review. One of four candidates was a false alarm, and two
  more were technically-correct code that merely looked suspicious.
