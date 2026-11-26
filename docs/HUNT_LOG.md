# Hunt log: what was checked, what was found, what closed as "not a bug"

Working record. It is deliberately separated from
[`formal/certification/KNOWN_LIMITATIONS.md`](../formal/certification/KNOWN_LIMITATIONS.md):
that document states the **limits of the verifier** and opens with an honest note, while
this one is a log of the **signal classes** tested against live code. Keeping them together
turned the former into 45 % diary and drove the reader past the limits.

Numbers live only in [`facts.json`](facts.json). Where a number is quoted below, it is a
snapshot date plus what it was measured on, not a claim about the current state.

## This is the signal, or it was noise

- **the project is live** — at least one commit in the last 12 months;
- **the defect is reachable** — from a call that the library exposes, not from a test helper;
- **the fix is one line** — otherwise the maintainer's cost exceeds the value;
- **the class is expressed as a formula** — `Eq` numeric with `Hash` bitwise,
  `derive(Ord)` over rational fields, `callable` passed into a comparison, `fetch_...` under
  `memoize`, `malloc(w*h*c)` in a 32-bit `int`, `partial_cmp().unwrap()` over a computed
  value;
- **the repository's policy permits a report** — checked before writing, not after.

## Classes explored

| Class | What it catches | Where it was closed |
|---|---|---|
| `eq-hash` | `Eq` by value, `Hash` by bits (`-0.0`, NaN) | **Zed → PR #67346 merged** |
| `eq-ord` | `derive(Ord)` over rationals → lexicographic order | **Woxi → fixed upstream `dd05bc2`** |
| `nan-sort` | `partial_cmp().unwrap()` over computed values | **fast_vector_similarity #2 → closed as completed**, the author fixed 7 entry points |
| `unchecked-len` | slicing without a length check, C strings | `ghdl` #3521 (open), `iio` PR #24 (13 sites, open) |
| `lru-effects` | a side effect under memoisation | tested, found not a bug |
| `callable-cmp` | a function compared with `>` / `<` | tested, found not a bug |
| `chain-type-confusion` | string built from the result of a chained call | tested, found not a bug (2026-11-24) |
| `genexpr-scope` | a generator expression capturing a mutated variable | tested, found not a bug |
| `py-forward-path` | `__path__` after a `NamespacePackage` merge | tested, found not a bug |
| `z3-alloc` | `malloc(w*h*c)` in a 32-bit `int` | 69 of 134 overflow-shaped sites recognised (51.5 %) |
| `utf8-nth` | indexing a UTF-8 string without checking the offset | `ghdl` #3521 |
| `alloc-size` | multiplication of sizes before allocation | Z3 allocation-form detector |

## What the hunt cost the harness

A class is only useful if the harness can **physically** call the code. Where the harness
cannot replay a finding, the finding is not counted. The verdict column in every nightly
run has three values, and `NOT_REPLAYABLE` does not become `CONFIRMED` just because it
looks alarming.

## External contracts (puzzle 55)

The hunt surfaced a second question besides "does it crash": **does the code do what its
reference implementation does?** Metamorphic contracts of puzzle 55 (commutativity,
monotonicity, invariance under concatenation) check behaviour against a reference rather
than against a written specification. Temporary parser departures are suppressed by pinning
the `GEARS_` settings; a contract whose right-hand side depends on a tree parameter is
rejected with a counterexample only if it fails for that specific tree — "proven" is not
what is being claimed there.

## Results

- **public reports: 24, false reports: 0**;
- **merged upstream: 3** (Zed #67346, Woxi `dd05bc2`, fast_vector_similarity #2);
- **open, no response yet:** `ghdl` #3521, `iio` PR #24;
- **blocked by CI approval:** TheAlgorithms/C #1595, #1596.

## 2026-11-26 — Rust laws: precision measured, one candidate reproduced, one report withheld

The nightly contour was rebuilt into a filter (three mandatory gates) and the shards moved
to Rust. Turning detectors on immediately produced a result about **the detectors**:

| Repository | Hits before reading | Hits after the `is_finite` fix |
|---|--:|--:|
| `fvs` | 4 | 4 |
| `vger` | 2 | 2 |
| `iced` | 3 | **0** |
| `nushell` | 2 (of 2011 files) | 2 (of 1594, `examples/` excluded) |

**The three `iced` hits were MY false positives, not their bugs.** `core/src/gradient.rs:70`
sorts by `partial_cmp(&offset).unwrap()`, and one line above stands
`if offset.is_finite() && (0.0..=1.0).contains(&offset)` — the guard makes `partial_cmp`
total, so no panic is possible. The detector did not know `is_finite`; now it does, and the
shape is pinned as a calibration case (`_FINITE`), so the same mistake cannot return
silently. `examples/`, `tests/`, `benches/` are excluded: a panic in an example is not a
public API contract.

**`vger/src/lib.rs:707` — mechanism proven, report withheld.** The code takes the index from
an iterator over **glyphs** and applies it to the **string**:

```rust
for (i, glyph) in self.layout.glyphs().iter().enumerate() {
    let c = text.chars().nth(i).unwrap();
```

The mechanism is proven by execution, not by reading — a dependency-free reproducer panics
exactly there:

```
glyph 0 -> 'é'
--- glyphs outnumber characters ---
thread 'main' panicked at main.rs:7:37: called `Option::unwrap()` on a `None` value   rc=101
```

What is **not** proven is reachability: nothing shows that `layout.glyphs()` can return more
glyphs than `text.chars().count()` in this renderer. Under the project's own rule ("the
defect must be reachable from a call the library exposes") a mechanism without reachability
is **not a report**, and sending it would be the 25th report we should not write.

**Rule learned, and it is the price of the Rust switch:** a C or Python finding goes through
`confirm_c` / `live_replay`, which physically invoke the code. Rust laws have no such step
yet — they match a shape. Until a reachability check exists, Rust hits are **candidates**,
and the nightly report must say "candidate", never "CONFIRMED".
**Closure of the `vger` candidate (same day): not a report, and not a bug either.**
`self.layout` is `fontdue::layout::Layout` (line 1: `use fontdue::layout::{…}`), and that
layout emits one glyph per character in order, so the index from `glyphs()` cannot exceed
`text.chars().count()`. The invariant was **not** verified in source — `fontdue` is absent
from the local crate registry — so the honest status is: *mechanism real, invariant believed
by documentation, candidate archived*. It is not sent, and the nightly contour must not call
it CONFIRMED.



## Bugs found in KERN itself during hunting

Every one of these was found because the report disagreed with the artifact:

| Bug | What was wrong | Consequence |
|---|---|---|
| `#657` | the histogram cut its tail | 64 of 103 skip reasons were invisible |
| `#661` | the skip reason named the wrong stage | the note pointed at a decoder instead of the recogniser |
| `#663` | the proof-category sum did not equal the step count | the centrepiece number was arithmetically wrong |
| `#522` | assignments **inside blocks that unconditionally exit** cancelled a valid path predicate | `lg/src/util/tsort.c::collapse` gave 3 false `[BOUNDS PATH]`: the guard `if (stack_curr <= 1) break;` yields `stack_curr > 1`, but `stack_curr--` from two later blocks that both `break` out silently dropped it. Fixed by masking the spans of exiting blocks (measured: fixture `1 → 0`, `tsort.c` `6 → 3`, `lg/src/util` `7 → 4`, `cmark-gfm` unchanged at 79 checked / 0 findings) |
| — | the wasm artifact lagged behind the code | the browser demo reported a verdict for the previous version |
| — | `except ImportError` silently disabled a detector | the guard did not verify the thing it declared |
| — | Russian prose in an English README | the limit was not readable by the audience it was written for |

**All six are the same class: the report disagreed with the fact.** Not one was a flaw in
the code analysis; each was a flaw in the account of the analysis. That is why the gates in
this repository check documents against artifacts before a push, and why
`make scorecard-check` is not optional.

## What has been decided not to hunt

- **defects that need a specific platform** — cannot be replayed by us, so the report would
  be unfalsifiable;
- **style and performance** — outside the class of proven answers;
- **findings without a one-line fix** — the maintainer will not take them, and an unmerged
  report is a cost;
- **repositories whose policy forbids machine-generated reports** — read first; three
  candidate repositories were dropped for this reason alone.

**Correction about `fvs` (owner's note, 2026-11-26).** The four `nan-sort` hits are
**historical, not current**: the cached clone is `5048c1a`, older than the upstream fix
`2ccb3a3` that put `has_non_finite` in front of seven functions. The blacklist rule did
exactly what it should — the repository is reported and silenced — and the hits only prove
the detector sees the pre-fix shape. No second issue is opened.

**Reachability stage for Rust exists now.** `tools/confirm_rust.py` builds a probe crate
depending on the target by path and runs it: `RUNTIME_CONFIRMED` (panic, rc=101),
`SURVIVED` (ran clean), `NOT_REPLAYABLE` (no Cargo.toml / build failed / no snippet).
Measured on a crate created inside the test: unguarded `partial_cmp().unwrap()` -> panic
reproduced; the same code behind `is_finite` -> `SURVIVED`. A `LAW_CANDIDATE` can therefore
become a proven crash — but only with a probe snippet, since the detector does not know the
public signature. Without one the honest answer stays `needs_probe`.
