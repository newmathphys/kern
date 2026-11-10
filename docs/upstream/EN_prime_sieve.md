`prime_sieve.c`: off-by-one in `prime()` and `count()` - heap-buffer-overflow (ASan confirms)

Tested on `e5dad3f`.

```c
// math/prime_sieve.c
const unsigned long long MAX_SIZE = 1000000;

void prime(int *p)
{
	for(long long int i=3;i<=MAX_SIZE;i+=2) { p[i]=1; }     // writes p[MAX_SIZE]
	...
	    for(long long int j=i*i;j<=MAX_SIZE;j+=i) {        // same <=

int count(int *arr, const int size){
  int k=0;
  for(int i=0;i<=size;i++){                                // reads arr[size]
```

`<=` on the bound makes both loops touch index `size` / `MAX_SIZE`, i.e. exactly one element past
the end of a buffer that holds `size` / `MAX_SIZE` elements.

Live ASan run on the functions copied verbatim out of the file:

```
# prime(p), p = malloc(1000000 * sizeof(int))
==ERROR: AddressSanitizer: heap-buffer-overflow
WRITE of size 4
    #0 in prime ps_fn.c:9
0 bytes after 4000000-byte region

# count(a, 10), a = malloc(10 * sizeof(int))
==ERROR: AddressSanitizer: heap-buffer-overflow
READ of size 4
SUMMARY: AddressSanitizer: heap-buffer-overflow ps_fn.c:26 in count
0 bytes after 40-byte region
```

The in-repo `test()` does not catch it: it allocates `int arr[1000005]` and calls `count(arr, 10)`,
so there is slack at both ends.

Fix - three characters:

```c
for(long long int i=3;i<MAX_SIZE;i+=2)
for(long long int j=i*i;j<MAX_SIZE;j+=i)
for(int i=0;i<size;i++)
```

(or document that the buffer must hold `size + 1` elements, but then `prime()` and `count()` disagree
with their own names.)

Found with a C analyser (KERN v2.8.3, `--xray`, off-by-one detector); confirmed with
`gcc -fsanitize=address,undefined`.
