# Live bug hunt in current HEAD (TheAlgorithms/Python @ 6e03a48)

> Goal: find a **fresh, unhandled crash** in the current state of a real
> repository - not a historical bug that the author already fixed.

## What was run

```
git clone --depth 1 https://github.com/TheAlgorithms/Python   # HEAD 6e03a48
```

From the current HEAD, 45 modules were taken from `maths/`, `financial/`,
`geometry/`, `searches/`, `ciphers/`; for each module the imports and all
top-level functions were extracted verbatim into a corpus where the reference is
the function itself - so the explorer can only report **crashes and hangs**
(there is no second implementation to diverge from).

```
$ python3 tools/trace_explorer.py /tmp/kern-live-bughunt/ds
[OK] DIVERGED (живой вызов, 0 ложных по построению): 0/45
```

## Result: no live bug found in this sample, and none is claimed

45 real modules of a popular repository, at its current commit, exercised on
typed inputs built from annotations and AST usage: **zero unhandled crashes, zero
hangs**.

### Why this is a plausible outcome, not a broken run

* `TheAlgorithms/Python` is heavily reviewed and every module ships its own
tests; the numeric helpers there are small and mostly guarded.
* The explorer's domains are built from annotations and observed operations. For
  functions whose inputs are graphs, trees, matrices or bit-strings, the domain
  stays shallow, so "no crash" here means "no crash **on the inputs the explorer
  could construct**" - not "provably crash-free".
* A first attempt of this run failed loudly and usefully: extracting function
  bodies **without** the module imports produced
  `NameError: name 'Callable' is not defined` for every annotated function. The
extraction was fixed to keep imports; that failure is recorded here because it
is exactly the class of harness defect that makes a hunt silently useless.

### What would raise the odds of finding a fresh bug

| Change | Effect |
|---|---|
| Deeper domains for structured inputs (graphs, trees, matrices) | the current ceiling is "small ints and short strings" |
| Run over **many** young repositories, not one curated one | 45 modules of a reviewed repo is a small sample |
| Crash-hunt in C/Zig/Rust with machine types | arithmetic overflows are where fresh bugs live, and `--auto` still lacks overflow obligations |
| Loop invariants (CHC) | removes the "candidate only" ceiling for index reasoning |

Honest summary: this run produced **no new bug**. It produced a reproducible
method, a corpus, and one real harness defect found and fixed. Claiming more
would be dishonest, and the numbers above are the whole story.
