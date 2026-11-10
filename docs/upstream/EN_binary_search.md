`binary_search.c`: `r - l` overflows for a negative `l`

Tested on `e5dad3f`.

```c
// searching/binary_search.c:21-25
int binarysearch1(const int *arr, int l, int r, int x)
{
    if (r >= l)
    {
        int mid = l + (r - l) / 2;
```

`l + (r - l) / 2` is the right shape - it avoids the classic `l + r` overflow. It does not protect
against a **negative `l`**: with `l = INT_MIN` and `r > 0`, `r - l` is not representable in `int`,
which is undefined behaviour.

Live UBSan run on the function copied verbatim out of the file:

```
bs_fn.c:5:26: runtime error: signed integer overflow: 2147483647 - -2147483648
              cannot be represented in type 'int'
```

`l` is a parameter, and neither the type nor an assertion rules out `l < 0`. This repository is
educational, so the snippet gets copied into projects where `l` comes from an outside call.

One-line fix:

```c
int mid = l + (int)(((long long)r - (long long)l) / 2);
```

or make the domain explicit:

```c
assert(l >= 0 && r >= l);
int mid = l + (r - l) / 2;
```

Found with a C analyser (KERN v2.8.3, `--xray`); the overflow was then confirmed with
`gcc -fsanitize=undefined`.
