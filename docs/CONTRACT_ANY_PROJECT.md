# How to write a contract for ANY project

KERN cannot get findings for free: a repository carries no `@kern:` rules, and an
automatic sweep over third-party code produces a table of zeros (measured: 0 of
715 functions in subset, `audits/README.md`). What it *can* do is prove or refute
**any rule you write** — for anyone's code. This document is that recipe, with a
worked example that found a real defect in a 25k-star repository.

## The recipe (5 steps)

| Step | What you do | Why |
|:--|:--|:--|
| 1 | Pick **one function** whose result you care about | a contract is per-function, not per-repository |
| 2 | State the rule in arithmetic: `requires` (allowed inputs) and `ensures` (promised result) | without a rule there is nothing to prove |
| 3 | If the function has loops/calls, **extract the math core** and say so in the header | the extractor does not model loops; a labelled extraction stays honest |
| 4 | Run `python3 tools/kern_contracts.py <file>` | `PASS` = proven over all inputs, `FAIL` = counterexample, `SKIP` = out of subset |
| 5 | Reproduce the counterexample with the **real compiler** | a model is ours; the witness must be real |

Step 5 is not optional. Without it a refutation is a claim about *our model*.

## Worked example: `TheAlgorithms/C` — a crash on `n = 0`

**Source.** [`TheAlgorithms/C`](https://github.com/TheAlgorithms/C) at
`e5dad3fa8def3726ec850ca66a7f51521f8ad393`, file `math/catalan.c`. Verbatim:

```c
long int factorial(int x) {
    int i; long int fac; fac = x;
    for (i = 1; i < x; i++) fac = fac * (x - i);
    return fac;
}
...
f1 = factorial(2 * n); f2 = factorial(n + 1); f3 = factorial(n);
C = f1 / (f2 * f3);          /* INTEGER division — all operands are long int */
```

**The rule (step 2).** The Catalan formula divides by `factorial(n+1) * factorial(n)`.
That divisor must be positive for the division to be defined:

```
requires n >= 0 and n <= 1
ensures  result > 0
```

**The extraction (step 3).** The loop is unrolled to the two inputs that decide the
obligation. For `n = 0` the original loop body never runs and `fac = x` leaves `0`,
so `factorial(0) == 0` — and every factorial factor for `n <= 1` is `0` or `1`:

```c
// @kern:requires n >= 0 and n <= 1
// @kern:ensures result > 0
int catalan_divisor(int n)
{
    if (n == 0) return 0;   /* factorial(1) * factorial(0) = 1 * 0 */
    return 2;               /* factorial(2) * factorial(1) = 2 * 1 */
}
```

**The verdict (step 4).** Verbatim:

```text
  [FAIL] catalan_divisor: КОНТРАКТ НАРУШЕН
         KERN-EQ2 : F
         ВЕРДИКТ  : НЕ доказано (контрпример/таймаут)
         [КОНТРПРИМЕР] n = 0, result = 0
         [RUNTIME CONFIRMED] контрпример перепроверен конкретным вычислителем тела
                             (модель совпала с исходником)
ИТОГО: доказано 0 | T_advisory 0 | нарушено 1 (из них безопасность: 0) | НЕ РЕШЕНО 0 |
       ЛОЖНЫХ ТРЕВОГ 0 | ВАКУУМНЫХ 0 | вне подмножества 0 | всего 1
```

**The ground truth (step 5).** The original `factorial` compiled by `gcc`, with
`n = 0` — the divisor is `0`, and the division is integer, so the process dies:

```text
n=0 -> f1=0 f2=1 f3=0
Исключение в операции с плавающей точкой (образ памяти сброшен на диск)
rc=136            # 128 + 8 = SIGFPE (integer division by zero)
```

**So:** typing `0` into this program crashes it. The root cause is one line —
`fac = x` initialises the accumulator to `0` instead of `1`, so `factorial(0)`
returns `0` where mathematics requires `1`. `KERN` did not need to understand the
program: it needed one stated rule about the divisor.

## What the same recipe looks like on other projects

| Project | Function | Rule | Verdict |
|:--|:--|:--|:--|
| `saber-hq/stable-swap` @39d5d4e | AMM amp-ramp (i64 form) | `result >= initial_amp` | REFUTED — `rustc -C overflow-checks=on` panics |
| `DaveGamble/cJSON` @6d9f244 | `parse_hex4` per-digit logic | `0 <= result <= 15` | PROVEN (227 steps, holes 0); the fall-through variant REFUTED at `c = 103` |
| `TheAlgorithms/C` @e5dad3f | `catalan.c` divisor | `result > 0` | REFUTED — `gcc` gives SIGFPE |
| money in integer cents | tax / bill split | `0 <= result <= base` | PROVEN; the unguarded split REFUTED at `people = 0` |

## Honest limits of the recipe

- **It is manual, one function at a time.** There is no way to point KERN at a
  repository and get findings; the rule has to come from a human (or from
  `explain --hypotheses`, which proposes and never applies).
- **The extraction must be labelled.** When loops or calls are unrolled by hand,
  the header must say which lines are verbatim and which are rewritten — as above.
- **A refutation is about the model.** For the `i64` AMM case the refuted model is
  ours, not upstream's code. For this Catalan case the extraction is exact for the
  inputs that decide the obligation, and the witness was reproduced by `gcc`.
- **Out of subset stays out of subset.** `lcm` from the same repository is
  `SKIP — вне подмножества`, because it calls `gcd`; loops, pointers, strings and
  floats are not modelled. `SKIP` is a refusal, not a pass.
- **The return value is named `result`** in a contract. Writing any other name
  (`divisor > 0`, say) leaves the solver with a free variable and yields an honest
  `N` — the tool reports "not decided" rather than inventing a verdict.
