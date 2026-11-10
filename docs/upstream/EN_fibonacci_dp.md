`fibonacci_dp.c`: `(n + 2)` overflows `int`, then ASan rejects the allocation (n comes from stdin)

Tested on `e5dad3f`. Third and last finding of one analyser sweep over this repository.

```c
// math/fibonacci_dp.c:19-20
int *out = (int *)malloc((n + 2) * sizeof(int));
```

`n` is read from stdin (`scanf`), so the user controls it. At `n = INT_MAX`, `n + 2` is not
representable in `int` - signed overflow, undefined behaviour - and the resulting size passed to
`malloc` is nonsense.

Live run of the unmodified file from the repository:

```
$ gcc -fsanitize=address,undefined fibonacci_dp.c -o fib
$ printf '2147483647\n' | ./fib
fibonacci_dp.c:20:12: runtime error: signed integer overflow: 2147483647 + 2 cannot be represented in type 'int'
==ERROR: AddressSanitizer: requested allocation size 0xfffffffe00000004 (0xfffffffe00001008 after adjustments for alignment, red zones etc.)
    #1 in fib fibonacci_dp.c:19
    #2 in main fibonacci_dp.c:51
```

Two fixes, whichever you prefer - check first, then compute in a wide type:

```c
if (n < 0 || n > some_sane_limit) { /* report and return */ }
size_t count = (size_t)n + 2;
int *out = malloc(count * sizeof *out);
if (!out) return NULL;
```

Note the second line matters on its own: `(n + 2) * sizeof(int)` is computed in `int` before the
conversion, so even without an overflow in `n + 2`, a value near `INT_MAX / 4` would overflow the
multiplication on 32-bit `size_t`.

Found with a C analyser (KERN v2.8.3, `--xray`); confirmed with `gcc -fsanitize=address,undefined`.
