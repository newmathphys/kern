# Real bugs found in real projects (before-fix / after-fix)

> Every case below is a **real commit in a real repository**. For each one: the
> exact code before the fix, what KERN says, the counterexample, and a **live run
> of the real code** proving the bug is not a paper construct. Commands are
> reproducible; artefacts are under `docs/evidence/real_history/`.

## Case A - `boltons` commit `5eb6cc0` ("resolve negative Bits indices")

Real guard in `boltons/mathutils.py`, extracted verbatim for both revisions:

```python
# BEFORE (5eb6cc0^)                 # AFTER (5eb6cc0)
def idx_ok(k, n):                   def idx_ok(k, n):
    if k >= n: return 0                 if k < 0: k = k + n
    return 1                            if k < 0 or k >= n: return 0
                                        return 1
```

**KERN (no contract in the source at all):**

```
$ python3 tools/kern_contracts.py --diff-equiv idx_before.py idx_after.py
  [DIVERGED] idx_ok: РЕФАКТОРИНГ ИЗМЕНИЛ ПОВЕДЕНИЕ
     [КОНТРПРИМЕР] k = -1, n = 0, res_old = 1, res_new = 0
```

**Live proof (real Python, the extracted logic):**

```
before(-1, 0) = 1   <- ПРИНИМАЕТ недопустимый индекс (баг)
after(-1, 0)  = 0   <- отвергает (фикс)
before(-6, 5) = 1   <- тоже принимает индекс -6 при длине 5
after(-6, 5)  = 0
```

So KERN detected the semantic change a real library fix introduced, and the
counterexample is executable: the pre-fix guard accepted an index that does not
exist.

## Case B - `boltons` commit `c1c25da` ("Fix off-by-one in Bits length check")

```diff
-        if val > 2 ** len_:
+        if val >= 2 ** len_:
```

**Live proof:**

```
before(val=4, len_=2) = ACCEPT   <- 4 не влезает в 2 бита (баг)
after (val=4, len_=2) = REJECT   <- фикс отвергает
```

Real consequence, as the commit message itself states: `Bits(4, 2)` produced the
3-bit value `'100'` while declaring length 2, silently breaking the
`len`/`__getitem__` invariant.

**KERN cannot check this one - and it is recorded, not hidden (#307):** the guard
contains `2 ** len_`, a power with a **variable** exponent, which is outside the
supported subset. `--diff-equiv` answers "нет одноимённых функций в подмножестве".
This is a coverage limit of the tool, and it is written in the journal.

## Case C - QuixBugs `gcd` (real bug in the canonical dataset)

```python
# buggy                          # dataset reference (fixed)
def gcd(a, b):                   def gcd(a, b):
    if b == 0: return a              if b == 0: return a
    return gcd(a % b, b)             return gcd(b, a % b)
```

**Live proof:**

```
gcd_buggy(1, 2) -> RecursionError   <- реальный краш до фикса
gcd_fixed(1, 2) = 1
```

**KERN:** `tools/trace_explorer.py` reports this task `DIVERGED` with a crash in
the tested function, and the same task is `EXPLORED` (no divergence) once the
dataset's fixed body is in place - that is how the 40/40 result is produced
(`docs/evidence/quixbugs_full.log`).

## Summary

| Case | Repository / commit | KERN verdict | Live proof |
|---|---|---|---|
| A | `boltons` `5eb6cc0` | **DIVERGED** + witness `k = -1, n = 0` | pre-fix guard accepts an invalid index |
| B | `boltons` `c1c25da` | **not checkable** (#307, variable exponent) | `Bits(4, 2)` accepted before the fix |
| C | QuixBugs `gcd` | **DIVERGED** (crash) | `RecursionError` on `gcd(1, 2)` |

Honest framing: two of the three are detected by KERN, one is outside the subset
and is named as such. None of them is a new CVE - these are **known** historical
bugs, and the value of the exercise is that KERN finds them from the code alone.
