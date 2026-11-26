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

## Bugs found in KERN itself during hunting

Every one of these was found because the report disagreed with the artifact:

| Bug | What was wrong | Consequence |
|---|---|---|
| `#657` | the histogram cut its tail | 64 of 103 skip reasons were invisible |
| `#661` | the skip reason named the wrong stage | the note pointed at a decoder instead of the recogniser |
| `#663` | the proof-category sum did not equal the step count | the centrepiece number was arithmetically wrong |
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
