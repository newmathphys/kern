# Resuming work on KERN: handoff (base slice of tack 2.3)

> **I cannot open sessions myself, and I keep no memory between them.** Only what
> is written in this repository survives. This file exists so a new session
> resumes from measured facts instead of from a summary.
>
> **Read first, in this order:** `docs/STATUS.md` (generated: state and counts) →
> this file (open work) → **`docs/PLAN_takt23.md` (the ACTIVE plan: NOT STARTED,
> 6 blocks of 20 minutes)** → `docs/CAPABILITY_MATRIX.md` (what is proven and what each
> proof does NOT show).
>
> **The commit pointer above is PROSE and goes stale by itself.** It is the **base
> slice of tack 2.3**, not "current `HEAD`": chasing HEAD is pointless, a SHA goes
> stale in the very commit that adds it (this line was corrected twice already). The
> authority is `git log -1` and `docs/STATUS.md`, never this line.

> **Facts (EN/RU, kept in sync by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->487 · CHECK <!-- fact:check_targets -->183 · cases <!-- fact:canfail_cases -->223 · anchors <!-- fact:anchors -->183 · registry <!-- fact:registry_targets -->239 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff

## Where we are

| Check | Value |
|:--|:--|
| Branch / tree | `main` = `d98953c`, clean |
| Registry | <!-- fact:registry_targets -->239 targets · **<!-- fact:check_targets -->183/<!-- fact:check_targets -->183 CHECK** · <!-- fact:canfail_cases -->223 non-vacuous cases |
| Release | `v2.8.0` published (4 assets, `artifact-check` chained, `seal` valid) |
| Open technical defects | **0** — `#436` is closed as a MEASUREMENT ERROR (numbers from different builds); after the rebuild all three numbers agree: 926 = 926 = 926 |

## Open work

**The ACTIVE plan is `docs/PLAN_takt23.md` (EN) / `docs/PLAN_takt23.ru.md` (RU).**
It is self-contained: a measured base, four **OPEN** questions (each with a number and a
command), six blocks of 20 minutes, four safeguards, boundaries and the working rules.
Do not re-derive it — read it.

Tack 2.2 (steps 1–7) is **fully closed**; the table below is kept as history:

| # | Step | Why |
|:--|:--|:--|
| 1 | ✅ **DONE** — **R4** in `docs_map_check.py` — compare the map's `§N` ranges with the real maximum | the map said `§1–§167` while the fact was **§169** (and `§1–§145` vs **§147**): **#404 recurred a THIRD time**. R4, the corrected ranges and a 4th meta-test diversion are in place |
| 2 | **#405** — split the funnel into `checked` / `trivial` / `skipped` | **the funnel currently lies**: functions WITHOUT `if` ARE analysed (live proof, **with Z3 in `PATH`**: `ratio` and `add32` produce findings) yet are counted as `skipped` |
| 3 | **RE-SCOPED: the reason histogram mixes FUNCTIONS and BRANCHES** — in the Python path `skipped` holds branch messages (`:4857`, `:4865`) while the counter counts functions (`:7354`), and the scraper (`:7604–7612`) merges both into one dict compared with the function counter (`:5655–5657`) → the nonsense `-6`. Split `fn_skip_reasons` / `branch_skip_reasons`, never print a negative, and add the `#407` Z3 preflight (`rc != 0` + `.venv/bin` picked up from `sys.executable`) | the OLD target ("dump `no reason`") was **vacuous**: that bucket measures 0 on both corpora |
| 4 | **Bitwise conditions via BV** + a `free_syms_in_path` flag | `& \| ^ << >>` over `Int` is unsound; `SAT` checks must refuse a path carrying free symbols |
| 5 | Ternary `?:` → `(ite …)` | `ternary: 6` in toolkit |
| 6 | `nil/null` (+49 C, +3 TS) with reset on `ptr=`, `ptr++`, `ptr+=`, `&ptr`, any call in TS | `nil/null` is the largest real reserve |
| 7 | **Mutation lock** for `canfail.py` | it mutates tracked files; one sabotage once reached `main` (`3067a1b`) |

**Correction to what this file said before.** The "no `if`" bucket was described as
"honest boundary, NOT a loss (nothing to branch on)". That is only **half** true:
there is nothing to branch on, but the obligations (overflow, division, bounds)
**are** checked there, and the counter reports those functions as `skipped` anyway.
That is defect **#405**, and it is why step 2 exists.

**Second precondition, found while re-measuring: Z3 must be in `PATH`.** The live
proof of #405 is INVISIBLE without it — `--xray` prints `findings 0` and no warning
(defect **#407**). Any `--xray` run in this project is `PATH="$PWD/.venv/bin:$PATH"`.

Both corpora are pinned by SHA (`27d942c8`, `0c3a9c33`) so "before/after" is
measured on identical bytes; the clones live in `~/.cache/kern/repos/`.


**Corrected in THIS session (re-measurement before step 1; defect #407 recorded).**
Everything below was re-measured at `d98953c` on the SHA-pinned corpora, and the plan
was corrected wherever it disagreed with the code:

1. **Z3 is a PRECONDITION, not a detail (#407).** The solver is a Python module
   inside `.venv` (`z3 5.3.1`) and `kernc` finds it through `PATH`. Without it
   `--xray` prints `findings 0` and **no warning at all** — the first re-measurement
   of the funnel returned zeros that looked like "clean". With
   `PATH="$PWD/.venv/bin:$PATH"` the evidence for #405 reproduces EXACTLY
   (`находок 4`, `проверено 7 / 16 (skipped 9)`). The preflight exists in `_demo`
   and on the contract path — not in `--xray`.
2. **The plan's §0 histogram did not reproduce.** `no reason` is **0 on both
   corpora** (4 runs: with and without Z3), not 2 and 1; "no `if`" is **126** and
   **337**, not 124 and 336. The sums (232, 400) and the checked counts
   (76/308, 58/458) were right. Denominator corrected: C **182**, TS **121**.
3. **Step 3 was VACUOUS as written** — its acceptance was already met. It is
   RE-SCOPED onto a defect that IS measurable there: the reason histogram mixes
   **functions** and **branches** (branch messages at `:4857`/`:4865`, the function
   counter at `:7354`, and the scraper merging both at `:7604–7612` → the nonsense
   `-6`). Note the honest part: the existing gate `xray-skip-reasons` **passes
   WITHOUT Z3 too** (measured), so its fixture cannot reproduce the mixing — the new
   case has to be added deliberately, otherwise the step is green by construction.
4. **#406 recurred a THIRD time**, in the very commit that recorded it: the map said
   `§1–§167` while the fact was §169, and `§1–§145` while §147.
5. **Step 1 is DONE**: R4 compares every printed `§N` range with the real maximum
   `## §…`, the ranges are corrected in the same commit, and the meta-test carries a
   4th diversion (`§1–§1`) so the new rule is provably able to fail.
6. **THE FUNNEL NOW HAS AN OWNER (sub-step 3.1).** The accounting invariant is no
   longer prose and no longer guarded by a separate Python watchman: it is written as
   `@kern:requires`/`@kern:ensures` in `tools/funnel_accounting.py`, PROVED by our own
   engine (Z3), sealed in `docs/contracts.lock.json` (8 fingerprints) and enforced from
   `tools/xray_check.sh` (`make xray-check`), whose weakened twins MUST be refuted —
   measured: counterexamples `result = -1, named = 1, skipped = 0` and
   `checked_arith_only = 1`. No new CHECK target or canfail case is created (the SAME
   pattern as the #400 sub-gate); non-vacuity is checked on EVERY run by the gate's own
   meta-test.
7. **#407 AND #406 ARE CLOSED; the funnel is wired to the spec (sub-step 3.2).**
   * **Belnap `N` in `--xray`**: `cmd_xray` calls `_xray_solver_gate`; with no solver it
     prints "this is N(0,0) by Belnap, not «0 findings»" and returns **rc=2**. Measured
     by stubbing the solver answer.
   * **Solver auto-pickup**: `_solver_env()` prepends the dir holding `z3` (next to
     `sys.executable`, or `.venv/bin`) to PATH for EVERY `run_kernc`. Measured: in a
     shell WITHOUT `.venv/bin`, `--xray audits/codecheck` now reports **4 findings**
     instead of 0 — the false zero is gone.
   * **Units separated** (the root of `-6`): Python-path function skips (`fn_skipped`)
     are separated from branch notes (`notes`), which are printed under `note:` and
     NEVER enter "Σ reasons == skipped"; the difference is computed by the SEALED spec,
     so a precondition violation prints "NOT A NUMBER" instead of a negative.
   * The #400 gate gained a **NON-VACUOUS** case: a Python fixture with a nested call
     condition yields a branch note at `skipped 0` (this is the deterministic
     reproduction of the mixing — no solver needed), and its meta-test rejects the
     VERBATIM "before" output. Measured: `[PASS #407.2] заметок уровня ВЕТКИ 3,
     пропусков функций 0, отрицательной разницы НЕТ`.
   * Registry unchanged (183/183 CHECK, 222 cases); `ci-fast` 11 green.
   **Only #405 (plan step 2) stays open.**
8. **STEP 2 DONE: the funnel has THREE buckets, and #405 is CLOSED.** Buckets are counted by
   ACTUAL WORK: `checked` (the solver ran), `trivial` (parsed, no obligations), `skipped`
   (not analysed). MEASURED before/after on the SHA-pinned corpora: `cmark-gfm/src` 76/308
   (skipped 232) → `checked 76 | trivial 126 | skipped 106 | Σ 308`; `toolkit/packages` 58/458
   (skipped 400) → `checked 58 | trivial 337 | skipped 63 | Σ 458`; `audits/codecheck` 7/16
   (skipped 9) → `checked 13 | trivial 3 | skipped 0`.
   **The honest part: `checked` did NOT rise on the corpora** — the 126 and 337 functions
   without `if` have NO obligations, so they became `trivial`; what changed is the LABEL, not
   the coverage. Functions WITH obligations (`ratio`, `add32`) really did move to `checked`.
   A companion defect was found and closed while fixing: `_SMT_CALLS` was not reset per
   function, which made every function after the first look "checked" (false coverage) —
   caught because the gate's fixture reported `checked 4 of 4`. The #400 gate was updated in
   the SAME commit (fixture must exercise all three buckets; `Σ buckets == total`; meta-test
   5 → 8 branches). **The journal now has ZERO open defects.**
   **Boundary:** this locks the SPECIFICATION; wiring `--xray` itself to it is the
   next sub-step (the function/branch unit split, `:4857`/`:4865` vs `:7354`).
   Measured experiments that shaped it (METRICS §149): the literal contract
   `result + trivial + skipped == total` on a scalar function gives a FALSE ACCUSATION
   (`total = 0, trivial = 1`), and tuples are unsupported (`SKIP — узел Tuple`).
9. **STEP 4 (safety half) DONE: a free constant in the path REFUSES instead of accusing.**
   MEASURED before the fix: `if (n < MAX_BUF) return n + n;` (CORRECT code) produced
   `[OVERFLOW PATH] … [КОНТРПРИМЕР] MAX_BUF = -2147483647, n = -2147483648` — the parser does not
   substitute `#define`, so the name entered the path FREE and Z3 picked it extreme. Now
   `_smt_sat_guarded` refuses (SAT detectors only; UNSAT checks stay sound) and NAMES the reason
   (`путь зависит от неизвестной константы`). Measured after: fixture `0 findings` (was 2),
   regression `audits/codecheck` still `4 findings`, `checked 13 | trivial 3 | skipped 0`.
10. **STEP 5 DONE (#408): the ternary translation broke on `?.` and `??`, not on ternaries.**
   `convert_ternary` treated ANY `?` as a ternary, so `obj?.field` and `a ?? b` looked for a `:`
   and failed; the FIRST `:` at depth 0 also mis-parsed `a ? b ? c : d : e`.
   **The honest boundary: coverage did NOT rise** — the reason went 6 → 0 but `skipped` stayed 63
   (the same functions are now named "syntax"). The gate got a THREE-SIDED control.
11. **STEP 7 DONE: the harness mutation lock.** A run leaves `.git/CANFAIL_ACTIVE_MUTATION`
   (pid + file) and the new gate `mutation-lock-check` distinguishes "mutation IN FLIGHT — you must
   NOT commit" from "a lock left by a crash — remove it deliberately" (lesson #50). The gate has a
   meta-test on 4 branches, and the canfail case creates a marker with a LIVE pid and removes it.
   Registry grew: **183/183 CHECK, 223 cases** (updated by name, iteratively, where the audit said).
12. **STEP 6 DONE (#409): a pointer is an `Int` (0 = NULL).** cmark `checked` 76 → 141 at the OLD
   denominator. Both safeguards implemented (the Z3 sort trap: `!p` → `p == 0`, never `not p`;
   the reset on pointer mutation, for exited AND enclosing blocks). A FALSE ACCUSATION was found by
   measuring (`inlines.c`) and fixed; the gate pins the two-sided control.
13. **#410 FIXED — and it changes the numbers of the WHOLE tack.** 308 of the 458 "functions" of
   `actions/toolkit` were **CALLS**: in a `.ts` file the groups were taken BY FILE SUFFIX (not by
   the regex that matched) and the fallback `RE_FN_C` matched `await stat(p)` / `throw new Error(...)`.
   The body was cut from the middle of the file → a false `[DEAD BRANCH]` (`io-util.ts: readlink`).
   Measured: `cmark 308 → 308` (K = 0), `toolkit 458 → 150` (458 − 309), `lost_real_functions == 0`.
   **Honest boundary: all past percentages are void** — `58 / 458 = 12.6 %` divided by calls. True:
   `55 / 150 = 36.7 %` of all functions and **`55 / 77 = 71.4 %`** of those WITH branches; on C
   `147 / 182 = 80.8 %`.
   preserved — dropping them moved the denominator to 476!), while numbers (`' '` → 32,
   `"utf8"` → crc32) are substituted ONLY inside the cut-out condition.
   Gate: fixture `tests/fixtures/xray_ts_calls.ts` + a step-7 section in `tools/xray_check.sh`
   (measured on both sides: pre-fix commit `20adf31` gives `Σ 3 == total 3`, after — `Σ 1`).
   **Open work:** memoisation of the verdict (`_SMT_VERDICT_CACHE`, `_SMT_CALLS` incremented ON A
   HIT so `checked` depends on LOGICAL queries) — acceptance is BIT-IDENTICAL buckets with and
   without the cache; and the remaining `syntax` bucket, whose real cause is still to be dumped.



14. **VERDICT MEMOISATION + AN HONEST CALL COUNTER (`#411`).** The profiler on `scanners.c`:
   **2032 calls, 382 unique, 1650 repeats (81.2 %)**, and **152.5 s of 153.3 s** goes INSIDE the
   calls (the floor of one `kernc` call is 11 ms). The cache is keyed by the full query text, lives
   in process memory, is NEVER written to disk; the coverage counter is incremented ON A HIT as well,
   so `checked` = "a LOGICAL query happened". MEASURED: `scanners.c` **153 s -> 29-33 s** (5.3x),
   buckets BIT-IDENTICAL on three corpora. Along the way the summary stopped lying: it printed
   `SMT calls 29` (the LAST function's value), now it prints the file total **2031**, and the 1-call
   difference is explained (the Belnap gate probe: 2032 = 2031 + 1).
15. **A SEARCH MASK (`#412`) - AND `cmark` COMPLETED FOR THE FIRST TIME.** The raw body (needed for
   literals in conditions) exposed the regexes to string contents: MEASURED on `cmark-gfm/src/xml.c`
   - the line `"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"` produced a phantom local `version`
   with a `?` and no `:` and CRASHED the whole corpus walk. The fix: LOCATION by mask, VALUE from the
   raw body (the mask preserves length character by character). MEASURED per file on 159 files:
   EXACTLY 2 changed, the cause named - PowerShell inside a template literal in `tool-cache.ts`
   (`catch { if (($_.Exception...`). `cmark-gfm/src`: **47 s, `checked 147 | trivial 126 |
   skipped 35 | Sum 308`, findings 0**.
16. **`#413` CLOSED: EIGHT CONTROL BYTES 0x08 (6 lines) instead of `\b`.** Replaced by a real
   word boundary. The acceptance oracle is TWO effects, both measured: (a) no DOUBLE findings
   (the fixtures `numdelims <= max_delims` and `row->n_columns++` gave EXACTLY TWO findings for one
   line each - the in-loop one with the FUNCTION name, the file twin with the FILE name; after
   deduplication by SUBJECT - ONE each, the precise one survived); (b) no NEW findings
   (`cmark` `147/126/35` 0 findings, `toolkit` `55/73/22` 0 findings, `codecheck` 4 findings -
   unchanged). The file twins are KEPT: they are needed for functions the splitter missed (#194).
17. **THE MAIN DISCOVERY OF `#413`: THE DOCSTRING LIED.** `_saturate_rewrite` describes itself as
   "Now an exact expression `ite(a+b > HI, HI, ...)` is built", but MEASURED: before the byte fix
   `_saturate_rewrite('a +| b','u32')` returned `a +| b` - the text did NOT change, i.e. the
   rewrite NEVER ran. It now returns `(4294967295 if (a + b) > 4294967295 else (a + b))`. A side
   finding: the BV route for `+|` was ACCIDENTAL (the `|` character matched the bitwise regex),
   not designed; real bitwise operations keep the BV route.
18. **A RATCHET AGAINST THE CLASS "AN INVISIBLE BYTE KILLED A REGEX".** New tool
   `tools/source_hygiene_check.py` (STRING CONSTANTS in the AST of every `tools/*.py`) + a section
   in the EXISTING target `edge-cases` + a meta-test with 3 branches. BOUNDARY: EXACTLY `0x08` is
   caught, because LEGITIMATE control bytes were MEASURED - `0x1b` (ANSI colours, 7 places) and
   `0x00` (byte tests, 3 files); a mention of the byte in a COMMENT is not accused. MEASURED:
   131 files clean.

19. **`#414` FIXED - A SOUNDNESS DEFECT found by the dump, not by a search.** The
   `!p -> p == 0` rewrite hit CALLS: `!S_is_line_end_char(c)` -> `S_is_line_end_char == 0(c)`,
   while `expr_smt` took `0(...)` for a HAVOC call and "translated" it to `(= S_is_line_end_char
   _havoc_1)` - the FUNCTION NAME became a VARIABLE. MEASURED: 9 conditions in `cmark` were
   SILENTLY accepted, while the same 17 forms in `toolkit` failed loudly (in TS `0.method()` is a
   syntax error, in C `0(...)` is a valid call). The rewrite now applies ONLY to a bare name.
20. **`#416` FIXED - fields and operators: 93 % of the functions with branches on BOTH corpora.**
   The "what-if" BEFORE the fix: `===`/`!==` gives -35 in TS (and 0 in C), fields `a->b`/`a.b`
   give -100 in C (and -2 in TS), `typeof X` gives -18 in TS. Priority 2 is confirmed for C and
   REFUTED for TS. MEASURED AFTER (0 findings): `cmark` **147 -> 170** checked, `skipped` 35 -> 12
   (93.4 %); `toolkit` **55 -> 72**, `skipped` 22 -> 5 (93.5 %). Safeguard B: `_mut_names_for()`
   resets a predicate with `a__b` when the BASE `a` OR the field `b` is reassigned.
21. **`#415` CLOSED - AND THE PARITY GATE FOUND AN ORPHAN ON ITS VERY FIRST RUN (`#417`).**
   Generation goes into a TEMPORARY directory, the swap is atomic, and on a parity violation
   `audits/smt2` is NOT modified (MEASURED). The check is TWO-WAY: "a row without a formula file"
   and "a file without a row (orphan)", plus a LOUD drift report against the committed
   `EVIDENCE.md`. FOUND: `zcalloc_zcallocSizeBounded.smt2` - the formula exists, the row does not,
   because `RE_VERDICT` knew only `PASS/FAIL/SKIP` while the extractor also prints `[N]`
   ("NOT SOLVED", Belnap N). So the snapshot SILENTLY hid exactly the case an auditor must see.
   FIXED: `[N]` -> the `**UNKNOWN (N)**` column. MEASURED after: `functions 37 | PROVEN 15 |
   REFUTED 19 | SKIP 2 | NOT SOLVED (N) 1 | formulas 37` - parity "37 rows == 37 formulas",
   `make audits` RC=0.
22. **STEP 4b (BV) WAS ESTIMATED BY MEASUREMENT, AND IT DOES NOT CONFIRM THE PROMISED GAIN.**
   The "what-if" on `cmark-gfm/src` (translation refusals): current **141**; + the index
   `a[i]` -> `a__at_i` gives **140 (+1!)**; + the bitwise abstraction `(a & b)` -> a free symbol
   gives **119 (+22)**. The reason: in C an index almost always comes together with `&` or a call,
   and the bitwise abstraction gives NO bit-level reasoning - it will not catch the dead branch
   `(x&1)==0 AND (x&2)==0 AND (x&3)!=0`. That needs REAL BV, i.e. re-encoding the accumulated path
   conditions from Int into `(_ BitVec 32)` - a separate, large piece of work, NOT started.

23. **BARRIERS 2+3 ARE IN PLACE (`#418`), BARRIER 4 (the extraction) IS NOT.** Seventeen
   defects of the tack were invisible to all 183 gates because what was checked is the FINAL
   VERDICT, not the translation itself. Now: `tools/clike_ir_check.py` - **19 pairs "raw condition
   -> the EXACT SMT or SKIP"** + 2 `#414` guards, in fractions of a second WITHOUT Z3, with a
   meta-test that MUST turn red (MEASURED: a planted expectation is caught); and a **corpus IR
   snapshot** `--dump-ir` / `--check-baselines` (MEASURED: `cmark` 308 functions / 2539 conditions /
   2398 translated, sha `0aa016a61960017a`; `toolkit` 150 / 156 / 134, sha `2a7aac90f9317962`).
   Both are wired into the EXISTING target `edge-cases` (no registry growth). Extracting
   `clike_frontend.py` is NOT done: **29 `canfail` cases patch `kern_contracts.py`** by textual
   anchors, and the contracts lock contains that file - the extraction must go together with
   rebuilding the anchors. The order is deliberate: the net, then the surgery.

24. **STEP 4b (BV) IS DONE (`#422`) - and THREE defects were found along the way.** Bitwise
   conditions are translated into QF_BV32: `_bv_as_bool` wraps a bitwise term in a boolean position
   into `(distinct <term> (_ bv0 32))` (otherwise `sort mismatch`), and the BV query is assembled
   ENTIRELY from BV forms (the Int query does not change by a byte). MEASURED: `cmark` `checked`
   **170 -> 173**, `skipped` **12 -> 9** (**93.4 % -> 95.1 %** of the functions with branches),
   findings **0**; `toolkit` unchanged. Side findings: `#419` (conditions starting with `!(` were
   lost because of a leading space - IR `2398 -> 2401`), `#420` (the BV query declared
   `bvand`/`bv1`/`_` as constants -> "not decided"), `#421` (a FALSE ACCUSATION: `x > 0 AND
   x + 1 < 0` was declared dead, while in C at `INT_MAX` the wraparound makes the branch ALIVE).
   `#421` is withdrawn by a CROSS-CHECK in BV with a NAMED note. HONEST BOUNDARY: the gain is +3,
   not +4, because 23 bitwise conditions come together with calls, and the "havoc + BV" mix is
   outside the subset; the `cmark` time went 47 s -> 69 s.
25. **THE NEXT STEP: extracting `clike_frontend.py` (barrier 4) under the net that is already in
   place.** Measurement: twenty-nine places in `canfail.py` patch `kern_contracts.py` by textual
   anchors, and the contracts lock contains that file - the extraction must go together with
   rebuilding the anchors. The acceptance criterion: the IR snapshots (`2401/2539` and `134/156`) and
   the buckets (`173|126|9`, `72|73|5`, `13|3|0`) match BIT-FOR-BIT.

26. **DIRECTION B (Goal 1): A DRY `kernx` RUN ON A BELNAP CONFLICT - THREE DEFECTS FOUND.**
   Two contradictory pieces of evidence for one claim: `kernx status` shows `статус conflicted: 1`
   and `N->B(конфликт) 1` (the truth layer works) while `kernx build` CRASHED with
   `[!] SQLite: CHECK constraint failed` - the catalog CHECK schema had 11 statuses while
   `ast.Status` has 12: `conflicted` (Belnap B) was not in the schema, so the FLAGSHIP capability
   was unrepresentable (`#423`). The agent packet collapsed B into F: the reason was printed as the
   LITERAL `"refuted"` although the human report said `[conflicted]` (`#424`). While fixing it, a
   SQLite migration trap surfaced: a bare `ALTER TABLE ... RENAME` REWRITES references in other
   tables (`metrics.claim_id REFERENCES "claims_old"`), and after the `DROP` the reference is
   dangling and the catalog becomes unusable (`#425`).
27. **FIXED AND PINNED:** the CHECK list is ASSEMBLED FROM `ast.Status` AT COMPILE TIME (drift is
   impossible by construction), `reason` prints the actual status, and the migration of an old
   catalog follows the procedure from the SQLite documentation (`foreign_keys=OFF` +
   `legacy_alter_table=ON` + `foreign_key_check`). Two tests in CI via `test-next`: every status of
   the vocabulary inserts, and the E2E "resolution -> catalog -> packet" must name
   `reason: conflicted`. MEASURED: build on a conflict -> `[OK] Собрано`, the catalog holds
   `('claim:feature Z','conflicted')`, the packet says `reason: conflicted`; an old DB: the row and
   the metrics survived, `FK: REFERENCES claims(id)`; a repeated run does not trigger the migration.
28. **BOUNDARIES:** verified on a FIXTURE project (there is no live project of the second contour in
   this environment); `kernx packet --scope` and `diff` were NOT tested for conflict cases; the
   migration does not carry rows whose status is outside the vocabulary - and it says so.

29. **A DRY MEASUREMENT ACROSS THREE POINTS (0 code changes).** (1) `#424`'S NEIGHBOURS: there is
   NO third twin - `kernx packet --scope` names `conflicted`, `kernx diff` shows
   `- claim:feature Z conflicted`, `state_axes.toBelnap` is an exhaustive `switch`. (2)
   `smtlib-proof-check` RC=0; `trusted == 0` for **3 of 7** UNSAT tasks, but **2970 of ~2981**
   trusted steps are ONE QF_BV task (the checker has no `bitblast`/`bv-*` rules - DECLARED), while
   the residue in the three tasks is 1 and 5+5, and the first is NAMED: **`rewrite`**. (3) THE
   ANTI-CHEAT: of the reviewer's 5 bypasses **2** are caught - the rules are SYNTACTIC: a literal
   `def __eq__: return True` is caught while `setattr(C, "__eq__", ...)` is NOT; `mock.patch` is
   caught while `target_mod.fn = lambda` is NOT; `pytest.skip('passed')` has no rule at all.
30. **THREE OPEN DEFECTS ARE RECORDED.** `#426` - the anti-cheat misses MASKED twins (the gate
   `anti_cheat_check.sh` claims "ALL 5 classes caught", but its fixture holds the LITERAL forms:
   class `#394.4`/`#418` - the check verifies the fixture, not the class). `#427` -
   `--anti-cheat <directory>` crashes with a traceback instead of a named error. `#428` - the
   checker COMPUTES the name of the unrecognised rule and `kernc prove` PRINTS it, but the gate
   parses only numbers, so the report does not answer the auditor's question. The cure for `#426`:
   SEMANTIC rules (`setattr` with a dunder name, assignment to an attribute of an imported module,
   `skip`/`xfail` inside `test_*`) plus a fixture with masked twins.

31. **`#426` IS FIXED WITH SEMANTIC RULES, `#427` IS CLOSED, `#429` IS RECORDED.** Added:
   `setattr` with a dunder name -> `dynamic dunder override`; assignment to an attribute of an
   IMPORTED module via a lambda/reference -> `monkeypatch of imported module attribute`; an
   UNCONDITIONAL `pytest.skip` in the body of a `test_*` -> `unconditional skip inside a test`. The
   fixture gained three masked twins, the gate requires 8 classes and is NON-VACUOUS (planting
   `getattr` -> `[!] чит НЕ пойман`, rc=2; restoring -> rc=0). MEASURED: the reviewer's 5 bypasses ->
   **5/5**. `--anti-cheat <directory>` is now rc=2 with a named error (was: an `IsADirectoryError`
   traceback).
32. **`#429` - A FALSE POSITIVE ON OUR OWN CODE (partially fixed).** The rule "exit inside tested
   code" fired on the MODULE-LEVEL CLI idiom `sys.exit(main())`: MEASURED **119 of 132** files of
   `tools/*.py` were flagged as cheats. Now an exit is flagged only INSIDE a function - the noise went
   **119 -> 30**. BOUNDARY: the other 30 are flagged by rules that only make sense for a TEST file
   (`mock` 186, `overfitting` 59, `swallowed` 29, `exit` inside functions 13), and the gate checks
   "clean code passes" on ONE hand-picked file - the cure is a `--test-file` mode or a requirement of
   "0 findings on N of our own files".

33. **`#426.2`/`#426.3`: CLASSES ARE CLOSED, NOT LINES.** Every trick has a SECOND sugar and it is
   closed too: `C.__eq__ = lambda ...` -> `dynamic dunder override (assign)`; `setattr(mod, "fn", ...)`
   -> `monkeypatch via setattr`; `obj.fn = lambda ...` (except `self`) -> `monkeypatch of attribute
   (callable)`; `raise unittest.SkipTest(...)` -> `test skipped by raise`; decorators
   `@pytest.mark.skip`/`xfail`/`@unittest.skip` -> `test disabled by a decorator` (while a CONDITIONAL
   `skipif(sys.platform == "win32")` is NOT flagged - only `skipif(True, ...)`). Along the way import
   aliases (`import x.y as alias`) are registered now. A TWO-SIDED control: the new fixture
   `tests/fixtures/anti_cheat_honest.py` (a setUp assignment, `cfg.timeout = 30`, a module-level
   `sys.exit(main())`, a conditional skipif) gives **0 findings**; the gate requires 12 classes + the
   honesty of the clean file + a rejection of a directory WITHOUT a `Traceback`, and it is
   NON-VACUOUS (planting into the honest file -> `[!] ЧЕСТНЫЙ файл обвинён`, rc=2). The noise on our
   own files: 31/132 (the `#429.2` boundary remains).

34. **`#428` CLOSED: THE RULE NAME IS WIRED INTO THE REPORT AND PROTECTED BY AN INVARIANT.** The
   gate parses `[i] первое непроверенное правило: <rule> (<N> шт.)` and prints the rule IN THE TABLE
   (`ДОВЕРЕННЫХ 1 (rewrite)`, `0 (—)`), while the two-sided invariant `trusted > 0` <=> the rule is
   NAMED makes the check NON-VACUOUS: a broken parser instantly turns the gate red (`rc=1`). A 10th
   meta-test branch was added; MEASURED `smtlib-proof selftest: ошибок 0`. The next step (NOT done):
   if the 1 and 5+5 trusted steps on non-bitwise tasks are trivial `rewrite`/`monotonicity` forms,
   the `trusted: 0` share there can be driven to 100 %.

**Closed in THIS session (verification of all capabilities):**

1. **`make showcase-live-all` — every row of `docs/CAPABILITY_MATRIX.md` is now
   EXECUTED, not read.** Before this, the live showcase covered 7 of 42 matrix
   rows: a reader could verify 7 capabilities and had to take the other 35 on
   trust from prose. Measured 2026-10-28: **32 rows, 0 failures, 119 s total,
   slowest row 24.5 s.** Each row carries its external oracle and what it does
   NOT prove. The two long rows (full tree scan ~20 min, cross-architecture
   ~5 min) run only under `showcase-live-all-full`, and their commands are
   PRINTED even when skipped — nothing is hidden behind a flag.
2. **Four defects were found BY building that coverage** (they were invisible
   while the rows lived only as prose): #395 the showcase buffered its output
   (0 bytes in 87 s when redirected — a log reader cannot tell "running" from
   "hung"); #396 `quixbugs-replay` read the dataset from `/tmp` only, so after
   any cleanup the gate silently skipped (cache moved to `~/.cache/kern/repos`);
   #397 `make bridge` truncated its OWN summary line with `head -40`, so the
   Truth Gate verdict never appeared; #397.4 a wrong marker in my own showcase
   row (`false_equivalent` belongs to a different gate) made the row fail while
   the target worked.

What is deliberately NOT done (not a defect, a boundary):

- `claims-audit` is in the full contour, not in `ci-fast` — so a bare number in a
  file listed in `SURFACES` can drift until the full run (defect #394.4).
- KERN is not a scanner: it does not find bugs in foreign repositories on its own.

## Closed in the last session (with the evidence for each)

1. **Drifting timing numbers no longer read as constants.** The observed RANGE is
   written next to each snapshot in `docs/METRICS.md` §159/§163 and
   `docs/CAPABILITY_MATRIX.md`, and the stable claim is the THRESHOLD
   (0.2 s; `CT < 3.0`; `EE >= 10.0`).
2. **Two foreign proofs are now reproducible from the repository** (defect #393):
   `docs/evidence/example_why_kern/lcm_numerator.c` -> `[BV] [FAIL]` with a
   counterexample, and `docs/evidence/thealgorithms_rust/binom_step.rs` ->
   `[FAIL] binom_step: ПЕРЕПОЛНЕНИЕ типа u64`. Each has a GUARDED twin that must
   be PROVEN, so the refutation is not vacuous. Gate: `make foreign-verdicts-check`.
3. **`docs/TEN_PROOFS.md` and this file are linked** from both READMEs.
4. **`make showcase-live` states its Zig requirement FIRST** (defect #392):
   `tools/showcase_live.py` runs a preflight printing the exact version and the fix
   BEFORE the seven rows, so a missing Zig 0.17 no longer looks like a defect in the
   project. Measured: without Zig 0.17 the warning is the first line; with it the
   showcase is 7 rows / 0 failures.

5. **The C-like `--xray` skip histogram is MEASURED (defects #400, #401).** The
   summary used to claim "skipped N with explicit reasons" while printing NONE;
   reasons are now recorded, normalised into structural keys, printed, and the sum
   is checked against the counter. Measured: `cmark-gfm/src` 232 skips, 
   `toolkit/packages` 400 — sums match. Gate `tools/xray_skip_reasons_check.py`
   (called from `xray-check`), case `xray-skip-reasons`.
6. **Four FALSE `[DEAD BRANCH]` on real `cmark-gfm/src/utf8.c` removed (#401).**
   `if_derived` accumulated `(not cond)` for every exited block regardless of
   branch, so mutually exclusive branches contradicted each other (`str1 >= 160`
   AND `str1 < 160`) and the path became UNSAT. `_clike_conds_at` is nesting-aware
   now; `if_derived` is gone. Findings 4 -> 0 with coverage unchanged (76/308),
   while a genuinely dead condition is STILL found. Case `xray-nested-branch`.

## Process rules that repeatedly saved this project

1. **Verify every published number and command against the code**, not against a
   summary. Four of ten externally drafted "proofs" did not match the repository.
2. **Never batch an edit with a run of the thing being edited** — the two raced
   three times in one session and produced fake `IndentationError` / stale reads.
3. **Write large new files atomically** (`cat > file <<'EOF'` or one editor call).
   A series of `insert_line` calls into a growing file tore functions in half.
4. **`zig` in `PATH` may be the pip package `ziglang` 0.13** (it lives in
   `.venv/bin` on purpose, for `portable-bench`). Put the real Zig first, or the
   build fails with an error that blames our own `build.zig`.
5. **A new file carrying `fact:` anchors must be added to `SURFACES`** — the
   orphan-anchor guard refuses it otherwise (defect #246).
6. **A new CHECK target needs a `canfail` case and a `CASE_TARGET` entry**, and a
   new case needs the file it patches in `FAULTABLE`.

## The next step: `trusted: 0` on the non-bitvector tasks

**STATUS: steps 1 and 2 are DONE** (`#431`). A dump of S-expressions (`KERN_DEBUG_TRUSTED`)
named THREE rules that held the residue on the non-bitvector tasks:

| Task | Rule | Status |
|:--|:--|:--|
| `2PhLockVParam_RC-07` | `rewrite` — absorption `and(false, X) = false` | ✅ FIXED (TRUSTED 1 → 0) |
| `storeinv…00002_001.cvc` | `commutativity` — equality symmetry | ✅ FIXED (5 → 4) |
| same | `lemma` x2, `monotonicity` x2 | ⏳ LEFT: `(lemma (unit-resolution @x184 @x104 false) $x162)`, `(monotonicity @x101 (= (select ?x29 i1) ?x108))` |

**The number of tasks with `trusted == 0` became 4 of 7.**

### For `QF_BV/add_three.4_bit` (2970 trusted) — fix the BRANCH LOGIC, not flattening

A dump of the premises of the first trusted step (`[dbg-ur-unver]`) showed that the step
is **CORRECT** (from `(C or k!220)` and `(not k!220)` exactly `C` follows), while the
cause of the refusal is a **NESTED `or`** in the clause: `remaining` = 1 literal
`(or A B C)` versus 3 in the conclusion. **THE FLATTENING ATTEMPT (associativity of
`or`) WAS REVERTED BY MEASUREMENT**: TRUSTED `2970 → 3408` (worse). So the existing
branches (partial resolution / De Morgan / case splitting) handle this shape BETTER —
they are what must be reworked.

**What must NOT be claimed:** that the `trusted > 0` residue in `QF_BV` is explained
by missing BV rules — NOT CONFIRMED by the dump (defect #430).

## What must NOT be claimed

- KERN is not a scanner: it does not find bugs in other people's repositories on
  its own (measured: 0 of 715 functions of foreign repos fall into the subset).
- `[BOUNDS] … length NOT known` is a candidate, not an accusation.
- SKIP / "outside the subset" is never a proof of correctness.
- The ReDoS and non-interference oracles are **measurements with thresholds**, not
  deterministic proofs.
