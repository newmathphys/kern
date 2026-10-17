# Shadow-contract audits (third-party code, hand-modelled)

These are **not** automatic audits of other people's repositories — that is not possible with
the current tooling, and the numbers below show why. They are **hand-written SMT-LIB2 models
of real expressions taken from real projects**, checked by KERN's own core
(`kernc prove` → Z3 + the Zig proof checker).

## Why "just run KERN on a popular repo" produces nothing

Measured, not assumed:

| Target | Result |
|:--|:--|
| `psf/requests`, `python-humanize/humanize`, `pallets/flask` — every `.py` file | **0** `@kern:` annotations found, **0** contracts verified |
| The same three projects — functions inside KERN's extractor subset (`int`-annotated params, only `+ - * / // %`, `if/else`, no calls/loops) | **0 of 715** (93 % excluded already by `non-int params`) |
| `andrewrk/zig-general-purpose-allocator`, `andrewrk/poop`, `andrewrk/mime`, `andrewrk/zasm` — Zig functions in subset | **0** (bitwise ops, loops, builtins, non-int types) |

KERN verifies **contracts**, not code in general. With no contracts in the target and a
narrow convenience-extractor subset, a 50-repository matrix would publish a table of zeros —
or worse, would present *our* injected contracts as findings about *their* code.

## What does work: model the expression by hand

`andrewrk/zig-general-purpose-allocator`, `gpda.zig:1065`:

```zig
fn isAligned(addr: usize, alignment: usize) bool {
    const aligned_addr = (addr & ~(alignment - 1));
    return aligned_addr == addr;
}
```

Modelled bit-for-bit in `andrewrk-gpa/isAligned.smt2` (same operators, 32-bit width,
precondition "alignment is a non-zero power of two") with the claim

```
(addr & ~(alignment-1)) == addr   ⇔   addr % alignment == 0
```

| File | Claim | Verdict |
|:--|:--|:--|
| `andrewrk-gpa/isAligned.smt2` | the real expression is equivalent to `addr % alignment == 0` | **PROVEN** — `KERN-EQ2 : T`, `e : 1` (all 2³² values of `addr`, every power-of-two alignment) |
| `andrewrk-gpa/isAligned_control.smt2` | the same with the classic off-by-one (`alignment-2`) | **REFUTED** — `KERN-EQ2 : F`, `e : 0`, counterexample `addr = #x40000000, alignment = #x00000001` |

The control exists because a checker that cannot say **no** is worthless: it shows the same
setup refutes a broken variant.

## Honest scope of such an audit

* The model is **mine**, not theirs: I transcribed their expression, and I chose the
  precondition. A refutation would therefore mean *my contract* is violated — before calling
  anything a bug in someone else's code, the counterexample must be reproduced against their
  real build.
* This checks a **pure expression**, not the allocator: no memory safety, no pointer
  arithmetic beyond the expression, no concurrency.
* It is evidence about **one function**, and it is presented as such — with the file, the
  line and the exact SMT used, so anyone can re-run it:

```bash
./zig-out/bin/kernc prove audits/andrewrk-gpa/isAligned.smt2          # -> ДОКАЗАНО (e=1)
./zig-out/bin/kernc prove audits/andrewrk-gpa/isAligned_control.smt2  # -> контрпример (e=0)
```

## Known limitation found while doing this

Feeding KERN's **convenience extractor** a Zig builtin (`@mod`, `@rem`) produces
`SKIP — invalid syntax (<unknown>, line 1)` — a Python parser error leaking into a Zig
diagnostic instead of a clear "this construct is outside the subset". Bitwise operators do
report correctly (`SKIP — бинарный оператор (только + - * / // %)`). Recorded as defect
**#117** in `docs/CAPABILITY_STATUS.md`.
