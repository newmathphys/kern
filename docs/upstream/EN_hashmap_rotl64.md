`XXH_rotl64`: shift by 64 is UB at `r == 0`, and `64 - r` overflows `int`

Tested on `3735986`.

```c
// hashmap.c:675-677
static uint64_t XXH_rotl64(uint64_t x, int r) {
    return (x << r) | (x >> (64 - r));
}
```

**1. Shift by 64 (UB).** At `r == 0` the expression becomes `x >> 64`, which is undefined
behaviour in C. Live UBSan run:

```
rot.c:4:26: runtime error: shift exponent 64 is too large for 64-bit type 'long unsigned int'
rotl64(x,0) = 0
```

**2. `64 - r` overflows `int`.** `r` is `int` and the domain is not constrained, so `r = INT_MIN`
makes `64 - r` unrepresentable (signed overflow is UB too).

Inside this file the helper is only called with `r = 31`, so no current path is affected - but the
XXH64 block is copied between projects all the time, and at `r = 0` that is a live UB.

Two-line fix:

```c
static uint64_t XXH_rotl64(uint64_t x, int r) {
    r &= 63;
    return (x << r) | (x >> ((64 - r) & 63));
}
```

Found with a C analyser (KERN v2.8.3, `--xray`); both facts above were then confirmed with
`gcc -fsanitize=undefined`.
