`binom(n, k)` underflows `u64` when `k > n`: the loop runs for `i in 0..k`, so
it evaluates `n - i` for `i > n`.

```
$ cargo test            # debug build, overflow checks ON
thread 'main' panicked at ...:
attempt to subtract with overflow

$ cargo run --release   # checks OFF
binom(0, 2) -> 18446744073709551615   # garbage, exit code 0
```

All seven existing tests use `k <= n`, so the case is not covered:

| test | n, k |
|:--|:--|
| `test_binom_5_2` | 5, 2 |
| `test_binom_10_5` | 10, 5 |
| `test_binom_0_0` | 0, 0 |
| `test_binom_large_n_small_k` | 1000, 2 |
| `test_binom_random_1` | 7, 4 |
| `test_binom_random_2` | 12, 3 |
| `test_binom_random_3` | 20, 10 |

Mathematically `C(n, k) = 0` for `k > n`, so the function should return `0`
rather than panic or return garbage.

### The fix

Guard the case explicitly and keep the rest unchanged:

```diff
 pub fn binom(n: u64, k: u64) -> BigInt {
+    // C(n, k) = 0 for k > n. Without this guard the loop below evaluates
+    // `n - i` for i > n, which is invalid for u64: a debug build panics with
+    // "attempt to subtract with overflow", and a release build silently wraps
+    // to 18446744073709551615 and returns garbage instead of 0.
+    if k > n {
+        return BigInt::from(0);
+    }
+
     let mut res = BigInt::from_u64(1).unwrap();
```

A regression test is added in the same commit, so CI covers the case:

```rust
#[test]
fn test_binom_k_greater_than_n() {
    assert_eq!(binom(0, 2), BigInt::from(0));
    assert_eq!(binom(5, 7), BigInt::from(0));
}
```

### Verification

The guard was checked against the seven existing expectations (no regression)
and against the three failing inputs, using the same arithmetic as the function
body:

```
binom(5,2)   = 10        expected 10        OK
binom(10,5)  = 252       expected 252       OK
binom(0,0)   = 1         expected 1         OK
binom(1000,2)= 499500    expected 499500    OK
binom(7,4)   = 35        expected 35        OK
binom(12,3)  = 220       expected 220       OK
binom(20,10) = 184756    expected 184756    OK

binom(0,2) = 0   (was: panic / garbage)
binom(5,7) = 0   (was: panic / garbage)
binom(1,3) = 0   (was: panic / garbage)
```

### How this was found

Not by reading the code: by stating a contract for the expression `n - i` with
the loop's own condition (`requires i < k`, `ensures result >= 0`) and letting a
SMT solver refute it. The counterexample was `n = 0, i = 1` — reachable as
`binom(0, 2)` — and was then reproduced with `rustc` (panic in debug, wrapped
garbage in release). See [KERN](https://github.com/newmathphys/kern), which
documents the case.

Happy to adjust the style (for example, documenting `k <= n` as a precondition
instead of returning 0) if you prefer that contract.
