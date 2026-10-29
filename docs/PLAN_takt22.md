# PLAN: Tack 2.2 — honest coverage funnel and targeted `--xray` widening

> **Status: step 1 DONE (R4 added + ranges corrected), steps 2–7 NOT STARTED.**
> **Base slice of this tack: `d98953c`** — the commit that introduced this plan. It
> is NOT "current `HEAD`", and it must not be chased: a SHA written in prose goes
> stale in the very commit that adds it. `git log -1` is the authority.
> §0 was RE-MEASURED at that slice (`docs/METRICS.md` §170 / §148) and three
> numbers were corrected; the corrections are marked below.
>
> **Read first, in this order:** `docs/STATUS.md` (generated state) →
> `docs/NEXT_SESSION.md` (handoff) → **this file** (the work) →
> `docs/CAPABILITY_MATRIX.md` (what is proven and what each proof does NOT show).

> **Facts (EN/RU, kept in sync by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->480 · CHECK <!-- fact:check_targets -->182 · cases <!-- fact:canfail_cases -->222 · anchors <!-- fact:anchors -->183 · registry <!-- fact:registry_targets -->238 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff

---

## §0. Base: what is measured (not assumed)

Both corpora are pinned by SHA and cloned into `~/.cache/kern/repos/`, so
"before/after" is measured on identical bytes.

| Corpus | SHA | Checked | Findings | Skip reasons |
|:--|:--|--:|--:|:--|
| `cmark-gfm/src` | `27d942c8` | **76 / 308** | 0 | no `if` **126** · syntax **53** · `nil/null` **49** · binary op **4** · no reason **0** |
| `toolkit/packages` | `0c3a9c33` | **58 / 458** | 0 | no `if` **337** · syntax **54** · ternary **6** · `nil/null` **3** · no reason **0** |

**CORRECTED at `d98953c`** (this table said 124/2 and 336/1; sums 232 and 400 and
the checked counts were right, the attribution of three functions was not). The
"no reason" bucket measures **empty** on both corpora, in four runs out of four —
see §1.3.

**The number that matters.** Functions **with branches**: C **182** (checked 76 =
42 %), TS **121** (checked 58 = 48 %). The "no `if`" bucket is **not** a parser
failure — see §1.2.

**Denominators, derived by ARITHMETIC from the counts above** (each skipped
function is counted exactly once, so the derivation is exact — but it is a
derivation, not a separate measurement):

| Corpus | total | no `if` | WITH branches | checked | skipped WITH branches |
|:--|--:|--:|--:|--:|:--|
| `cmark-gfm/src` | 308 | 126 | **182** | 76 = **41.8 %** | 106 = syntax 53 + `nil/null` 49 + binary 4 + no reason 0 |
| `toolkit/packages` | 458 | 337 | **121** | 58 = **47.9 %** | 63 = syntax 54 + ternary 6 + `nil/null` 3 + no reason 0 |

**Z3 is REQUIRED for every run below.** Without `.venv/bin` in `PATH` the x-ray
prints `findings 0` and no warning at all (defect #407). Reproduce the histogram:

```bash
PATH="$PWD/.venv/bin:$PATH" python3 tools/kern_contracts.py --xray ~/.cache/kern/repos/cmark-gfm/src | tail -8
```

---

## §1. Four answers, each measured — the starting point of this plan

### 1.1 `docs_map_check.py` has NO rule R4 — and #404 already recurred

The gate has R1 (every `docs/*.md` is mentioned or exempt), R2 (every link
resolves), R3 (no `||` row splicing). **Nothing compares the `§N` ranges printed
in the map with the real maximum `## §…`.**

Measured at `d98953c`: the map says `§1–§167` while the real maximum is **§169**,
and `§1–§145` while the English mirror reaches **§147**. So #404 was closed for
exactly one commit and then recurred a **third** time — in the very commit that
recorded #406. **Step 1 closes this**: R4 compares every printed range with the real
maximum `## §…`, and the ranges are corrected in the same commit; the meta-test
carries a fourth sabotage (`§1–§1`) so the new rule is provably able to fail.

### 1.2 Functions WITHOUT `if` ARE checked for arithmetic — but are reported as `skipped` (defect #405)

Live run on `audits/codecheck` (**Z3 REQUIRED** — see §6 rule 8 and defect #407):

```bash
PATH="$PWD/.venv/bin:$PATH" python3 tools/kern_contracts.py --xray audits/codecheck | tail -8
```

```
[REPO SUMMARY] файлов 16 | функций проверено 7 / 16 (skipped 9) | находок 4
    skip: нет условий `if` в теле × 9
  audits/codecheck/c_unguarded.c: [CRASH PATH] ratio: возможно деление на ноль: b == 0
  audits/codecheck/rust_overflow.rs: [OVERFLOW PATH] add32: переполнение типа `i32` … [КОНТРПРИМЕР] b = 2147483647, a = 1
  audits/codecheck/rust_allman.rs: [OVERFLOW PATH] add32Allman: … [КОНТРПРИМЕР] b = 2147483647, a = 1
  audits/codecheck/zig_div.zig: [CRASH PATH] ratio: возможно деление на ноль: b == 0
```

**Without Z3 this command prints `находок 0` and not a single warning** — the four
findings above exist only with the solver present (#407: "the tool did not run" is
reported as "0 findings").

Both files, verbatim:

```c
int ratio(int a, int b) { return a / b; }          /* ZERO branches */
```
```rust
pub fn add32(a: i32, b: i32) -> i32 { a + b }      /* ZERO branches */
```

**Both produced findings and both were counted as `skipped`.** Cause, in the code
(`tools/kern_contracts.py:6809` and `:6814`): the obligation detectors
(`_clike_overflow_findings`, bounds, divisors) run **unconditionally**, but the
`checked` counter is incremented **only when `proven > 0`** — that is, only when
the body contains at least one **translatable** `if`.

**Consequence:** the funnel `76 / 308 (skipped 232)` is **understated**, and it
**hides the fact that the analysis ran**. This is defect **#405** (class
#320/#370): the report says something other than what happened.

Answer to the natural question "are we losing the most obvious bug class
(unprotected arithmetic)?": **no, we are not losing it.** What is lost is the
**truth about coverage**.

### 1.3 `no reason` is statically UNREACHABLE — and it MEASURES EMPTY today

All exits from the `for m in _ifs` loop (lines 6487–6505) are either
`skip_why.append(...)` or `proven += 1`; `skip_why` and `_ifs` are initialised
once per function (6433, 6486). Therefore `proven == 0 ∧ skip_why == [] ∧ _ifs ≠ []`
should be impossible.

**CORRECTED at `d98953c`.** The plan recorded this bucket as measured ×2 (C) and
×1 (TS). At `d98953c` it measures **0 on both corpora, in four runs out of four**
(with and without Z3), while the sums stay 232 and 400 — the three functions were
attributed to "no `if`" instead. So the bucket is not currently observable, and
step 3's acceptance would pass **vacuously**. Keep the dump as a CONDITIONAL tool:
print the function name, `len(_ifs)` and `skip_why` in the `else` branch IF the
bucket reappears (e.g. after the parser is touched in steps 4–6), and do not claim
step 3 as a fix while there is nothing to fix.

**Step 3 is therefore RE-SCOPED** onto the defect that IS measurable here: the
reason histogram mixes **functions** and **branches** — see §3, step 3.

### 1.4 "binary operator: 4" means BITWISE operators — and Int is the wrong theory

Measured in `cmark-gfm/src`: **21** conditions of the form
`if (options & CMARK_OPT_*)`, plus `|`, `^`, `~`. Four fired (for the rest, the
first failing reason is different).

🔴 **`& | ^ << >>` over unbounded `Int` is NOT the same as over `i32/u32`.**
`x & 1` is meaningless in an Int model. The project already has a **BV mode**
(`@kern:bitvec32`, `_needs_bitvec`) for exactly this reason. So the correct move is
**routing such conditions to the BV encoder**, never "adding them to `expr_smt`" —
otherwise we get a **false PROVEN**, the very class of #317/#349.

---

## §2. Three safety conditions, verified against the code (+ a fourth)

### 2.1 (Step 2) The new invariant — and the gate that WILL break

`tools/xray_skip_reasons_check.py` currently checks `named == skipped`,
`checked >= 1`, `skipped >= 2`. It parses `total` from the summary but **never uses
it** — so the proposed invariant

```
checked + trivial + skipped == total   AND   Σ skip_reasons == skipped
```

**closes an existing hole**, not just a new one.

**Fourth condition (found here, must not be missed).** The gate **will break** in
step 2 unless fixed in the same commit:

- its fixture contains `int plain(int n) { return 42; }` — after step 2 that
  becomes **`trivial`**, not `skipped`;
- if `bitwise` moves to BV-`checked`, `skipped` drops to **1** and the gate's
  threshold `skipped >= 2` fails.

So fixture **and** threshold change together with the code — otherwise we trade
one defect for another.

**The invariant now has an owner (sub-step 3.1, done).** The funnel identity
`checked + trivial + skipped == total` and the dimension rule `named <= skipped`
are no longer prose: they live in `tools/funnel_accounting.py` as `@kern:` contracts,
are PROVED by our own engine, sealed in `docs/contracts.lock.json`, and the gate
`tools/funnel_contract_check.py` (invoked from `tools/xray_check.sh`) requires the
weakened twins to be REFUTED — so the proof cannot be vacuous. No new CHECK target is
created: the sub-gate lives INSIDE `xray-check`, exactly like the #400 one.

### 2.2 (Step 4) The `UNSAT`/`SAT` asymmetry is correct — but a leak flag is required

The asymmetry is real:

- **`UNSAT`** (dead-branch / redundant-guard): encoding an unknown uppercase
  constant as a free `BitVec` symbol is **sound** — `UNSAT` means "unreachable for
  **every** value of the constant". It can only fire by congruence (e.g. `if (o & M)`
  and, inside it, `if (!(o & M))`), and never yields a false alarm.
- **`SAT`** (overflow counterexamples): a free constant lets Z3 pick
  `MAX_BUF = 2147483647` and report a **false overflow**.

The existing protection (docstring of `_clike_overflow_findings`) requires every
name **in the expression** to be a parameter or a typed local. It does **not**
cover the **path**: if a free symbol lands in `path_conds`, the overflow query
becomes `∃c. path(c) ∧ overflow` — weaker than reality → **false accusation**.

**Add to the plan:** a `free_syms_in_path` flag. When set, `UNSAT` checks still
run, but `SAT` checks (overflow, bounds, divisors) return **SKIP with a named
reason** (`путь зависит от неизвестной константы`), never a finding.

### 2.3 (Step 6) `nil/null` — the reset list is longer than two cases

Beyond `ptr = …` and `foo(&ptr)`, reset the accumulated constraint on:
`ptr++`, `ptr--`, `ptr += …`, and **any `&ptr` in a call** (including
`memcpy(&ptr, …)`). For TS/JS reset on **any call** taking the object: in JS the
object is passed by reference, so `foo(arr)` may change `arr.length` and the
`arr__length` symbol must be dropped.


---

## §3. The seven steps: acceptance and risk

| # | Step | Acceptance | Risk |
|:--|:--|:--|:--|
| **1** | ✅ **DONE** — **R4** in `docs_map_check.py`: compare the map's `§N` range with the real maximum `## §…` | sabotage `§1–§1` → red (4th meta-test diversion); ranges == fact (`§170` / `§148`) | low |
| **2** | **#405**: three buckets `checked` / `trivial` / `skipped`; `checked` counted by **detector execution**, not by translatable `if` count; update the gate invariant (including `total`) and its fixture in the same commit | on `audits/codecheck` `ratio` and `add32` land in **checked**; `Σ buckets == total`; `Σ reasons == skipped`; canfail case. **Run with Z3 in `PATH`** — without it there are no findings to move (#407) | medium |
| **3** | ✅ **DONE (sub-steps 3.1 + 3.2)** — the funnel specification is sealed (`tools/funnel_accounting.py` + gate invoked from `xray_check.sh` + lock, METRICS §149) AND the tool itself is WIRED to it (METRICS §150): Belnap gate `rc=2`, solver auto-pickup, units separated. **The old target ("dump `no reason`") was VACUOUS.** The `no reason` bucket measures **0 on both corpora** (4 runs), so "dump it" has nothing to dump. The real, MEASURED defect in the same place is a **unit mismatch in the reason histogram**: in the Python path `skipped` holds **BRANCH** messages (`kern_contracts.py:4857`, `:4865`) while the counter `skipped N` counts **FUNCTIONS** (`:7354`); the repo-level scraper (`:7604–7612`) pours both into ONE dict which is then compared with the function counter (`:5655–5657`) — hence the nonsense `-6`. Fix: (a) split `fn_skip_reasons` (must sum to `skipped N`) from `branch_skip_reasons` (informational, printed under its OWN label, never mixed); (b) never print a negative difference; (c) the `#407` safeguard — `--xray` refuses with `rc != 0` when Z3 is absent, and `run_kernc` auto-picks `.venv/bin` relative to `sys.executable` | `--xray audits/codecheck` prints **no negative line**, with AND without Z3; `Σ fn_reasons == skipped`; branch notes are labelled and counted separately. **The gate needs a NEW case**: its current fixture is C-like only and therefore passes even WITHOUT Z3 (measured) — the new case (a Python file with an undecided branch) is RED before the fix and green after | medium |
| **4** | **Bitwise via BV** + `free_syms_in_path`; `SAT` checks under the flag → SKIP with reason | `binary operator` → 0 on `cmark-gfm`; fixture: BV version correct while the **Int version proves a falsehood** (negative control) | **high** |
| **5** | Ternary `?:` → `(ite …)` | `ternary` → 0 in toolkit; control: a ternary in a C fixture yields the correct verdict | medium |
| **6** | `nil/null` (+49 C, +3 TS) with reset per §2.3 | 0 false alarms; control: reassignment does **not** carry the constraint | medium |
| **7** | **Mutation lock**: `canfail.py` writes `.git/CANFAIL_ACTIVE_MUTATION` (PID + file) and removes it in `finally`; gate `make mutation-lock-check` + `make hooks` (the hook itself is local, **not versioned**) | marker present → gate red; after a run the marker is gone | low |

**Order: 1 → 2 → 3 → 4 → 5 → 6 → 7.** Rationale: 1–3 produce **honest numbers**
before the parser is touched; 4 is the only place where a **false proof** is
possible, so it comes strictly after the funnel stops lying.

---

## §4. Boundaries that will NOT disappear

- "no `if`" in TS is **337 of 458**, and it is mostly **not a loss**: there is
  nothing for the x-ray to branch on, apart from arithmetic (which IS checked).
- After steps 4–6 the realistic target is C **~68 %** and TS **~55 %** of functions
  **with branches** (denominator corrected: C **182**, TS **121**) — not "95 % of
  everything". The target itself is an ESTIMATE; only the denominator is measured.
- The #400 gate checks the **link** between counter and reasons, not the quality of
  the reasons: "outside the subset" can remain an over-broad bucket.
- Do **not** promise `16/16` on `audits/codecheck` before step 2: at least 3–4 of
  the 9 skipped functions will become `checked` (they carry findings), but the exact
  split is only known after the change.
- **Z3 is a precondition, not a detail.** Every number in this plan is read through
  `--xray`, and without the solver that path reports zeros that look like "clean"
  (#407). A measurement taken without Z3 is not a measurement.

---

## §5. How to verify this plan's claims (all commands are read-only)

```bash
# 0. Z3 is present — otherwise every number below is a false zero (#407)
printf '(set-logic ALL)\n(declare-const x Int)\n(assert (= x 0))\n(check-sat)\n' \
  | zig-out/bin/kernc prove /dev/stdin     # must NOT print "z3 недоступен"

# 1.1 the map's §N ranges (now enforced by R4 inside docs_map_check.py)
grep -n '§1–§1' docs/README.md
grep -oE '^## §[0-9]+\.' docs/METRICS.md | grep -oE '[0-9]+' | sort -n | tail -1
make docs-map-check          # R4 + the 4th meta-test diversion

# 1.2 functions without `if` DO get checked, yet are counted as skipped (#405)
PATH="$PWD/.venv/bin:$PATH" python3 tools/kern_contracts.py --xray audits/codecheck \
  | grep -E 'REPO SUMMARY|skip:|CRASH PATH|OVERFLOW PATH'

# 1.3 the "no reason" bucket: statically impossible, and currently EMPTY
grep -n 'без названной причины' tools/kern_contracts.py
PATH="$PWD/.venv/bin:$PATH" python3 tools/kern_contracts.py --xray \
  ~/.cache/kern/repos/cmark-gfm/src | grep -c 'без названной'   # expect 0

# 1.4 bitwise conditions in the corpus
grep -hoE 'if \([A-Za-z_][A-Za-z0-9_]* *(&|\||\^|<<|>>) *[^)]*\)' \
  ~/.cache/kern/repos/cmark-gfm/src/*.c | wc -l
```

---

## §6. Working rules for this tack (each one paid for in practice)

1. **Never run a check in the same batch as an edit to what it checks.** This race
   produced a false `IndentationError`, stale reads, and once a `canfail` sabotage
   committed to `main` (`3067a1b` — the CI caught it).
2. **Never commit while `tools/canfail.py` runs** — it mutates tracked files
   (see step 7 for the permanent fix).
3. **Write large new files atomically** (`cat > file <<'EOF'`, or one editor call);
   a series of `insert_line` calls into a growing file split functions in half.
4. **A real Zig 0.17 must be first in `PATH`** — the pip `ziglang` 0.13 package
   breaks the build and the error blames OUR `build.zig` (#392).
5. **Any new file with `fact:` anchors must be in `SURFACES`** (`tools/sync_state.py`),
   otherwise the orphan guard (#246) refuses it — and it is right to.
6. **Every new CHECK target needs a non-vacuous canfail case and a `CASE_TARGET`
   entry** (the two-way invariant is enforced by `tools/registry.py`).
7. Contour per step: **test → code → canfail case → registry → sync → gates →
   commit → CI → push**.
8. **Z3 must be in `PATH` before any `--xray` run**: `PATH="$PWD/.venv/bin:$PATH"`.
   The solver is a Python module inside `.venv` (`z3 5.3.1`); `kernc` finds it via
   `PATH`, and without it `--xray` prints `findings 0` with **no warning at all** —
   "the tool did not run" reads as "clean" (#407). Same class as rule 4 (Zig), and it
   already produced a false zero while §0 was being re-measured.
9. **A self-check against your OWN retelling is vacuous.** The gate
   `funnel-contract_check.py` compares the tool's summary line with a sample — and the
   sample, retyped by hand, repeated the pattern's error (the doubled "У" in
   ВАКУУМНЫХ was read as one), so a PROVED specification was declared unproved. The
   sample must be the VERBATIM output, and the parser must be self-tested against
   that verbatim text. Cost of ignoring this: a false FAIL that looks like a real
   defect in the spec.

