# PLAN: Tack 2.2 — honest coverage funnel and targeted `--xray` widening

> **Status: NOT STARTED.** Base commit: `08eb5cd`. This document is written so a
> NEW session resumes from measured facts, not from a summary.
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
| `cmark-gfm/src` | `27d942c8` | **76 / 308** | 0 | no `if` **124** · syntax **53** · `nil/null` **49** · binary op **4** · no reason **2** |
| `toolkit/packages` | `0c3a9c33` | **58 / 458** | 0 | no `if` **336** · syntax **54** · ternary **6** · `nil/null` **3** · no reason **1** |

**The number that matters.** Functions **with branches**: C **184** (checked 76 =
41 %), TS **122** (checked 58 = 48 %). The "no `if`" bucket is **not** a parser
failure — see §1.2.

Reproduce the histogram:

```bash
python3 tools/kern_contracts.py --xray ~/.cache/kern/repos/cmark-gfm/src | tail -8
```

---

## §1. Four answers, each measured — the starting point of this plan

### 1.1 `docs_map_check.py` has NO rule R4 — and #404 already recurred

The gate has R1 (every `docs/*.md` is mentioned or exempt), R2 (every link
resolves), R3 (no `||` row splicing). **Nothing compares the `§N` ranges printed
in the map with the real maximum `## §…`.**

Measured at `08eb5cd`: the map says `§1–§167` while the real maximum is **§168**,
and `§1–§145` while the English mirror reaches **§146**. So #404 was closed for
exactly one commit.

### 1.2 Functions WITHOUT `if` ARE checked for arithmetic — but are reported as `skipped` (defect #405)

Live run on `audits/codecheck`:

```
[REPO SUMMARY] файлов 16 | функций проверено 7 / 16 (skipped 9) | находок 4
    skip: нет условий `if` в теле × 9
  audits/codecheck/c_unguarded.c: [CRASH PATH] ratio: возможно деление на ноль: b == 0
  audits/codecheck/rust_overflow.rs: [OVERFLOW PATH] add32: переполнение типа `i32` … [КОНТРПРИМЕР] b = 2147483647, a = 1
```

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

### 1.3 `no reason` (×2) is statically UNREACHABLE — needs a dump, not a guess

All exits from the `for m in _ifs` loop (lines 6487–6505) are either
`skip_why.append(...)` or `proven += 1`; `skip_why` and `_ifs` are initialised
once per function (6433, 6486). Therefore `proven == 0 ∧ skip_why == [] ∧ _ifs ≠ []`
should be impossible — yet it is **measured** (×2). So there is a path not yet
seen. Do **not** guess: print the function name, `len(_ifs)` and `skip_why` in the
`else` branch, run once over `cmark-gfm/src`, and close the path (or remove the
unreachable branch).

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
| **1** | **R4** in `docs_map_check.py`: compare the map's `§N` range with the real maximum `## §…` | sabotage `§1–§1` → red; ranges == fact | low |
| **2** | **#405**: three buckets `checked` / `trivial` / `skipped`; `checked` counted by **detector execution**, not by translatable `if` count; update the gate invariant (including `total`) and its fixture in the same commit | on `audits/codecheck` `ratio` and `add32` land in **checked**; `Σ buckets == total`; `Σ reasons == skipped`; canfail case | medium |
| **3** | **Dump `no reason`**: temporary `print` (name, `len(_ifs)`, `skip_why`) → one run → find both functions; then close the path or delete the unreachable branch | `no reason: 0` on both corpora | low |
| **4** | **Bitwise via BV** + `free_syms_in_path`; `SAT` checks under the flag → SKIP with reason | `binary operator` → 0 on `cmark-gfm`; fixture: BV version correct while the **Int version proves a falsehood** (negative control) | **high** |
| **5** | Ternary `?:` → `(ite …)` | `ternary` → 0 in toolkit; control: a ternary in a C fixture yields the correct verdict | medium |
| **6** | `nil/null` (+49 C, +3 TS) with reset per §2.3 | 0 false alarms; control: reassignment does **not** carry the constraint | medium |
| **7** | **Mutation lock**: `canfail.py` writes `.git/CANFAIL_ACTIVE_MUTATION` (PID + file) and removes it in `finally`; gate `make mutation-lock-check` + `make hooks` (the hook itself is local, **not versioned**) | marker present → gate red; after a run the marker is gone | low |

**Order: 1 → 2 → 3 → 4 → 5 → 6 → 7.** Rationale: 1–3 produce **honest numbers**
before the parser is touched; 4 is the only place where a **false proof** is
possible, so it comes strictly after the funnel stops lying.

---

## §4. Boundaries that will NOT disappear

- "no `if`" in TS is **336 of 458**, and it is mostly **not a loss**: there is
  nothing for the x-ray to branch on, apart from arithmetic (which IS checked).
- After steps 4–6 the realistic target is C **~68 %** and TS **~55 %** of functions
  **with branches** — not "95 % of everything".
- The #400 gate checks the **link** between counter and reasons, not the quality of
  the reasons: "outside the subset" can remain an over-broad bucket.
- Do **not** promise `16/16` on `audits/codecheck` before step 2: at least 3–4 of
  the 9 skipped functions will become `checked` (they carry findings), but the exact
  split is only known after the change.

---

## §5. How to verify this plan's claims (all commands are read-only)

```bash
# 1.1 the map's §N ranges are stale (R4 missing)
grep -n '§1–§1' docs/README.md
grep -oE '^## §[0-9]+\.' docs/METRICS.md | grep -oE '[0-9]+' | sort -n | tail -1

# 1.2 functions without `if` DO get checked, yet are counted as skipped (#405)
python3 tools/kern_contracts.py --xray audits/codecheck | tail -6

# 1.3 the "no reason" bucket is reachable but statically impossible
grep -n 'без названной причины' tools/kern_contracts.py

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

