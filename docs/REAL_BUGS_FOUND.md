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

## Case D — `tigerbeetle/tigerbeetle` @ `68958eb7`: a real ORDERING defect in a test (`#529`/T4c)

Found 2026-11-08 by the blind full-corpus exam (942 files, precision 35/35 = 1.00) and kept after
line-by-line triage. This case is different from A–C: it is not a crash in shipped code and not a
historical bug — it is a live ordering defect in the upstream test file at the pinned commit.

`src/clients/python/tests/test_conformance.py`:

```python
6168    transfers_1 = client.lookup_transfers([transfer_2_id])
6169    transfer_lookup_1 = transfers_1[0]              # <- USE
6170    assert len(transfers_1) == 1                    # <- GUARD for the line above
```

`lookup_transfers` returns whatever the server answered. On an **empty** answer, line 6169 raises
`IndexError: list index out of range`, and the assertion that would have explained the situation
(«exactly one transfer expected») never runs. The failure is reported as a harness index error
instead of the authors' own assertion.

**KERN (no contract, no annotation in the source):**

```
$ python3 tools/kern_contracts.py --xray <tigerbeetle>/src
  src/clients/python/tests/test_conformance.py: [BOUNDS PATH]
    test_two_phase_transfer_creates_posts_voids_and_expires_two_phase_transfers:
    `transfers_1[0]` (строка 6169) — возможен выход за границы
```

**Patch (2 lines, ready upstream):**

```diff
--- a/src/clients/python/tests/test_conformance.py
+++ b/src/clients/python/tests/test_conformance.py
@@ -6168,8 +6168,8 @@ def test_two_phase_transfer_creates_posts_voids_and_expires_two_phase_transfers(
     transfers_1 = client.lookup_transfers([transfer_2_id])
-    transfer_lookup_1 = transfers_1[0]
     assert len(transfers_1) == 1
+    transfer_lookup_1 = transfers_1[0]
     assert transfers_1[0].id == transfer_2_id
```

After the patch the same input (`[]`) yields `AssertionError` with the count, not `IndexError`.
Receipt: `docs/evidence/blind_p1_2026-11-07.log`, section `T4c`.

**Honest framing:** this is a defect of TEST diagnostics, not of the shipped server: the suite still
fails on a wrong answer, but with a message that hides the cause. Recorded here because the whole
point of the blind exam is that a stranger's code is judged by its own text, not by its reputation.

## Case E — `isamert/scheme.rs` @ `238b817b7f`: `derive(PartialOrd)` on a fraction (`#4`)

`src/utils/fraction.rs`:

```rust
#[derive(Debug, PartialOrd, PartialEq, Clone, Copy)]
pub struct Fraction { pub n: i64, pub d: i64 }
```

The derived `PartialOrd` compares `n` and then `d` — the order of the **fields**, not of the
**numbers**. `Fraction { n: 1, d: 3 } > Fraction { n: 1, d: 2 }` by fields, while `1/3 < 1/2`.

Reachable from user input: `src/lexer.rs:36` compares two `Token::Fraction` values with
`partial_cmp`, and `src/parser.rs:32` delegates S-expression comparison to `Token::partial_cmp`.
So `(< 1/3 1/2)` evaluates to `#f` where Scheme says `#t`.

Receipt: `rustc -O` on the isolated type prints `Greater`; `fractions.Fraction` says `1/3 < 1/2`.
Upstream: [#4](https://github.com/isamert/scheme.rs/issues/4).

**Honest framing:** the crate does not build on current stable rustc (162 errors, e.g.
"trailing semicolon in macro used in expression position"), so the interpreter itself could not be
run; the report says so explicitly and rests on the call path above plus the isolated reproducer.

## Case F — `kiesraad/abacus` @ `58c5f124b1`: `u64` overflow in a public `Fraction` (`#4393`)

`backend/apportionment/src/fraction.rs` implements `Add`/`Ord`/`Eq` with raw `u64` products and no
`gcd` reduction. In `--release` (overflow checks off):

```rust
Fraction::new(1, 5_000_000_000) + Fraction::new(1, 5_000_000_000)
// -> 10000000000 / 6553255926290448384   (expected 1/2500000000)
```

`25e18 − 2^64 = 6_553_255_926_290_448_384`: one wrap. `Ord` breaks **asymmetrically**, without any
prior overflow — `Fraction::new(5_000_000_000, 1).cmp(&Fraction::new(10^19, 5_000_000_000))`
returns `Less`, while `5e9 > 2e9`.

Upstream: [#4393](https://github.com/kiesraad/abacus/issues/4393) — **closed by the maintainer as a duplicate of their own #3179**, with thanks for the report. The defect is therefore confirmed, but it is an independent rediscovery, not a new finding: it was found from scratch, without knowledge of their backlog.

**Honest framing:** the report is **preventive**. `Fraction` is not yet constructed in the active
seat-allocation paths (`list_averages` / `max_remainder` are declared but not filled), so no
election result is affected today. The claim is about the public API contract, nothing more.

## Case G — `mahmoud/boltons` @ `d31d821d56c8`: wrong exception type (`#800`)

`IndexedSet().pop()` with no argument walks the inner list and lets `IndexError: pop from empty
list` escape, while `MutableSet.pop()` promises `KeyError`. Callers writing `except KeyError`
silently miss it.

Upstream: [#800](https://github.com/mahmoud/boltons/issues/800).

## Case H — `ad-si/Woxi` @ `c42f615822`: `Rational` derives `Ord` (BigInt, `#2704`)

`crates/woxi-reduce/src/exact.rs:12`:

```rust
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Rational {
  pub numerator: BigInt,
  pub denominator: BigInt,
}
```

Same defect class as Case E, but here `BigInt` removes any overflow explanation — the only
cause is the derive itself. Reachability was proved by **removing the traits and letting rustc
answer**, not by grepping:

```
$ cargo check --workspace --tests        # `PartialOrd, Ord` stripped from the derive
error[E0277]: the trait bound `Rational: Ord` is not satisfied
  --> crates/woxi-reduce/src/affine.rs:36:3   | pub constant: Rational,
  --> crates/woxi-reduce/src/affine.rs:37:3   | pub coefficients: BTreeMap<Variable, Rational>,
error[E0599] --> crates/woxi-reduce/src/presburger.rs:353:16
```

So `AffineTerm` (a linear form) derives `Ord`, which delegates to the lexicographic comparison,
and the Presburger residue grouping keys on `(BigInt, BTreeMap<Variable, Rational>)`.

**Honest framing:** `PartialEq` is derived the same way and `new()` reduces, so `Eq`/`Ord` agree
and `BTreeMap` invariants hold — no wrong answer or panic was observed. The claim is only that
where numeric order of coefficients matters, field order is returned instead.

Upstream: [#2704](https://github.com/ad-si/Woxi/issues/2704).

## Case I — `boa-dev/boa` @ `502206e50e`-era clone: `Eq`/`Hash` disagree on `-0.0` (`#5678`)

`core/engine/src/value/hash.rs` implements `PartialEq` for the public `JsValue` via
`SameValueZero` (so `+0.0 == -0.0`) plus `impl Eq`, and implements `Hash` by hashing
`f64::to_bits()` — where the two zeros differ (`0x0000…` vs `0x8000…`). Inserting a key
and looking it back up therefore fails.

Confirmed against `boa_engine v0.22.0` with a unit test in `core/engine/src/value/tests.rs`:

```rust
let a = JsValue::new(0.0_f64);
let b = JsValue::new(-0.0_f64);
let mut set = HashSet::new();
set.insert(a.clone());
assert_eq!(a, b);                                      // passes
assert!(set.contains(&b), "Eq/Hash contract broken");  // FAILS
```

```text
thread 'value::tests::kern_eq_hash_minus_zero' panicked: Eq/Hash contract broken
test result: FAILED. 0 passed; 1 failed
```

The same split exists across variants: `Integer32(0)` hashes as `0.0f64`, `Float64(-0.0)`
as `0x8000…`, and they compare equal.

**Honest framing:** this is *not* a NaN claim — `tag_f64` in `value/inner/nan_boxed.rs`
canonicalises every NaN at construction, so NaN payloads cannot differ inside a `JsValue`.
Only the sign of zero escapes. The trait impls are public API of a published crate
(`boa_engine`), which is what makes this reportable even though the engine itself does not
yet key any map by `JsValue`.

Upstream: [#5678](https://github.com/boa-dev/boa/issues/5678). Class now detected statically by
`law_hunter.py --rust` as **eq-hash-mismatch** (subtype A: `to_bits()` hash with numeric `eq`).

## Case J — `swc-project/swc` @ `49c4bb202b`: `Number` derives `Eq` but encodes the sign of zero in `Hash` (`#12815`)

`crates/swc_css_ast/src/value.rs`:

```rust
#[ast_node("Number")]
pub struct Number { pub span: Span, pub value: f64, pub raw: Option<Atom> }
implement Eq for Number {}

#[allow(clippy::derived_hash_with_manual_eq)]
impl Hash for Number {
    fn hash<H: Hasher>(&self, state: &mut H) {
        fn integer_decode(val: f64) -> (u64, i16, i8) {
            let bits: u64 = f64::to_bits(val);
            let sign: i8 = if bits >> 63 == 0 { 1 } else { -1 };
            /* ... mantissa, exponent ... */
            (mantissa, exponent, sign)
        }
        self.span.hash(state);
        integer_decode(self.value).hash(state);
    }
}
```

`0.0` decodes to `(0, 0, +1)`, `-0.0` to `(0, 0, -1)`: equal values, different hashes. `raw`
is not hashed at all, so `None` does not save the contract, and minifiers synthesise numbers
with `raw: None` and `DUMMY_SP`.

Confirmed with `cargo test -p swc_css_ast`:

```text
thread 'value::kern_eq_hash_test::number_eq_hash_minus_zero' panicked at
crates/swc_css_ast/src/value.rs:611:9: Eq/Hash contract broken on -0.0
test result: FAILED. 0 passed; 1 failed
```

**Honest framing:** `swc_ecma_ast::Number` documents the opposite (correct) behaviour — its
`PartialEq` distinguishes `+0` and `-0` — so the JS side of the same repository already
handles this; only the CSS crate does not. The report says so, which is what makes it a
consistency argument rather than a matter of taste.

Upstream: [#12815](https://github.com/swc-project/swc/issues/12815) — **closed by the maintainer as not planned, citing `AGENTS.md`**. Their `AGENTS.md` routes bugs found by static analysis to a separate tracker (`swc-project/swc-ai-issues`) and says explicitly not to file them in `swc-project/swc`; the report was reproduced by `cargo test -p swc_css_ast`, but it was filed in the wrong tracker. Recorded here as reproduced-but-not-accepted, not as an accepted fix.

## Case K — `surrealdb/surrealdb` (28k ★): `Value` claims `Eq`, `Geometry` hashes bits (`#7715`)

`Value` derives `Hash` and `PartialEq` and declares `impl Eq for Value {}`
(`surrealdb/types/src/value/mod.rs:87`, `:140`). The `Geometry` variant resolves those
two derives to different implementations: `derive(Hash)` calls the hand-written
`impl hash::Hash for Geometry` which hashes `p.x().to_bits()`, while `derive(PartialEq)`
calls the derived `PartialEq for Geometry`, which compares `geo_types::Point<f64>`
numerically. So `Point(0.0, 0.0)` equals `Point(-0.0, -0.0)` and hashes differently.

Confirmed live with `cargo test -p surrealdb-types`:

```text
thread 'value::kern_test::kern_geometry_eq_hash' panicked at value/mod.rs:1727:
Eq/Hash contract broken on Geometry(-0.0)
test result: FAILED. 0 passed; 1 failed
```

The report notes that `Number::hash` in the same crate already solves this with
`Canonical::of(*self)`, so the discipline exists and `Geometry` bypasses it.
Upstream: [#7715](https://github.com/surrealdb/surrealdb/issues/7715).

## Case L — `vectordotdev/vector` (19k ★): `MetricRef` is an `IndexMap` key (`#27277`)

`src/sinks/prometheus/exporter.rs` keeps metrics in
`IndexMap<MetricRef, (Metric, MetricMetadata)>` (`:239`) and looks them up with
`metrics.entry(MetricRef::from_metric(&normalized))` (`:630`). `MetricRef` implements
`PartialEq` numerically over `bounds: Option<Vec<f64>>` and declares `impl Eq`, but
`Hash` feeds each bound as `bound.to_bits()`. A histogram bound arriving as `-0.0`
and later as `0.0` therefore produces two entries, so the exporter emits the same
metric family twice in `/metrics`.

Confirmed live with `cargo test --lib --no-default-features --features sinks-prometheus`:

```text
thread '...metric_ref_eq_hash_minus_zero' panicked at exporter.rs:1986:
Eq/Hash contract broken on -0.0 bound
test result: FAILED. 0 passed; 1 failed; 580 filtered out
```

Upstream: [#27277](https://github.com/vectordotdev/vector/issues/27277).

## Case M — `lancedb/lance`: `HilbertUDF` hashes bbox bits (`#11344`)

`rust/lance-geo/src/rtree/sort/hilbert_sort.rs` compares `bbox.minx()`/`miny()`/
`maxx()`/`maxy()` numerically in `PartialEq`, declares `impl Eq`, and hashes the same
coordinates as `to_bits()`. `HilbertUDF` is a `ScalarUDFImpl`, and DataFusion requires
`Eq + Hash` for user-defined functions because the planner stores them in hash-based
structures (CSE, projection deduplication).

Confirmed live with `cargo test -p lance-geo --lib hilbert_udf_eq_hash_minus_zero`:

```text
thread 'rtree::sort::hilbert_sort::kern_eq_hash_test::hilbert_udf_eq_hash_minus_zero'
panicked at hilbert_sort.rs:349: Eq/Hash contract broken on -0.0 bbox
test result: FAILED. 0 passed; 1 failed; 97 filtered out
```

Upstream: [#11344](https://github.com/lance-format/lance/issues/11344).

## Case N — `databendlabs/databend` (9.5k ★): `DataValue` hashes floats by bits (`#21155`)

`DataValue` derives `PartialEq`, declares `impl Eq for DataValue {}`, and implements
`Hash` by hand with `DataValue::Float64(v) => v.to_bits().hash(state)`. So
`Float64(0.0)` and `Float64(-0.0)` compare equal and hash differently, which breaks
any hash-based grouping (GROUP BY keys, DISTINCT sets, hash joins).

Confirmed in a GitHub Actions runner (the local machine has no `clang`):

```text
thread 'data_value::kern_eq_hash_test::kern_eq_hash_minus_zero' panicked at
src/query/datavalues/src/data_value.rs:74:9: Eq/Hash contract broken on -0.0
test result: FAILED. 0 passed; 1 failed
```

The crate is still in the live build graph — `src/query/expression` and
`storages/common/table_meta` depend on `databend-common-datavalues`.
Upstream: [#21155](https://github.com/databendlabs/databend/issues/21155) — **triaged the same day and assigned to an engineer** (assignee `@SkyFan2002`), which is the first external acceptance of a report from this audit.

## Summary

| Case | Repository / commit | KERN verdict | Live proof |
|---|---|---|---|
| A | `boltons` `5eb6cc0` | **DIVERGED** + witness `k = -1, n = 0` | pre-fix guard accepts an invalid index |
| B | `boltons` `c1c25da` | **not checkable** (#307, variable exponent) | `Bits(4, 2)` accepted before the fix |
| C | QuixBugs `gcd` | **DIVERGED** (crash) | `RecursionError` on `gcd(1, 2)` |
| D | `tigerbeetle` `68958eb7` | **BOUNDS PATH** (index before its guard) | `[]` → `IndexError` instead of the authors' `assert` |
| E | `isamert/scheme.rs` `238b817b7f` | **DIVERGED** (order, not value) | `1/3 > 1/2` from `derive(PartialOrd)`; `#4` |
| F | `kiesraad/abacus` `58c5f124b1` | **DIVERGED** in `--release` (preventive) | `1/5e9 + 1/5e9` → `10000000000/6553255926290448384`; `#4393` (dup of #3179, confirmed) |
| G | `boltons` `d31d821d56c8` | **CONTRACT** (wrong exception class) | `IndexedSet().pop()` → `IndexError`, not `KeyError`; `#800` |
| J | `swc-project/swc` `49c4bb202b` (31k ★) | **EQ/HASH SPLIT** on `-0.0` | `(0,0,+1)` vs `(0,0,-1)` in `integer_decode`; `cargo test -p swc_css_ast`; `#12815` (closed: AGENTS.md routing) |
| N | `databend` `77137bc2ad` (9.5k ★) | **EQ/HASH SPLIT** on `Float64(-0.0)` | `cargo test -p databend-common-datavalues` → FAILED (cloud); `#21155` |
| M | `lance` `e03f5e2f9d` | **EQ/HASH SPLIT** on `-0.0` bbox | `cargo test -p lance-geo` → FAILED; `#11344` |
| L | `vector` (19k ★) | **EQ/HASH SPLIT** in an `IndexMap` key | `MetricRef` bounds: `cargo test` → FAILED; `#27277` |
| K | `surrealdb` (28k ★) | **EQ/HASH SPLIT** on `Value::Geometry` | `cargo test -p surrealdb-types` → FAILED; `#7715` |
| I | `boa-dev/boa` (5.8k ★) | **EQ/HASH SPLIT** on `-0.0` | `JsValue::new(0.0) == JsValue::new(-0.0)`, `HashSet::contains` → `false`; `cargo test -p boa_engine`; `#5678` |
| H | `ad-si/Woxi` `c42f615822` | **ORD derives** (proved by rustc) | `Rational{numerator: BigInt, …}` lexicographic; `E0277` at `affine.rs:36,37`, `E0599` at `presburger.rs:353`; `#2704` |

Honest framing: three of the four are detected by KERN, one is outside the subset and is named as
such. None of them is a new CVE — these are **real** defects (historical in A–C, live in D), and the
value of the exercise is that KERN finds them from the code alone.
