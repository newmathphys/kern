# Pull request — TheAlgorithms/C: `math/lcm.c`

**PREPARED, not yet submitted.** [`lcm_fix.patch`](lcm_fix.patch) applies with
`git apply` (verified `git apply --check`) from the repository root, against the
upstream revision cloned 2026-10-26. After applying, both defects below are gone
and the file's own test cases still pass.

---

## Title

```
Fix signed overflow in math/lcm.c (wrong answer when the LCM itself fits in int)
and SIGFPE when both inputs are zero
```

## Body

`math/lcm.c` has two defects, both in the same expression:

```c
int lcm(int a, int b) { return (a * b) / gcd(a, b); }
```

### 1. The intermediate product overflows even when the answer does not

`(a * b)` is computed **before** the division. For `a = b = 50000` the true
`lcm(50000, 50000)` is `50000` — it fits in `int` with room to spare (about
40 000 times over) — but the intermediate product is `2500000000`, which exceeds
`INT_MAX` (`2147483647`). In C11 that is **undefined behaviour**, and the program
prints a wrong answer:

```
$ gcc -w -O0 lib.c -o lcm_plain && ./lcm_plain 50000 50000
lcm(50000, 50000) = -35899          # should be 50000

$ gcc -w -O0 -fsanitize=undefined lib.c -o lcm_ubsan && ./lcm_ubsan 50000 50000
lib.c:19:35: runtime error: signed integer overflow: 50000 * 50000 cannot be
             represented in type 'int'
lcm(50000, 50000) = -35899
```

The file's own documented test cases (`15,20 → 60` and `12,18 → 36`) pass, which
is why this went unnoticed: both stay far below `sqrt(INT_MAX) ≈ 46341`.

### 2. `SIGFPE` when both inputs are zero

`gcd(0, 0)` returns `0` (the `a == 0` branch returns `b`), so the divisor is
zero and the program dies:

```
$ ./lcm_plain 0 0
Floating point exception (core dumped)   # exit code 136
$ ./lcm_ubsan 0 0
lib.c:19:40: runtime error: division by zero
```

`lcm(0, 0)` is conventionally `0`.

### The fix

```c
int lcm(int a, int b)
{
    if (a == 0 || b == 0)
        return 0;

    return (a / gcd(a, b)) * b;
}
```

Two changes, each addressing one defect:

* **Divide before multiplying.** `gcd(a, b)` divides `a` exactly, so
  `a / gcd(a, b)` is exact, and the intermediate value never exceeds the true
  LCM. The old order computed a product up to `a * b` for no reason.
* **Guard the zero case** so `gcd(0, 0) == 0` cannot become a divisor.

### Verification after the patch

```
$ gcc -w -O0 -fsanitize=undefined lib_fixed.c -o lcm_fixed_bin
$ ./lcm_fixed_bin 50000 50000
lcm(50000, 50000) = 50000          # correct, no UBSan diagnostic
$ ./lcm_fixed_bin 0 0
lcm(0, 0) = 0                      # no SIGFPE
$ ./lcm_fixed_bin 15 20
lcm(15, 20) = 60                   # unchanged
$ ./lcm_fixed_bin 12 18
lcm(12, 18) = 36                   # unchanged
```

No sanitizer diagnostic is emitted for any of the four inputs.

### How this was found

Not by reading the code — by stating a contract for the arithmetic and letting a
solver refute it, then confirming with `gcc`. The end-to-end account is in
[`docs/EXAMPLE_WHY_KERN.md`](../EXAMPLE_WHY_KERN.md).

### Scope of the fix

The change is local to `lcm()`. `gcd()` is untouched. If `lcm(a, b)` itself does
not fit in `int`, the result still cannot be represented — that is inherent in
the `int` return type and is **not** claimed to be fixed here.

---

## Reproduction script (as run)

```bash
git clone --depth 1 https://github.com/TheAlgorithms/C /tmp/TheAlgorithmsC
cd /tmp/TheAlgorithmsC && git apply --check <lcm_fix.patch>   # clean
```
