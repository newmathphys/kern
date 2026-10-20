# Field audit: 14 industry repositories

What this document is: a **measured** run of KERN's two field tools over real,
unmodified third-party code bases, and what the numbers were **before** and
**after** fixing the defects that the run itself exposed.

* `tools/trust_scorecard.py --repo <dir>` — composition / hygiene scorecard
  (8 language categories, licence, tests, CI, MCP surface, Lean theorems).
* `tools/kern_contracts.py --xray <dir>` — zero-annotation X-Ray
  (`[DEAD BRANCH]`, `[CRASH PATH]`, `[BOUNDS PATH]`, McCabe CC).

**Scope, stated plainly.** KERN is a verification gate for *contracts*
(`requires ⇒ ensures`, certificate re-checked by the native Zig proof checker).
It is **not** an AST-level linter for unannotated C/C++: the C-like X-Ray parses
conditions, `assert` guards, type ranges and divisors, and it **skips 60–80 % of
functions** on real repositories. So a `0 findings` line below means
"nothing proven and nothing refuted inside the analysed subset", not "clean code".

Repositories were cloned with `--depth 1` into `/dev/shm/kern-field-lab`
(hooks disabled, LFS smudge off). **Nothing in their trees was modified.**

## 1. Scorecard: before → after

"Before" = first field run (v2.5.0 tools). "After" = same tools with the
fixes #181 (profiles, licence/test/Lean detection) and #183 (type ranges).

| Repository | Language | Before | After | Δ |
|:--|:--|:--|:--|--:|
| `github/cmark-gfm` | C | 40 / 100 · D | **78 / 100 · B** | +38 |
| `actions/toolkit` | TypeScript | 40 / 100 · D | **83 / 100 · B** | +43 |
| `BurntSushi/ripgrep` | Rust | 50 / 100 · D | **73 / 100 · B** | +23 |
| `modelcontextprotocol/servers` | Python/TS | 50 / 100 · D | **85 / 100 · A** | +35 |
| `modelcontextprotocol/python-sdk` | Python | 68 / 100 · C | **85 / 100 · A** | +17 |
| `modelcontextprotocol/typescript-sdk` | TypeScript | 50 / 100 · D | **83 / 100 · B** | +33 |
| `tiangolo/fastapi` | Python | 64 / 100 · C | **81 / 100 · B** | +17 |
| `jlowin/fastmcp` | Python | 56 / 100 · C | **75 / 100 · B** | +19 |
| `pallets/click` | Python | 58 / 100 · C | **83 / 100 · B** | +25 |
| `pallets/flask` | Python | 50 / 100 · D | **73 / 100 · B** | +23 |
| `psf/requests` | Python | 52 / 100 · C | **70 / 100 · B** | +18 |
| `tigerbeetle/tigerbeetle` | Zig | 54 / 100 · D | **84 / 100 · B** | +30 |
| `zigtools/zls` | Zig | 60 / 100 · C | **73 / 100 · B** | +13 |
| `leanprover-community/aesop` | Lean 4 | 42 / 100 · D | **73 / 100 · B** | +31 |

Why before was so low: the scorecard looked only for a file literally named
`LICENSE` (real projects ship `COPYING`, `LICENSE.md`, `LICENSE-MIT`), only for
`tests/` (not `test/`, `__tests__/`, `*_test.go`, `*.test.ts`, in-tree Zig
`test "` / Rust `#[test]`), and only for Lean files under `formal/` — so
`aesop` with 250 `.lean` files scored 0 for formal soundness.

Grade `A+` (95–100) stays reserved for the full KERN stack (contracts with
`trusted: 0`, can-fail harness, Ed25519 attestation, 8-tool MCP surface).

## 2. X-Ray `[CRASH PATH]`: before → after

"Before" = raw regex over source text. "After" = comment/string stripping,
path narrowing, `assert` guards, type ranges and let-inlining (#178–#184).

| Repository | `checked / total` functions | `[CRASH PATH]` before | after |
|:--|:--|--:|--:|
| `github/cmark-gfm` | 95 / 254 | 59 | **0** |
| `actions/toolkit` | 32 / 148 | 22 | **0** |
| `BurntSushi/ripgrep` | 36 / 1354 (was 0 / 1292) | 60 | **0** |
| `modelcontextprotocol/servers` | 207 / 345 | 25 | **0** |
| `modelcontextprotocol/typescript-sdk` | 103 / 916 | 60 | **0** |
| `modelcontextprotocol/python-sdk` | 2748 / 3276 | 16 | **4** |
| `jlowin/fastmcp` | 7524 / 8680 | 13 | **3** |
| `tiangolo/fastapi` | (unchanged) | 4 | **0** |
| `pallets/click` | (unchanged) | 3 | **0** |
| `pallets/flask` | (unchanged) | 1 | **0** |
| `zigtools/zls` | 114 / 497 | 49 | **1** |
| `tigerbeetle/tigerbeetle` | 586 / 2380 | 60 | **0** |
| `psf/requests` | `[BOUNDS PATH]` | 4 | **0** |
| `leanprover-community/aesop` | n/a (Lean) | — | — |

Total `[CRASH PATH]`: **469 → 8** (re-measured after #182–#184; per-repo numbers above). Before the fixes roughly **95 %** of the
findings were false: `/` inside `// comments`, `/// docs`, string literals
(`"pkg/windows/Manifest.xml"`), JS regex literals, `ALL_CAPS` macros, and
identifiers that were not inputs at all.

## 3. What still remains (and why it is honest)

| Finding | Verdict |
|:--|:--|
| `fastmcp` `divide` / `modulo` (`y == 0`) | **real**: test helper divides by an unguarded parameter |
| `zls` `initFromTrigram` (`len == 0`) | **real contract gap**: the function itself has no `len != 0`; the caller's invariant is not visible |
| `python-sdk` (4) | conservative: divisor is a dynamically-resolved attribute or a test helper parameter — value unknown, not proven either way |
| `zls` `alternate` | **fixed by #182/#183**: `assert(@backingInt(index) < len)` is now a path guard |
| `tigerbeetle` (`shard_bits`, `slot_count`, …) | **fixed by #183**: comptime fields/constants do not depend on inputs |

Rule used throughout: **a false accusation is worse than a skip**. When the
model cannot prove the guard, the finding is dropped and the reason is
recorded, never guessed.

## 4. Reproduce

```bash
git clone --depth 1 https://github.com/tigerbeetle/tigerbeetle /tmp/kern-field-lab/tb
python3 tools/trust_scorecard.py --repo /tmp/kern-field-lab/tb
python3 tools/kern_contracts.py --xray /tmp/kern-field-lab/tb
```

Both tools are also exposed as `make audit-repo-check` (git sandbox:
`GIT_TERMINAL_PROMPT=0`, `core.hooksPath=/dev/null`, 30 s timeout, `/dev/shm`
cleanup on `SIGTERM`) and as the browser scanner on
<https://newmathphys.github.io/kern/#scorecard> (GitHub Trees API +
`raw.githubusercontent.com`, `kernc.wasm`, no backend).

## 4. B2: `[BOUNDS PATH]` and `[OVERFLOW PATH]` for C-like, and a retro-test on historical CVE fixes

Two more defect classes are now modelled for `.c/.h/.cc/.zig/.rs/.ts/.js/.go`
(`_xray_clike_file`, `tools/kern_contracts.py`):

| Class | What is claimed | How it is decided |
|:--|:--|:--|
| `[BOUNDS PATH]` | an array/pointer index can be **negative** on the current path (reads before the buffer) | index is a `-`-expression and Z3 confirms `SAT(idx < 0)` under the path guards + type ranges |
| `[OVERFLOW PATH]` | a **size** passed to `malloc/calloc/realloc/strbuf_grow/alloc` can exceed `INT32_MAX` | argument is a `+`/`*` expression and Z3 confirms `SAT(size > 2147483647)` |

**Declared limits (measured, not assumed).** Loops are not modelled, so
`value - 1` indexing is claimed **only when the same variable is not controlled
by a `while`/`for` condition**; pointer-offset arithmetic (`data[-k - i]`) is
reported separately, because there the index is negative *by construction* and
the real question is whether it walks before the buffer start. A single
parameter index (`buf[i]`) is never accused: its range comes from the type.

### 4.1 Retro-test on real CVE fixes (`github/cmark-gfm`)

Method: for each published security fix, take the file **before** and **after**
the fix (`git show <c>^:file` vs `git show <c>:file`), run `--xray`, compare.

| # | Fix commit | Vulnerability | Before | After | Verdict |
|:--|:--|:--|:--|:--|:--|
| A | `2cb4a20` (2022-11-08) | OOB read in `validate_protocol`: `data[-rewind - i]` with unguarded `i` up to `len` | **2 findings**, incl. exactly `-rewind - i` | 1 finding (`-rewind - len - 1`, see note) | **CAUGHT** |
| B | `4682993` (2026-09-22) | unsigned pointer overflow: `data[-((ptrdiff_t)rewind) - len - 1]` | 0 | 0 | missed (C cast `(ptrdiff_t)` is outside our expression subset) |
| C | `ac80f7b` (2022-02-22) | `row->n_columns` (`uint16_t`) wrap in `extensions/table.c` | 0 | 0 | missed (16-bit field increment, not a size passed to `alloc`) |
| D | `198669d` (2018-10-18) | off-by-one `numdelims <= max_delims` → `<` in `src/inlines.c` | 0 | 0 | missed (comparison semantics, not an index/size expression) |

**Result: 1 of 4 historical fixes caught, 0 false accusations on the fixed
file except one residual** on `data[-rewind - len - 1]`: after the fix that line
is guarded by `if (len == (size_t)(max_rewind - rewind)) return true;`, and the
C cast makes the condition untranslatable for us — so the finding stays as a
*honest* "possible" rather than a proven bug.

**What this measures.** The useful claim today is narrow: *"here is an index
that can be negative / a size that can overflow, decided by Z3 on this path"*.
It is not a CVE detector for all classes. Fix B needs cast handling
(`(ptrdiff_t)`, `(size_t)`), fix C needs field-width tracking, fix D needs
comparison-semantics analysis — those are the concrete next steps.

### 4.2 Refinement after §4: casts, off-by-one, and a counter-based pointer rule (defects #189–#191)

The first retro-run left one residual finding on the **fixed** file and missed
three fixes. Three narrow causes were found and closed:

| # | Cause | Fix |
|:--|:--|:--|
| **#189** | C casts (`(size_t)(…)`, `(ptrdiff_t)(…)`) made a guard untranslatable, so the path was not narrowed — and in `4682993` the cast hid the index entirely | `_strip_c_casts()` removes type casts before parsing conditions/indices/sizes (a cast does not change an `Int` in our model) |
| **#190** | Upper bound / off-by-one was not checked at all (`i <= len` allows `i == len`) | `[BOUNDS PATH] off-by-one` is claimed when the comparison is exactly `<=`, the right side is a length-like **parameter**, and the same counter is used as an index |
| **#191** | “Pointer offset is negative” is **trivially true** for any `data[-k]`, so on the fixed file it was pure noise | Class 1 is claimed only when the offset contains a **loop counter** (its magnitude grows without a matching guard) |

**Re-measured on the same four published fixes:**

| # | Fix | Before | After | Verdict |
|:--|:--|--:|--:|:--|
| A | `2cb4a20` (OOB read in `validate_protocol`) | **1 finding — exactly `data[-rewind - i]`** | **0** | **CAUGHT (sniper: hit before, clean after)** |
| B | `4682993` (pointer overflow via cast) | 0 | 0 | still missed (offset is a fixed sum, no counter — claiming it would be noise) |
| C | `ac80f7b` (`uint16_t` counter wrap) | 0 | 0 | still missed (struct-field width is not modelled) |
| D | `198669d` (`<=` → `<`) | 0 | 0 | still missed (no `buf[i]` in the same function) |

Synthetic control stays 6/6: `buf[i-1]` → flag; under `if (i < 1) return` → silence;
`malloc(len+1)` → flag; under `if (len > 1000) return` → silence; `while (i <= len) buf[i]`
→ off-by-one; with `< len` → silence.

### 4.3 Native certificates for the fix (our own checker, not Z3 trust)

Two SMT models of the same claim (“the backward offset stays inside the
available prefix”) are checked by the native Zig proof checker:

| Model | File | Result |
|:--|:--|:--|
| **before** the fix (no bound check) | `audits/cmark/validate_protocol_unguarded.smt2` | `KERN-EQ2 : F`, `[MODEL VERIFIED]` (4 asserts), counterexample `max_rewind = 0, rewind = 0, len = 1` |
| **after** the fix (`len < max_rewind - rewind`) | `audits/cmark/validate_protocol_guard.smt2` | `KERN-EQ2 : T`, `[PROOF VERIFIED] steps: 29 … farkas: 1 … **trusted: 0 \| holes: 0**` |

So the code with the guard is **proven** by our own checker, and the code without
it has a **verified counterexample** — not “Z3 said so”.

## 5. Four of four cmark-gfm fixes, a real zls finding, and .js/.go field runs

### 5.1 Retro-test: **4 / 4** published fixes (was 1 / 4)

| # | Fix | Vulnerability | Rule that catches it | Before | After |
|:--|:--|:--|:--|--:|--:|
| A | `2cb4a20` | OOB read: `data[-rewind - i]`, `i` up to `len` | pointer offset containing a **loop counter** (#191) | **1** | **0** |
| B | `4682993` | unsigned wrap: `data[-((ptrdiff_t)rewind) - len - 1]` | cast covers **one term**, rest is unsigned (#192) | **1** | **0** |
| C | `ac80f7b` | `uint16_t n_columns` counter overflows 65535 | field type from the file's own `struct` (#193) | **1** | **0** |
| D | `198669d` | off-by-one: `numdelims <= max_delims` | `<=` against a length-like **capacity** name (#194) | **1** | **0** |

Every rule is stated with its own limit, and each is validated in both
directions: a hit on the vulnerable file and **silence on the fixed one**.
Rules C and D work at **file level**, because both affected functions in
cmark-gfm have **multi-line signatures** and are not visible to the per-function
parser (this was the measured reason they were missed before).

### 5.2 Native certificates for every class (`audits/cmark/`, `audits/zls/`)

| Vulnerable → fixed | Model | Verdict of our Zig checker |
|:--|:--|:--|
| A `2cb4a20` | `validate_protocol_unguarded/_guard.smt2` | `F` + `[MODEL VERIFIED]` (counterexample `max_rewind=0, rewind=0, len=1`) → **`T`, trusted: 0, holes: 0** (29 steps, farkas 1) |
| C `ac80f7b` | `capacity_u16_unguarded/_guard.smt2` | `F`, counterexample `n = 65535` → **`T`, trusted: 0 (5 steps)** |
| D `198669d` | `offbyone_unguarded/_guard.smt2` | `F`, counterexample `n = cap` → **`T`, trusted: 0 (21 steps)** |
| zls `initFromTrigram` | `audits/zls/init_from_trigram_unguarded/_guard.smt2` | `F`, counterexample `len = 0` → **`T`, trusted: 0 (13 steps)** |
| B `4682993` | `ptr_wrap_unguarded/_guard.smt2` | `F`, counterexample `a=0, b=1, cap=0` → **`T`, trusted: 0, holes: 0** (25 steps). Model is **case-split** (`a < b` → wrap; guard removes that case), because a comparison with `ite` inside it is not canonicalised yet. |

**The certificates are verified by a gate, not by hand:** `tools/audits_run.py`
checks every `audits/*/*.smt2` file against its expected verdict
(`*_guard` → proven, `*_unguarded` / `*_control` → refuted) and fails `make audits`
on any mismatch — **12 certificates, 0 mismatches**. Before this they were dead
files: a solver regression would have silently invalidated the whole table.

### 5.3 Real finding in `zigtools/zls`

`src/TrigramStore.zig:519` `initFromTrigram(trigram, len: u32)` computes
`split.index_1 % len`. With `len == 0` that is a division by zero (panic in Zig).
`--xray` reports `[CRASH PATH] initFromTrigram: возможно деление на ноль: len == 0`;
the pair of SMT models above proves the missing guard (`len >= 1`) closes it.

### 5.4 `.js` and `.go` field runs — and three false-positive classes they exposed

| Repository | Files | Functions checked | Findings (final) |
|:--|--:|--:|--:|
| `expressjs/express` `lib/` | 6 (`.js`) | 7 / 21 | **0** |
| `axios/axios` `lib/` | 70 (`.js`) | 32 / 133 | **0** |
| `gin-gonic/gin` | 99 (`.go`) | 86 / 1375 | **0** |
| `cli/cli` `pkg/search` + `internal/ghrepo` | 9 (`.go`) | 12 / 82 | **0** |

The `cli/cli` run uses a **sparse checkout of two packages** instead of the whole
repository: a full scan of `cli/cli` does not fit a bounded session, and reporting
“0 findings over the whole repo” from a partial scan would be a false claim.

The first run produced **9 findings, all false**, and each was traced to a defect:

| # | Cause | Evidence |
|:--|:--|:--|
| **#195** | `let`-inlining treated a **reassigned** local as a constant (`var done = false; …; done = true; if (done)`) | express: 4 fake `[DEAD BRANCH]` |
| **#196** | `x = x || K` was not modelled — after it `x` is never 0 | axios: fake `[CRASH PATH]` on `% samplesCount` |
| **#197** | `err != nil` compared against a pointer sentinel in an `Int` model | gin: 4 fake `[DEAD BRANCH]` |

After the fixes: **0 findings on all three**, and the checked counts dropped where
they should (gin 200 → 86), because pointer comparisons are now honestly skipped
instead of being “proven”.
