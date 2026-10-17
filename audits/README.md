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

### 2. The same function, now straight from the `.zig` source (improvement #15)

The hand-written model above existed **because** the convenience extractor could not read
bitwise operators: `& | ^ ~ << >>` do not exist in `Int`, so `isAligned` was skipped. But
KERN's own core has always handled **QF_BV** — so the extractor was the bottleneck, not the
engine. It now detects bitwise operators (or the `@kern:bitvec32` / `@kern:bitvec64`
annotation), rebuilds the body in the theory of bit-vectors **with the same statement parser**
(so the same code is checked), and feeds it to the core:

| File | Function | Verdict |
|:--|:--|:--|
| `andrewrk-gpa/alignment_bitvec.zig` | `alignmentAgrees` — real `addr & ~(alignment - 1)` compared against `addr % alignment` | **PROVEN** (`(_ BitVec 32)`, signed) |
| `andrewrk-gpa/alignment_bitvec.zig` | `alignmentAgreesBuggy` — the `alignment - 2` variant | **REFUTED** — counterexample `addr = #xc0000001, alignment = #x40000000, result = #xc0000001` |

The counterexample is checkable by hand: `alignment = 0x40000000`, so `~(alignment-2) =
0xC0000001`, hence `addr & mask == addr` → the buggy branch returns `0xC0000001 % 0x40000000
= 1`, not the `0` the contract requires.

### 3. `tigerbeetle/tigerbeetle` (financial database)

`src/stdx/stdx.zig:67` — `div_ceil`, body at lines 83-85:

```zig
assert(denominator > 0);
if (numerator == 0) return 0;
return @divFloor(numerator - 1, denominator) + 1;
```

Modelled in `tigerbeetle/div_ceil.zig`. `@divFloor` is a builtin outside the extractor subset,
so the model writes it as `/` — for a non-negative numerator and positive denominator (which
the `requires` states) `@divFloor` and `/` coincide, so the model is faithful.

| Function | Claim | Verdict |
|:--|:--|:--|
| `divCeil` (real) | `result == (numerator + denominator - 1) / denominator` | **PROVEN** — `[PROOF VERIFIED]` 98 steps, `holes: 0`, `trusted: 15` (the proof checker re-checked Z3's certificate) |
| `divCeilBuggy` (control: `numerator / denominator + 1`) | same claim | **REFUTED** — a *safety* obligation fires first: `numerator = 2147483647, denominator = 1, result = 2147483648` overflows `i32`, `[RUNTIME CONFIRMED]` |

### 4. `ghostty-org/ghostty` (GPU terminal)

`src/renderer/size.zig:253` — `GridSize.update`, body:

```zig
const calc_cols: Unit = @intFromFloat(screen_width / cell_width);
self.columns = @max(1, calc_cols);
```

Modelled in `ghostty/grid_columns.zig`, with the modelling steps stated in the file:
`@max(1, x)` unfolded to `if (x < 1) return 1; return x;`, and the `f32` division replaced by
integer `/` (identical for non-negative values, and `requires` bounds the inputs by `2²⁴`, where
`f32` still represents integers exactly — the boundary is stated, not hidden). The property
specified is the invariant the code exists to guarantee: **the grid is never empty**.

| Function | Claim | Verdict |
|:--|:--|:--|
| `gridColumns` (real) | `result >= 1` | **SKIP — honest refusal**: Z3 proves it, but KERN's proof checker does not cover the certificate (`неверный шаг unit-resolution`). The gate refuses to claim "verified" rather than trusting the solver — see defect **#118** |
| `gridColumnsBuggy` (control: clamp removed) | `result >= 1` | **REFUTED** — counterexample `screen_width = 0, cell_width = 1, result = 0` (empty grid), `[RUNTIME CONFIRMED]` |

The control exists because a checker that cannot say **no** is worthless: each case above shows
the same setup refuting a broken variant.

## Honest scope of such an audit

* The model is **mine**, not theirs: I transcribed their expression, and I chose the
  precondition. A refutation would therefore mean *my contract* is violated — before calling
  anything a bug in someone else's code, the counterexample must be reproduced against their
  real build.
* This checks a **pure expression**, not the subsystem: no memory safety, no pointer
  arithmetic beyond the expression, no concurrency.
* Where the model had to translate a construct (a builtin, a float division), the translation
  is written down in the file and the domain in which it is exact is part of the `requires`.
* It is evidence about **one function per case**, presented as such — with the file, the line
  and the exact input, so anyone can re-run it:

```bash
./zig-out/bin/kernc prove audits/andrewrk-gpa/isAligned.smt2          # -> ДОКАЗАНО (e=1)
./zig-out/bin/kernc prove audits/andrewrk-gpa/isAligned_control.smt2  # -> контрпример (e=0)
python3 tools/kern_contracts.py audits/andrewrk-gpa/alignment_bitvec.zig
python3 tools/kern_contracts.py audits/tigerbeetle/div_ceil.zig
python3 tools/kern_contracts.py audits/ghostty/grid_columns.zig
```

## Known limitations found while doing this

* **#117** — feeding the extractor a Zig builtin (`@mod`, `@rem`) used to produce
  `SKIP — invalid syntax (<unknown>, line 1)`: a Python parser error leaking into a Zig
  diagnostic. Fixed: the reason now names the construct (`zig-выражение вне подмножества: ...`).
* **#118** — on the Ghostty `gridColumns` obligation the proof checker rejects a certificate
  that Z3 produced (`unit-resolution` step not covered). The verdict degrades to SKIP, i.e. the
  gate is conservative, never silently optimistic. Recorded in `docs/CAPABILITY_STATUS.md`.

