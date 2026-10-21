# KERN on high-stakes math cores: three targeted checks

What this document is: three **targeted** checks of KERN's contract verifier on
arithmetic that moves money, sizes memory, or parses untrusted input. Each case
names the real repository and commit, shows the code that was checked, the
contract, and KERN's **verbatim** output.

It is **not** a repository scan. KERN verifies *contracts*, and third-party
repositories contain none — an automatic sweep over them produces a table of
zeros, which is measured in `audits/README.md` (0 of 715 functions in subset).
So each case below extracts a **math core** and states exactly what was taken
from the original and what was rewritten to fit the supported subset.

| Case | Repository | Commit | What was checked |
|:--|:--|:--|:--|
| 1 | [`saber-hq/stable-swap`](https://github.com/saber-hq/stable-swap) | `39d5d4e0e844a009c83d37a3ce63d219fdba0bff` | `StableSwap::compute_amp_factor`, ramp-up branch |
| 2 | [`DaveGamble/cJSON`](https://github.com/DaveGamble/cJSON) | `6d9f2443ab071f86e5d9b43025a40929ec41c46c` | per-digit logic of `parse_hex4` |
| 3 | money in integer cents (pattern from `TheAlgorithms/Python` `financial/`) | — | tax and bill-split arithmetic |

Raw artefacts (verbatim logs, the checked sources, compiler transcripts):
`docs/evidence/high_stakes/`.

---

## Case 1 — DeFi / AMM (Rust): the amplification ramp

`compute_amp_factor` returns the current amplification coefficient while the AMM
ramps between two values. It is the parameter that sets the price curve, so a
wrong value moves the pool's price. The original arithmetic is:

```rust
let amp_delta = (amp_range as u128).checked_mul(time_delta.to_u128()?)?…
self.initial_amp_factor.checked_add(amp_delta)
```

Two things in the original are outside KERN's subset: `checked_*` method calls
and the `u128` widening. So the **same arithmetic** was written as plain `i64`
to see whether the invariant holds without the widening:

```rust
// @kern:requires initial_amp >= 0 and target_amp >= initial_amp
// @kern:requires time_range > 0 and time_delta >= 0 and time_delta <= time_range
// @kern:ensures result >= initial_amp and result <= target_amp
pub fn amp_ramp_up_safe(initial_amp: i64, target_amp: i64, time_delta: i64, time_range: i64) -> i64 {
    return initial_amp + (target_amp - initial_amp) * time_delta / time_range;
}
```

KERN's verbatim output (`docs/evidence/high_stakes/kern_rust_amm_amp.log`):

```text
  [BV] amp_ramp_up_safe (стр. 10): теория битовых векторов (_ BitVec 64, знаковый)
  [FAIL] amp_ramp_up_safe: КОНТРАКТ НАРУШЕН
         KERN-EQ2 : F
         ВЕРДИКТ  : НЕ доказано (контрпример/таймаут)
         [КОНТРПРИМЕР] time_delta = #x1c00000000000001, initial_amp = #x1c00000000100000,
                       target_amp = #x6400000000100002, time_range = #x4000000000000000,
                       result = #x1c000000000fffff
ИТОГО: доказано 0 | T_advisory 0 | нарушено 2 (из них безопасность: 0) | НЕ РЕШЕНО 0 |
       ЛОЖНЫХ ТРЕВОГ 0 | ВАКУУМНЫХ 0 | вне подмножества 0 | всего 2
```

**Ground truth.** Every precondition holds in the witness, and a real compiler
rejects the operation (`docs/evidence/high_stakes/ground_truth_rust.log`):

```text
preconditions: initial>=0 true target>=initial true range>0 true delta>=0 true delta<=range true
thread 'main' panicked: attempt to multiply with overflow          (rc=101)

--- control: the same code with small values ---
result = 550
contract result >= initial_amp : held                                  (rc=0)
```

**What this means — and what it does not.** The counterexample is about the
**naive `i64` formulation**, not about Saber's code: upstream widens to `u128`
before multiplying, which is exactly what prevents this. So the honest reading
is: *KERN found, with a witness, why the `u128` widening in `compute_amp_factor`
is load-bearing* — remove it and the invariant `result >= initial_amp` breaks.
This is not a vulnerability report about `saber-hq/stable-swap`.

`--auto` (zero-annotation) mode over the same file reports nothing, because the
file carries contracts: the contract path takes precedence.

---

## Case 2 — Parser (C): the hex-digit nibble in cJSON

`parse_hex4` decodes `\uXXXX`. The original loops over four characters; the
loop is outside the extractor subset, the per-digit arithmetic is not. The
contract states the property the parser depends on: **a hex digit must map into
0..15** — anything else silently produces a corrupted code point.

```c
// @kern:requires c >= 48 and c <= 102
// @kern:ensures result >= 0 and result <= 15
int hex_digit(int c) {
    if (c >= 48 && c <= 57) return c - 48;
    if (c >= 65 && c <= 70) return c - 65 + 10;
    if (c >= 97 && c <= 102) return c - 97 + 10;
    return 0;
}
```

KERN's verbatim output (`docs/evidence/high_stakes/kern_c_hex_nibble.log`):

```text
  [PASS] hex_digit: ДОКАЗАНО
         [PROOF VERIFIED] steps: 227 | premises bound: 3/15 | mp: 17 |
         rewrite (linear): 39 | farkas: 15 | trusted: 7 | holes: 0
  [FAIL] hex_digit_unguarded: КОНТРАКТ НАРУШЕН
         [КОНТРПРИМЕР] c = 103, result = 55
         [RUNTIME CONFIRMED] контрпример перепроверен конкретным вычислителем тела
                             (модель совпала с исходником)
ИТОГО: доказано 1 | T_advisory 0 | нарушено 1 (из них безопасность: 0) | НЕ РЕШЕНО 0 |
       ЛОЖНЫХ ТРЕВОГ 0 | ВАКУУМНЫХ 0 | вне подмножества 0 | всего 2
```

So the guarded form is **proven over all 2^32 inputs of the contract domain**
(`trusted: 7` steps re-checked by the native proof checker, `holes: 0`), while
the form that falls through to `c - 48` is **refuted with a concrete input**.

**Ground truth.** `gcc -O0`, with KERN's exact witness
(`docs/evidence/high_stakes/ground_truth_c.log`):

```text
cJSON hex_digit_unguarded(c=103 = 'g') -> result = 55
contract result <= 15 : VIOLATED                                        (rc=1)
```

`c = 103` is the character `g`. The fall-through branch returns `103 - 48 = 55`,
which is not a nibble: the caller would shift it into a code point and produce a
character that was never in the input. The guarded form returns `0` and the
contract holds.

**Honest scope.** The loop over the four characters and the caller that
assembles `(h << 4) + digit` were **not** checked — loops are outside the
extractor subset. Only the per-digit obligation is proven; the assembly step is
not covered by this case.

---

## Case 3 — Money in integer cents (Python)

TheAlgorithms/Python `financial/` module keeps money in `float`. Float money is
a defect class of its own, so this case uses the **same standard patterns**
(`price_plus_tax`, progressive discount, pro-rata split) in **integer cents**,
where the arithmetic is exact and checkable. This is a modelled case, not an
extraction — and it is labelled as such.

```python
# @kern:requires base >= 0
# @kern:ensures result >= 0 and result <= base
def tax_15_percent(base: int) -> int:
    return base * 15 // 100

# @kern:requires total >= 0 and people >= 0
# @kern:ensures result >= 0
def split_bill_unguarded(total: int, people: int) -> int:
    return total // people

# @kern:requires total >= 0 and people > 0
# @kern:ensures result >= 0
def split_bill_guarded(total: int, people: int) -> int:
    return total // people
```

KERN's verbatim output (`docs/evidence/high_stakes/kern_py_money.log`):

```text
  [PASS] tax_15_percent: ДОКАЗАНО
         [PROOF VERIFIED] steps: 41 | premises bound: 3/4 | mp: 8 |
         rewrite (linear): 9 | farkas: 0 | trusted: 4 | holes: 0
  [FAIL] split_bill_unguarded: ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ (делитель: people)
         [КОНТРПРИМЕР] total = 0, people = 0
  [PASS] split_bill_guarded: ДОКАЗАНО
         [PROOF VERIFIED] steps: 54 | premises bound: 4/5 | mp: 9 |
         rewrite (linear): 6 | farkas: 0 | trusted: 3 | holes: 0
ИТОГО: доказано 2 | T_advisory 0 | нарушено 1 (из них безопасность: 1) | НЕ РЕШЕНО 0 |
       ЛОЖНЫХ ТРЕВОГ 0 | ВАКУУМНЫХ 0 | вне подмножества 0 | всего 3
```

**Ground truth.** The witness executed in a live interpreter:

```text
>>> split_bill_unguarded(0, 0)
ZeroDivisionError: division by zero
```

Note the counter-classification: the unguarded split is reported as
**`безопасность: 1`** (a safety obligation), not as a business-logic violation —
the tool distinguishes "the money is computed wrong" from "the process dies".

---

## Summary

| Case | Function | Contract | Verdict | Witness | Confirmed by |
|:--|:--|:--|:--|:--|:--|
| 1 | `amp_ramp_up_safe` (i64 form) | `result >= initial_amp` | **REFUTED** | `time_delta=#x1c00000000000001 …` | `rustc -C overflow-checks=on` → panic, rc=101 |
| 2 | `hex_digit` | `0 <= result <= 15` | **PROVEN** (227 steps, holes 0) | — | — |
| 2 | `hex_digit_unguarded` | `0 <= result <= 15` | **REFUTED** | `c = 103` → `55` | `gcc -O0` → VIOLATED, rc=1 |
| 3 | `tax_15_percent` | `0 <= result <= base` | **PROVEN** (41 steps, holes 0) | — | — |
| 3 | `split_bill_unguarded` | `result >= 0` | **REFUTED** (safety) | `people = 0` | live `python3` → ZeroDivisionError |
| 3 | `split_bill_guarded` | `result >= 0` | **PROVEN** (54 steps, holes 0) | — | — |

Three proven obligations, three refuted with a concrete witness, and **every
refutation was reproduced by a real compiler or interpreter**. No false
accusation was produced.

## Honest limits

- **These are math cores, not whole files.** The Rust `checked_*` calls and the
  `u128` widening, the C `for` loop over four characters, and Python floats were
  all outside the extractor subset and are stated as such above.
- **A counterexample is a claim about the model, not about the project.** For
  case 1 the refuted model is ours (the plain `i64` rewrite); upstream's `u128`
  code is not accused of anything. For case 2 the extracted per-digit logic is
  the original arithmetic, and the witness was reproduced by `gcc`.
- **Case 3 is modelled**, not extracted: the real module uses floats, and float
  money is itself a defect class.
- **`unsigned int` parameters are not accepted by the C extractor** (defect
  #312): the first version of case 2 was skipped with
  `SKIP — параметр c: 'unsigned int c'`, and the signature was changed to `int`
  for the check. This is a coverage limitation, recorded rather than hidden.
- **Nonlinear arithmetic is skipped**, not approximated: the first version of
  case 3 used `base * rate` (multiplication by a variable) and KERN answered
  `SKIP — нелинейное умножение`. A literal rate is used instead.
