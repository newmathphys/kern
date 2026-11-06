# Changelog

All notable changes to KERN. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below is produced by a command in the repository — see
[`docs/METRICS.md`](docs/METRICS.md) and [`docs/evidence/`](docs/evidence/).

## [Unreleased]

Tack 2.4 / **Test 1**: differential soundness check of the C-like translator against LIVE
compilers (`tools/translator_diff_check.py`, `gcc`/`rustc`/`node`), plus **defect #465**:
nested `if/else` in C-like bodies used to collapse into one statement and were silently skipped.
**Test 1 (hunting third-party code)**: `--xray` over `deepseek-ai/dsh-superagent-prototype`
(`src/policy.ts::settingsPolicy`) produced a FALSE `[DEAD BRANCH]` on a REACHABLE branch —
**defect #467**: a brace-less `if` swallowed the rest of the body in semicolon-free (ASI) TS/JS/Go.
**Test 3**: surviving mutants behind `pytest` (`tools/pytest_blind_check.py`), plus **defect #466**:
the arithmetic/translation gates crashed under the system `python3` (no `z3-solver` package).
**Test 1 (hunting third-party code, part 2)**: `--xray` over `deepseek-ai/DeepJIT` (C++20
header-only) exposed THREE blind spots — **defect #468**: `.hpp`/`.cu`/`.cuh` were missing from
`CLIKE_EXT` (86 of 94 core files invisible), `assert len(x) == 1` was not a path guard, and the
bodies of compound `try`/`with` lost their guards (9 false `[BOUNDS PATH]`).

### Added

- `tools/translator_diff_check.py` — the C-like translator is compared against LIVE compilers
  (`gcc`/`rustc`/`node`) on a matrix of 13 constructs × 3 languages. Every live point must be
  PROVEN **and** the floor-semantics trap (Python `//`/`%`) must NOT be proven (defect class
  `#349`). A missing compiler is a NAMED skip, never a silent green.
- `make translator-diff-check` (CHECK) and `make translator-diff-selftest` (META), wired into the
  full `ci.sh` contour (the gate drives real compilers and runs ~77 s); a new can-fail case
  `translator-diff` proves the gate is able to go red.
- `tools/pytest_blind_check.py` — **Test 3** («surviving mutants behind `pytest`»): five functions
  with `@kern:` contracts and deliberately WEAK tests. Every one-line body mutation must SURVIVE
  `pytest` (`rc=0`) **and** be KILLED by `kern` with a counterexample; measured `TP=5/5`, `TN=5/5`,
  `FP=0`, `FN=0`, `J=1.00`.
- `make pytest-blind-check` (CHECK) and `make pytest-blind-selftest` (META); a new can-fail case
  `pytest-blind` proves the gate goes red when a contract is weakened.
- `tools/z3bin.py` — the z3 solver is invoked as a BINARY (`$Z3` → `.venv/bin/z3` → `PATH`); the
  `z3-solver` python package is not a runtime dependency.
- `tools/xray_asi_check.py` + `make xray-asi-check` (CHECK) — regression for **defect #467**:
  four fixtures (real ASI TS, minimal TS repro, TS dead-branch control, C control). The two
  zero-finding fixtures must ALSO be genuinely analysed (`checked >= 1`, `skipped 0`), so a
  silently skipped file cannot masquerade as «0 findings». The control shares the FIXED language
  (TS), since the fix lives in the TS branch; a can-fail case `xray-asi` proves the gate goes red
  (dropping the ASI branch) for the REAL reason, not from a crash.
- `tools/audits_mem_cap_check.py` + `make audits-mem-check` (CHECK) and
  `make audits-mem-selftest` (META) — **defect #470**: the memory cap of the audit harness is
  verified by REAL subprocesses (fast, no Z3): (A) a child asking 8× the cap must return
  `rc=125` with a NAMED reason, (B) death by signal (`rc<0`) must be named (`SIGSEGV`), not
  surface as a raw `-11`, (C) a non-memory failure (`exit 3`) must pass through UNCHANGED (no
  false accusation). The meta mode proves non-vacuity: with `mem_cap=False` the same 1 GB
  allocation succeeds (`rc=0`) and the signal stays raw, so the gate cannot be green without a
  limiter. A can-fail case `audits-mem-cap` removes `preexec_fn` and the gate goes red in 1 s.

### Fixed

- `tools/kern_contracts.py` — **defect #465**: nested `if/else`
  (`if (a > b) { if (a > 0) { … } else { … } } else { … }`) collapsed into a single statement
  (`SKIP — c-выражение вне подмножества: 'a > b) if (a > 0'`). `_collapse_cond_returns` now
  folds `if (c) { return a; } else { return b; }` into `return c ? a : b;` by bracket balance
  BEFORE brace flattening; nested branches fold recursively.
- `tools/arith_semantics_check.py`, `tools/lang_semantics_check.py`, `tools/arith_zig_ref_check.py`
  — **defect #466**: `import z3` raised `ModuleNotFoundError` under the system `python3`
  (`PYTHON ?= python3`), so `make arith-semantics-check` returned `RC=2` and the `arith-semantics`
  can-fail case passed VACUOUSLY (a non-zero rc read as «the gate can go red»). Now `RC=0` under
  both `python3` and `.venv/bin/python`, and the can-fail case goes red for the real reason.
- `tools/kern_contracts.py` — **defect #467**: a brace-less `if` in an ASI-style file
  (TS/JS/Go without `;`) made `_clike_block_end` fall back to `body.find(";")`, which in such a
  file is the END of the body — the inner condition leaked as an OUTER fact, two contradictions
  made it UNSAT, and a REACHABLE branch was reported as `[DEAD BRANCH]` (a false accusation, worse
  than a miss). `_clike_block_end` now takes `lang`; for `go`/`js`/`ts` without `{}` the statement
  ends at the NEWLINE (`;` is taken only if it comes earlier), which NARROWS the block — fail-closed.
- `tools/kern_contracts.py` — **defect #468** (found hunting `deepseek-ai/DeepJIT`): three blind
  spots in `--xray`. (a) `.hpp`/`.hh`/`.cu`/`.cuh` were missing from the C/C++ extension set, so
  86 of 94 core files of a C++20 header-only library were INVISIBLE (the parser could handle them);
  they are now a single `C_EXT` list, and `CLIKE_EXT = {…} | C_EXT` (lesson #353: one place).
  (b) `assert len(x) == 1` was not a path guard in the BOUNDS walk (the crash walk got one in #179),
  and `assert len(set(x)) == 1` emitted a junk symbol — both now add path conditions, plus the
  finite-set cardinality axiom `|set(x)| <= len(x)` (boundary: a `Name` `x`, `k >= 1`). (c) compound
  `try`/`with` were not walked, so their bodies lost inner guards (an `assert` inside `try`); they
  are now walked SEQUENTIALLY while `except`/`finally`/`else` keep the OUTER path (soundness).
  MEASURED: 9 false `[BOUNDS PATH]` on `DeepJIT` tests -> 0.
- `tools/kern_contracts.py` — **defect #471** (three faces of ONE class: "the guard is
  lost, so protected code is accused"). (a) **Python: the `else` branch carried the WRONG
  guard** — the scan at the `ast.If` node walked the WHOLE `If` (including `orelse`) with the
  direct `cond` instead of `(not cond)`, so `if b == 0: return a; else: return gcd(a % b, b)`
  was accused of `[CRASH PATH] b == 0` — the very condition the `if` excludes. The scan is now
  body-only; the recursive `_walk_branches(orelse, path + [(not cond)])` stays the single
  source of truth. (b) **C-like: the body of `while` was analysed WITHOUT the loop condition**
  (`_exec_clike`/`_xray_clike_file` registered only `if (...)` blocks) — Euclid's
  `while b != 0 { … a % b … }` was accused of dividing by `b == 0`, which is the EXIT
  condition. Added `_clike_while_conds_at`: the condition is applied inside the loop body only,
  with sound invalidation (a variable reassigned BEFORE the current statement drops the guard;
  an assignment INSIDE it does not, because the RHS is evaluated with the OLD value). (c) **C-like:
  the `else` branch got no `(not cond)`** — `if a == 0 { … } else { gcd(b % a, a) }` was accused
  of `a == 0`. Added `_clike_else_conds_at`. HONESTY NOTE: the first version of (c) simply
  ADDED `(not cond)` while `if_blocks` already carried the direct `cond` (one block covers both
  branches) — the path became `cond ∧ ¬cond` = UNSAT, and **REAL findings disappeared**
  (MEASURED: `modular_exponential`, a true `modulus == 0`, vanished). The helper now returns
  `(direct, negated)` pairs and the caller REPLACES the direct guard — measured back.
- `tools/kern_contracts.py` — **defect #472**: `f32`/`f64`/`float`/`double` were absent from
  `_TYPE_MAP`/`_NUMERIC_TYPES`/`_CLIKE_RANGES`, so the fallback silently put them in the
  INTEGER domain (class #321) and `pub fn debt_to_equity(debt: f64, equity: f64) -> f64
  { debt / equity }` was accused of `[CRASH PATH] equity == 0` — in IEEE-754 that is `inf`/`NaN`,
  NOT a panic. QF_FP is honestly unsupported, so such functions now become a **NAMED skip**
  (`вещественная арифметика (f32/f64) — модель QF_FP не поддерживается`) instead of a verdict.
- `tools/kern_contracts.py` — **defect #473**: `[BOUNDS UNKNOWN]` printed "НЕ считается ни
  находкой, ни безопасным" and was appended to `found` — Belnap **N** counted as **F**
  (the same class as #454/#469b, but under a SECOND label). Three branches (index modified in
  a loop; inside `while`; solver "unknown") now go through one `_note()` router to `notes`.
  MEASURED on `QuixBugs`: counter `62 -> 42`, while the set of REAL findings is byte-identical
  (31 `[BOUNDS PATH]` + 6 `[CRASH PATH]` + 5 `[SMELL]` before and after) — только класс N ушёл.
- `tools/xray_check.sh` — TWO-SIDED regression gate for #471a/b/c + #472 + #473 on the new
  fixture `tests/fixtures/xray_crash_guards/{guards.py,guards.rs}`: FIVE cases must be silent
  (`gcd_guarded`, `gcd_no_else`, `gcd_while_rust`, `gcd_else_rust`, `ratio_f64`) and THREE must
  stay findings (`gcd_unguarded`, `arr_unguarded`, `ratio_i64`) — exactly `находок 3`. Without
  the TP controls a "fix" by muting would pass; with them it cannot.
- `tools/canfail.py` + `tools/registry.py` — three can-fail cases (`xray-guard-else`,
  `xray-while-guard`, `xray-float-skip`) prove the gate can go red by disabling exactly one fix
  (231 -> 234 non-vacuous cases).
- **`#480` CLOSED BY MEASUREMENT (no code change)** — «`premises_unbound` для BV» is STRUCTURAL, not a
  naming problem. Investigation, step by step:
  1. with the depth fix (`#479`) the same file parses into 21 758 steps, and the refusal becomes
     `premises_unbound` with `посылок 1/794`;
  2. dumping the actual premises shows only THREE top-level `(asserted …)` steps — `$x16`, `$x22`,
     `(not (bvuge result offset))` — so the missing piece looked like a hash-consed NAME;
  3. `$x16` really is a `let` binding `(and $x9 $x15)` that expands to the contract assertion
     verbatim, so TWO fixes were implemented: an abbreviation lookup for bare atoms in
     `expandLets`, and a `collectAbbrevs` pre-pass (the map was EMPTY when the proof root is a
     command list `(set-logic …) (declare-fun …) … (let …)`);
  4. MEASURED after both fixes: still `посылок 1/794`, trusted steps 19 865 -> 19 874, verification
     SLOWER. Cause, from the checker's own debug channel: the `?x` abbreviations are BIT-LEVEL
     `mkbv` terms over hundreds of `k!` atoms (`?x17516 = (mkbv k!960 k!970 …)`), i.e. the 794
     "premises" are bit-blast CLAUSES, not contract assertions. Matching them to 3 contract
     assertions is conceptually impossible;
  5. therefore BOTH fixes were REVERTED (rule: no measurement — no change) and the boundary is
     recorded instead. The real fix requires a solver emitting DRAT/LFSC (cvc5 / Bitwuzla), which
     is a product decision, not a patch.
  This is why `LIMITS` says BV is not proof-carrying — now with the exact numbers.

- `tools/abi_check.py` + `make abi-check` (CHECK) / `make abi-selftest` (META) — **defect #483, the
  machine ABI**. `kernc audit` turned out to be a DEMO of SMT theories (UNSAT core, arrays, CHC),
  not a code auditor: the real funnel and findings live in the Python frontend. So the versioned
  ABI belongs THERE (`--xray-json`), which is exactly the «matryoshka» split (frontend + kernc
  backend). Without an ABI every consumer (CI plugin, MCP server, a Go/Rust wrapper) had to parse
  TEXT with regexes — i.e. to repeat the «the report says something other than what happened»
  class on their side. The contract is explicit: `schema_version: "1.0"`, `summary` (files/total/
  checked/trivial/skipped/findings/unreadable), structured `findings[]` (file/type/details),
  `skipped[]` and `notes[]` histograms. The gate requires EXACTLY ONE JSON object on stdout (a
  leaked log line breaks every consumer at once), the required keys, `summary.findings ==
  len(findings)`, a non-empty `type`, and the funnel identity `checked+trivial+skipped == total`.
  `--selftest` proves the validator refuses SIX breakage types; can-fail `abi-json` leaks a log
  line into stdout and the gate reddens in 1 s. NOTE: `--json` already existed for CONTRACT
  reports, so the new flag is `--xray-json` — reusing the old name would have silently changed an
  existing interface.
- `tools/mutation_lock.py` + `make mutation-lock-selftest` (META) / `make mutate-full` — **defect
  #482**: the mutation tools shared ONE hard-coded lock `/tmp/kern_mutation.lock`, i.e. one lock
  PER MACHINE, so a 40-minute `mutate_zig` sweep blocked `canfail` — and therefore EVERY gate
  check, even ones about unrelated code. MEASURED as real friction: the sweep in this session had
  to be paused three times just to run a single can-fail case. The lock now names the WORKING TREE
  (`/tmp/kern_mutation.<sha256(root)[:12]>.lock`): inside one tree `canfail` and `mutate_zig` still
  exclude each other (defect #88b stays fixed — both edit the sources), while separate git
  worktrees get separate locks. `make mutate-full` runs the full sweep in its own worktree and
  copies the log back. The selftest proves all four properties with REAL flocks: different trees
  have different paths, the same tree returns `BUSY`, ANOTHER tree stays free, and after closing
  the lock is free again.
  HONEST NOTE: the first attempt exited `rc=2` because the worktree was created at `HEAD` *before*
  this fix, so it still used the machine-wide lock — the defect reproduced itself while being
  fixed. The sweep must therefore start AFTER the commit that contains the fix.

- `src/verifier/proof_check.zig` — **defect #479**: the S-expression depth ceiling was TOO LOW for the
  native build. MEASURED on `audits/smt2/kernel_align_deepjit_align_guarded.smt2`: Z3's proof of a
  32-bit alignment bit-blast has **depth 14 113** (1.29 MB) while `MAX_SEXP_DEPTH` was **12 288**,
  so a formula the solver had PROVED was refused with «вывод ГЛУБЖЕ предела вложенности» and the
  checker reported **0 steps**. The limit is now target-split: **16 384 native** (2 271 of headroom
  over the measured need) and **4 096 on wasm** (a browser stack is tiny, deep parsing there stays
  dangerous). With the fix the SAME file parses into **21 758 steps** and the refusal moves to the
  REAL reason (`premises_unbound`, see #480), i.e. the checker now ACCOUNTS for deep BV proofs
  instead of blanket-refusing them. `zig build test` rc=0, `zig build wasm` rc=0.
- `src/verifier/proof_check.zig` — **named boundary #480 (OPEN)**: raising the depth exposed what
  `premises_unbound` really means for `QF_BV`. On the same file the checker now reports
  `посылок 1/794 | ДОВЕРЕННЫХ 19 865 | шагов 21 758` — because in a bit-blasted proof the
  `asserted` steps are **clauses of the bit-blast** (`(or (not k!N) …)`), not the 3 contract
  assertions. Binding them to the contract is conceptually wrong; they must be classified as
  tautologies/definitions, and each of them rests on the `k!` axioms anyway (91 % trusted). This
  CONFIRMS the LIMITS claim that BV is not proof-carrying, now with numbers.
- `tools/kern_contracts.py` — **defect #478**: `[EQUIVALENT?]` printed a HARD-CODED reason
  `(premises_unbound)` regardless of what the checker actually said. MEASURED: for the deep BV
  formula the checker says `[!] причина: вывод ГЛУБЖЕ предела вложенности парсера
  (MAX_SEXP_DEPTH)`, while the report blamed premise binding — class #370/#371 («the report says
  something other than what happened»): the reader looks for a premise-binding defect that is not
  there. The reason is now parsed from the checker output (verified against real output, not a
  guess).

- `tools/spawn.py` + `tools/spawn_check.py` + `make spawn-check` (CHECK) / `make
  spawn-selftest` (META) — **defect #477, the subprocess choke point**. The class «subprocess
  without a limiter» fired THREE times: `#464` (solver timeout), `#466` (`z3` missing from
  `PATH` → silent SKIPs), `#470` (no memory ceiling, `kernc prove` grew to 5.4 GB). MEASURED by
  AST over `tools/*.py`: **170** `subprocess.*` calls, of which **51 had NO `timeout=`** — i.e.
  51 places where a hung binary blocks a gate FOREVER, without a verdict and without a reason.
  `spawn.run()` is the blessed path: timeout ALWAYS (default 900 s), the `z3` directory from
  `z3bin.find_z3` in `PATH` (single source of truth #353), `RLIMIT_AS` on the child, and NAMED
  outcomes (`124` timeout, `125` memory/signal). Its `--selftest` proves all five cases with
  real subprocesses (normal / timeout / memory cap / signal / foreign exit code). Three real
  sites were fixed rather than ratcheted: the `z3 --version` probe and the
  `trust_scorecard` call in `kern_contracts.py`, and the `zstd` unpack in
  `smtlib_proof_check.py` — each now names its timeout. The gate is a RATCHET (baseline 51,
  target 0): growth reddens it, improvement prints «lower the baseline», and the debt list is
  printed every run so it stays visible. Can-fail case `spawn-timeout` reddens the gate in 1 s.
- `tools/xray_precision_check.py` + `make xray-precision` (CHECK) — **defect #475, the
  PRECISION gate**. Precision on third-party code was measured at **56 %** on
  `TheAlgorithms/Rust` (18 findings, 8 false) and, worse, **21 false accusations on 50
  CORRECT `QuixBugs` programs** — and a false accusation is the worst outcome (worse than a
  miss). The gate is two-sided and hermetic: `precision_clean/` (py+rs+c, every guard style:
  if-return, if-else, while, assert, range check, f64) must yield **0 findings**;
  `precision_buggy/` must yield **exactly 5** with every expected name present (a missed
  finding = lost signal); `precision_known_fp/` must yield **exactly 1** — a RATCHET for
  **`#476`**, so when that defect is fixed the gate goes red and demands the function be moved
  back into `precision_clean`. External corpus (`QuixBugs/correct_python_programs`) is checked
  when present against a NAMED baseline (`EXT_FP_BASELINE = 21`, target 0): growth reddens the
  gate, improvement prints "lower the baseline". A missing corpus is a NAMED skip, never a
  silent green. Can-fail case `xray-precision` drops the `while` guard and the gate reddens in
  18 s.
- **Named boundary `#476` (OPEN, not fixed)**: `len(<literal list>)` in a guard is not unified
  with the literal length, so `data = [1,2,3,4]; if 0 <= i < len(data): return data[i]` is
  accused with the counterexample `i = -1`. It is NOT hidden in an allow-list: the function
  lives in `tests/fixtures/precision_known_fp/` and the gate asserts exactly one finding there,
  so the debt is counted and the ratchet works in both directions.

  formulas whose proof the checker verified only PARTIALLY. MEASURED on
  `audits/smt2/hex_index_deepjit_hex_hi.smt2`: the solver says `ДОКАЗАНО`, the proof checker
  says `[PROOF PARTIAL] … ДОВЕРЕННЫХ 15` (bit-blast axioms `k!` — an unprovable free constant,
  so a strict offline check is impossible). That is TWO different claims under one word, and to
  a buyer of «proof-carrying artifacts» it reads as a promise BV does not keep. `measure()` now
  returns `(verdict, trusted)` and every `PROVEN` row carries the count: `trusted 0` (solver and
  checker agree), `[PROOF PARTIAL] trusted N`, or `` `trusted ?` `` when the checker reports no
  counter at all (MEASURED: 44 formulas → **13** `trusted 0`, **11** PARTIAL, **20** without a
  counter — the last group is `ДОКАЗАНО (допущено)`, a weaker claim that the table previously
  hid behind `PROVEN`). Gate `make evidence-trust` (CHECK) + `make evidence-trust-selftest`
  (META): `PROVEN` without a count is a violated claim; the selftest proves all three breakage
  types are caught (and that an empty table is a failure, not a pass); can-fail `evidence-trust`
  turns the gate red in 0 s.
- `tools/audits_run.py` — **defect #470**: the audit harness put NO memory ceiling on its
  subprocesses. MEASURED: `make audits` → `kernc prove` on `audits/rust-core/midpoint.rs` grew
  to **5.4 GB and kept growing** (a 300 s timeout existed, a memory bound did NOT), and with up
  to `KERN_AUDIT_WORKERS` (6) of them at once a «proof run» could evict the whole machine.
  `run()` now sets `RLIMIT_AS` in the CHILD via `preexec_fn` (`KERN_AUDIT_MEM_MB`, default
  2048), inherited by grandchildren (`kern_contracts.py` → `kernc` → `z3`), and turns the
  outcome into a NAMED one (`rc=125`): (a) allocator said so (`out of memory` /
  `error.OutOfMemory` / `MemoryError` / `Cannot allocate memory`), (b) or the child died by a
  SIGNAL (`rc<0`, `SIGSEGV`/`SIGABRT`/`SIGKILL`) — the usual RLIMIT_AS outcome, which used to
  leak out as a raw `-11` with the cause lost. Non-memory failures are passed through unchanged
  (no false accusation). Belnap `N`, not a verdict: `[N]` rows are printed and the `.kern` claim
  status becomes `unknown` (`src/next/parser.zig` rejects an unknown status string — writing raw
  `oom` would break parsing of the project, so the honest name is `unknown`, and the cause stays
  visible in the report).
- `tools/audits_run.py` — **defect #469b (same class as #469a)**: the harness did not pass the
  SOLVER to its children. MEASURED under `make audits` (`PYTHON ?= python3`): `kernc prove`
  printed `[!] z3 недоступен`, so all 44 corpus formulas got UNKNOWN → `proven 0 | refuted 0` →
  the anti-vacuum guard failed with `rc=2` and the certificate rows could not be counted.
  `run()` now prepends the z3 directory (`z3bin.find_z3`, single source of truth #353) to `PATH`;
  a missing solver still yields a NAMED failure instead of a silent «unknown».
- `tools/real_cases_check.py` — **defect #469a**: the expectations lagged behind the honest
  verdict introduced by **#433**. `qfs_sanitizer.smt2` (QF_S) and `ieee754_nan.smt2` used to
  report a FALSE `[PROOF VERIFIED] trusted: 0` because `.structural_only` steps of `th-lemma`
  never called `markTrusted`; after #433 they honestly report `[PROOF PARTIAL]`
  (`trusted > 0`, `unbound = 0`, `holes = 0`), so the gate went red with `rc=2`. The rows now
  assert the measure of #433 instead of the old wish, and the gate got its own solver `PATH`.
- `tools/kern_contracts.py` — **defect #469b (findings counter)**: `[BOUNDS?] … — это
  НЕОПРЕДЕЛЁННОСТЬ (N), не находка` was still appended to `found`, so an honest Belnap `N`
  inflated the finding count (MEASURED on `deepseek-ai/DeepJIT`: `находок 3` instead of 1
  `[SMELL]`, and `findings 1` on `tests/test_ascend.py`). Those lines now go to `notes` — the
  counter can no longer read `N` as `F`. A can-fail case `xray-bounds-note` proves the gate goes
  red (a `while` body loses `notes`).
- `tools/kern_contracts.py` — **defect #469c**: `.tsx`/`.jsx` were not scanned, so 29–30 files of
  `deepseek-ai/dsh-superagent-prototype` stayed invisible. Both extensions are in `CLIKE_EXT`
  (and therefore in `_XRAY_EXTS`); MEASURED over the agent's 30 `.tsx` files: 171 files scanned,
  122/308 functions analysed, **0 findings** — JSX markup does not break the function splitter.
- `tools/xray_check.sh` — a TWO-SIDED regression gate for **#468**: `examples/array_bounds.py`
  gains `get_assert_guard`, `get_set_assert_guard`, `get_try_assert_guard`; the `xray_exts` fixture
  gains `h.hpp` (counted AND analysed, not merely counted). At `HEAD` the gate yields 2 findings,
  with the fix 0; a new can-fail case `xray-assert-guard` proves it can go red by DISABLING the
  `ast.Assert` branch (not by breaking a signature — that would be a vacuous crash, lesson #466).

## [2.8.1] — 2026-11-01

Tack 2.2 / 2.3: **50 journal entries closed (#399..#448), `Open technical defects: 0`**.
Every number below was produced by a command in the repository (see `docs/METRICS.md`).

### Added

- `tools/funnel_accounting.py` — the coverage funnel's arithmetic under locked contracts
  (`@kern:requires`/`@kern:ensures`, checked by `kernc`, sealed in `contracts.lock.json`).
- `tools/clike_ir_check.py` — a table-driven IR gate (19 Int + 5 BV + 2 safeguards) plus an
  instant IR snapshot of both corpora; `tools/mutation_lock_check.py`;
  `tools/source_hygiene_check.py` (the `0x08` ratchet).
- `docs/PLAN_takt22.*` and `docs/PLAN_takt23.*` — self-contained plans with acceptance
  criteria, safeguards and boundaries, kept under RU/EN parity.

### Changed

- `--xray` coverage of functions with branches: `cmark-gfm/src` `41.8% -> 95.1%`
  (`76/182 -> 173/182`), `actions/toolkit` `12.6% -> 93.5%` (`72/77`), with **0 false alarms**.
  The TS denominator was cleaned of 308 `await`/`throw` calls (`458 -> 150`);
  `scanners.c` is **5.3x faster** (SMT memoisation).
- `src/verifier/proof_check.zig`: **6 of 7** `smtlib-proof-check` tasks now pass with
  `trusted: 0` (was 3) and **0 rejected proofs** (`unbound = 0` everywhere); trusted steps on
  `QF_BV/add_three.4_bit` dropped **`2970 -> 646`**; the report identity
  `checked + trusted + other + holes == steps` holds to the unit.
- `src/next/`: the Belnap conflict `B = JOIN_K(T, F)` (`conflicted`) is representable in the
  SQLite catalogue (CHECK generated at compile time from `ast.Status`) and is no longer
  collapsed into `"refuted"` in `agent_packet.json`.
- `--anti-cheat`: rules moved from syntax to context; noise over its own 132 files of
  `tools/*.py` dropped **31 -> 0** while all **12/12** classes stay caught.
- 8 tools of `tools/` now honour `$ZIG`; `kernc --help` prints 27/27 tokens to stdout.

### Fixed

- Journal entries `#399..#448`, including: a falsely inflated coverage denominator (`#410`),
  a silent `0 findings` without a solver (`#407`), eight control bytes `0x08` instead of
  `` (`#413`), a false HAVOC model `!f(c)` (`#414`), a crash on `xml.c` (`#412`),
  vanishing steps in `storeinv` (`#433`), the report identity (`#432`), the three axioms of
  the theory of arrays (`#445`), a 139-level `let` nest (`#443`), and the sealing tool's
  raw traceback (`#448`).


## [2.8.0] — 2026-10-27

### Added

- **Native Zig AST verifier (`kernc verify-zig <file.zig>`, #375):** a built-in
  `std.zig.Ast.parse` frontend INSIDE the static `kernc` binary (0 Python, 0
  regexes). It extracts `/// @kern:requires` and `/// @kern:ensures` from
  `.doc_comment` tokens across all four `fn_proto` forms, models
  `i32`/`u32`/`i64`/`u64`/`usize`, generates safety obligations for `+`/`-`/`*`,
  unary `-MIN_INT`, division by zero and the `MIN_INT / -1` trap
  (`@divTrunc`/`@divFloor`/`@rem`/`@mod`), and suppresses overflow obligations on
  the modular/saturating operators (`+%`, `-%`, `*%`, `+|`, `-|`). MEASURED:
  `addGuarded`/`divOk` PROVEN, `addWrapOk` PROVEN with **0** obligations,
  `addBad` REFUTED with the counterexample `a = INT_MIN, b = -1`.
- **Native theory CLI (`kernc theory <file>`, #376):** a file-based CLI entry
  point for the native Zig engines (`arrays` McCarthy `QF_AX`, `absint`
  `join`/`widen`/`narrow`, `dtmc` stochasticity and reachability) - previously
  they ran only on strings hardcoded inside `kernc audit`.
- **SMT-COMP proof-checking track (`make smtlib-proof-check`, #366, #371-#373):**
  23 official SMT-LIB tasks across `QF_LIA`, `QF_BV`, `QF_AX` and `QF_S`;
  `proof_check.zig` audited 7 official UNSAT derivations (7,945 steps, 0 holes)
  and three official tasks were proven with **`trusted: 0 | holes: 0`**.
- **SV-COMP executable witness validation (`make svcomp-witness-check`, #367,
  #368, #374):** 37 UNMODIFIED official tasks across 4 categories; UNSAFE
  witnesses are confirmed by two external oracles - the compiler (`-Woverflow`)
  and a run under `gcc -fsanitize=undefined,address`.
- **MBPP+ live-Python oracle (`make mbpp-xray-check`, #377, #378):** `[CRASH
  PATH]` accusations are confirmed by a LIVE Python run on the found
  counterexample instead of trusting the test table.
- **Sub-expression overflow detection in `--xray` (Path C, #368):** intermediate
  signed overflows inside compound expressions (`J = 1.00` on the SV-COMP
  overflow regression).
- **Journal hierarchy invariant (`orphans()`, #370):** every sub-row `| **N.k** |`
  must sit under its own header `| **N** |` (RU and EN, 338 records).

### Fixed

- **#371:** trailing `(exit)` is stripped before `(get-proof)` on official
  SMT-LIB files; `MAX_SEXP_DEPTH` raised 4,096 -> 12,288 (the measured safe
  ceiling) with an explicit `TooDeep` reason instead of blaming the solver.
- **#372:** `kernc prove` prints `[PROOF VERIFIED]` strictly when `trusted == 0`,
  otherwise `[PROOF PARTIAL] ... NOT VERIFIED`.
- **#373:** the 1 MB read limit in `kernc smtlib` is gone - official files of
  1.6 MB were silently skipped and reported as "0 files".
- **#374:** `#include_next <assert.h>` in the SV-COMP witness harness - without
  it our own stub shadowed the system header and 6 official `array-examples`
  tasks would not build (the category was VACUOUS).
- **#377:** a false division-by-zero accusation inside `for i in range(n * k)` -
  the loop-entry non-emptiness guard is now emitted (for a product `A * B` the
  sound ring-of-integers property gives the linear `(distinct A 0)` /
  `(distinct B 0)`).
- **#378:** assignment values (`x = ...`, `x += ...`) were never crash-walked, so
  the whole loop body was a blind spot of `--xray`.
- **#379:** `cyberseceval_check.py` is now explicitly labelled an external
  AST/regex BASELINE (0 `kernc`/`z3` calls); real CWE verification lives in
  `cwe-twins-check`, `svcomp-witness-check` and `smtlib-proof-check`.

### Measured

- 449 core Zig tests (was 436), 172/172 CHECK gates proven able to fail,
  208 non-vacuous can-fail cases, 223 registry targets, journal records
  #1-#379 (338 rows, RU == EN).
- Three blind spots of `EvalPlus MBPP+` confirmed by a live run: `Mbpp/265`,
  `Mbpp/292`, `Mbpp/422` pass BOTH base `MBPP` and the 80x `MBPP+` yet raise
  `ZeroDivisionError` on `n = 0` / `b = 0` - with 0 false accusations.


## [2.7.3] — 2026-10-26

Минорный релиз **измеримых гарантий на внешних задачах**. Пять этапов
Генерального плана закрыты и измерены; каждый пункт ниже — команда, которую
можно повторить.

### Added

- **`make real-cases-check` (ЭТАП 5) — измеренная матрица возможностей.**
  **17/17 возможностей закрыто** (у каждой ОБЕ половины: `bad` пойман точным
  маркером И `good` ДОКАЗАН) и **анатомия одной функции 6/6 режимов**. Режим
  движка назван в таблице (QF_LIA / QF_BV / QF_SLIA / Int+Bool). Документы
  `docs/REAL_WORLD_CAPABILITIES.md` + `.ru.md`.
- **`make cwe-juliet-check` (ЭТАП 3) — парный бенчмарк NIST Juliet-style.**
  **Индекс Юдена `J = 1.00`**, **счёт SV-COMP `27/27`**, `TP 9/9 · TN 9/9 ·
  FP 0 · FN 0` на девяти классах MITRE CWE. Документы `docs/CWE_COVERAGE.md` +
  `.ru.md`.
- **`make ai-traps-check` (ЭТАП 4А) — полигон из шести ИИ-ловушек.**
  **6/6 перехвачено СВОИМ маркером, 6/6 честных близнецов доказаны.**
  Документы `docs/AI_TRAPS_SHOWCASE.md` + `.ru.md`.
- **`make quixbugs-diff-check` (ЭТАП 4Б).** **`false_equivalent = 0`**
  (40/40 `DIVERGED`) и **`false_diverged = 0`** на контрольных парах.
- **Двусторонний инвариант `CASE_TARGET` (#358).** Каждый кейс обязан быть в
  таблице, каждое значение — вести в существующую цель; мета-тест 3 ветки.
  Инвариант сразу нашёл семь кейсов без записи и одну запись в никуда.

### Fixed

- **#361 — `--diff-equiv` падал на не-Python входе.** `parse_bodies` теперь
  маршрутизирует по расширению: Python через `ast`, C-like (`.c .h .zig .rs
  .go .ts .js`) через `parse_clike` с их семантикой из `VALUE_SEMANTICS`.
  **Измерено двусторонне:** C-контроль «файл против себя» → `[EQUIVALENT]`;
  багованная C-пара → `[DIVERGED]` с контрпримером `hi = 0, v = 1`. Нелинейные
  тела теперь **называют причину** (`тело требует QF_BV …`).
- **#365 — метка «QF_FP» в матрице была ложной.** Фикстура
  `ieee754_nan.smt2` моделирует NaN парой **Int + Bool**, а не сортом
  `(_ FloatingPoint 11 53)`; `trusted: 0` там верен для МОДЕЛИ. Настоящий QF_FP
  даёт **213 доверенных шагов** (`METRICS.md` §89.1), где заявлять `trusted: 0`
  нельзя. Метка исправлена; директива `@kern:float` **не реализована** — это
  названо, а не подделано.
- **#359, #360, #362, #363, #364** — дефекты, найденные собственными гейтами
  этого цикла (см. журнал `docs/CAPABILITY_STATUS.md`).

### Upstream

- **[`TheAlgorithms/C#1596`](https://github.com/TheAlgorithms/C/pull/1596)** —
  `math/lcm.c`: переполнение `a * b` (при `50000, 50000` печатает **`-35899`**
  там, где истинный НОК `50000` влезает в `int`) и `SIGFPE` при `(0, 0)`.
  Патч `docs/pr/lcm_fix.patch`, оба дефекта воспроизведены `gcc`, исправление
  перепроверено сборкой `-fsanitize=undefined`. Третий отчёт в апстрим после
  `#1595` (C) и `#1075` (Rust).

### Known limitations

- Настоящий **QF_FP** (сорт `(_ FloatingPoint 11 53)`) даёт **213 доверенных
  шагов** пруф-чекера; `trusted: 0` там не заявляется. Директивы `@kern:float`
  в исходнике **нет**.
- `--diff-equiv` сравнивает в Int-теории: нелинейные тела (произведение двух
  переменных, битовые операции) в сравнение не попадают и **называют причину**.
- Режим `--gen-tests`/`--concolic` работает по ветвям: у функции без ветвей
  честно 0.

### Added

- **Артефакты 3-го внешнего PR: `TheAlgorithms/C math/lcm.c` (ШАГ 3 Захода Б).**
  `docs/pr/lcm_fix.patch` + `docs/pr/thealgorithms_c_lcm_PR.md`. **Оба дефекта
  воспроизведены `gcc` на нетронутом файле:** (1) при `a = b = 50000` промежуточное
  `50000 * 50000 = 2500000000 > INT_MAX` — UB в C11, печатает **`-35899`** вместо
  истинного `50000` (ответ в `int` влезает с запасом ~40 000 раз!); (2) при
  `a = b = 0` `gcd(0,0) == 0` → деление на ноль → **SIGFPE**. **Исправление:**
  гард нуля + **деление ДО умножения** `(a / gcd(a, b)) * b`. **Проверено после
  патча** (`-fsanitize=undefined`): `50000,50000 → 50000`, `0,0 → 0`, контроль
  `15,20 → 60` и `12,18 → 36` не изменился, диагностик санитайзера нет. Патч
  накладывается чисто (`git apply --check`). Граница: если сам НОК не влезает в
  `int`, результат непредставим — это следствие типа, и здесь не заявлено как
  исправленное. PR подготовлен, не отправлен.
  задачах.** `tools/real_cases_check.py`. **ИЗМЕРЕНО: 17/17 возможностей закрыто**
  (у каждой доказаны ОБЕ половины: `bad` пойман точным маркером И `good`
  ДОКАЗАН) и **анатомия одной функции 6/6 режимов** (`--xray` → контракт
  `REFUTED` → `explain` read-only → `--heal` `T (1,0)` → `--diff-equiv`
  `DIVERGED` на точке бага → `--gen-tests`/`--concolic` живые тесты). Режим
  движка назван в таблице (QF_LIA vs QF_BV vs QF_SLIA vs QF_FP). Документы
  `docs/REAL_WORLD_CAPABILITIES.md` + `.ru.md` (пара внесена в `docs-parity`),
  мета-тест 4 ветки, невакуумный кейс `real-cases`. Границы названы: IEEE-754
  NaN поддержан на уровне SMT-фикстуры, а не директивой `@kern:float` в
  исходнике; режим 6 работает по ветвям.
- **`make quixbugs-diff-check` (ЭТАП 4Б) — честный замер QuixBugs через
  `--diff-equiv`.** `tools/quixbugs_diff_check.py`. **ИЗМЕРЕНО на полном корпусе
  (40 пар):** `DIVERGED 40 | EQUIVALENT 0 | false_equivalent 0` — ни одна
  багованная пара не объявлена эквивалентной. **Контрольная половина не зависит
  от датасета:** пары `(correct, correct)` обязаны давать `EQUIVALENT`
  (измерено `false_diverged 0`, падений инструмента 0). Без датасета половина с
  40 парами честно пропускается вслух, но контрольная выполняется ВСЕГДА — гейт
  не бывает вакуумным. Мета-тест 4 ветки, невакуумный кейс `quixbugs-diff`.
- **`make ai-traps-check` (ЭТАП 4А) — полигон из шести ИИ-ловушек.**
  `tools/ai_traps_check.py` + фикстуры `audits/ai_traps/`. **ИЗМЕРЕНО: 6/6
  ловушек перехвачено СВОИМ маркером, 6/6 честных близнецов доказаны.** Классы:
  Contract Tampering (паттерн DeepSeek/GLM) → `[SECURITY] контракт ИЗМЕНЁН`;
  Vacuous Precondition → `[VACUOUS] … B4: N, e = 0`; Point-Patch Overfitting →
  `[КОНТРПРИМЕР] x = -10`; Runtime Reward Hacking → `CHEAT DETECTED` (5/5);
  MCP Poisoning/Rug-Pull → `MCP RUG-PULL DETECTED` + `PROMPT INJECTION` +
  `INVISIBLE UNICODE`; CEGIS Self-Healing → `T (1,0)`, крашей 1 → 0, объяснение
  read-only. **Два правила строгости:** (А) точный маркер, а не `rc != 0` — иначе
  опечатка в фикстуре засчиталась бы за перехват; (Б) честный близнец обязан быть
  `PROVEN`/`PASS`, `SKIP` не считается. Документы `docs/AI_TRAPS_SHOWCASE.md` +
  `.ru.md` (пара внесена в `docs-parity`), мета-тест 4 ветки, невакуумный кейс
  `ai-traps`.
- **`make cwe-juliet-check` (ЭТАП 3) — парный бенчмарк NIST Juliet-style по девяти
  классам MITRE CWE.** `tools/cwe_juliet_check.py` + девять пар `bad`/`good` в
  `audits/cwe_juliet/`, прогнанных через собственные движки KERN. **ИЗМЕРЕНО:**
  `TP 9/9 · TN 9/9 · FP 0 · FN 0`, **Индекс Юдена `J = 1.00`**, **счёт SV-COMP
  `27 / 27`, штраф 0**. Классы: CWE-190, 191, 369, 682, 680, 125/193, 22, 89/285,
  208. Документы `docs/CWE_COVERAGE.md` + `.ru.md` (пара внесена в `docs-parity`),
  мета-тест 4 ветки, невакуумный кейс `cwe-juliet`. Границы названы: это не
  полный SARD (девять классов, а не тысячи случаев); CWE-680 и CWE-190 делят одно
  обязательство типа (различает контекст); «ВНЕ ПОДМНОЖЕСТВА» не считается
  доказательством `good`.
- **Двусторонний инвариант `CASE_TARGET` (ШАГ 0, класс #356 закрыт).** Каждый
  кейс обязан быть в таблице, каждое значение — вести в существующую цель
  (цель Makefile либо шаг `zig build`, сверенный с `build.zig`). Мета-тест 3
  ветки, невакуумный кейс `casetarget-gap`. Инвариант сразу нашёл семь кейсов без
  записи и одну запись, ведущую в никуда (`"kern-invariant": "kern"`).

### Fixed

- **#359 — два дефекта САМОГО нового гейта, найденные его первым прогоном.**
  (а) Классификация `contracts` считала обе ветви по выводу `bad`, поэтому `good`
  «доказывался» выводом уязвимого файла — метрика, считающая не то, что
  заявляет. (б) Фикстура границ использовала литерал списка вместо
  документированной аннотации `# @kern:len(data) = N`, из-за чего защищённый
  `good`-близнец обвинялся с контрпримером `kern_len_data = 9` при 8 элементах —
  ложное обвинение.

### Fixed

- **#355 — гейт `artifact-check` не мог пройти НИ РАЗУ, а запись #285 утверждала
  обратное.** `detect_version` искал версию регекспом `releases/download/(vX.Y.Z)/`
  — **со слэшем**, которого в README нет ни в одном теге (`v2.6.3`, `v2.6.4`,
  `v2.7.0`, `v2.7.1` проверены). Поэтому обе цели падали на первом же звене, а
  #285 объясняла удаление кейсов тем, что «README объявляет хеш, и цепочка жива» —
  при том что хеш из README убрал #250. Класс #312/#350/#354: запись противоречит
  коду. **Исправлено:** регексп принимает фактическую форму и не путает `v2.7.2`
  с `v2.7.20`; источник хеша — опубликованный `SHA256SUMS`; offline-режим сверяет
  `--version` сборки с версией README; байтовое сравнение с CI-ассетом переведено
  в сведение с названной причиной; добавлен `--selftest` (6 веток), он идёт первым.
  **ИЗМЕРЕНО:** `artifact-check` rc=0 — asset v2.7.2 `7028931f…` == `SHA256SUMS`;
  `artifact-check-offline` rc=0. Кейс `artifact-offline` ВОЗВРАЩЁН в харнесс
  (подмена версии в README краснит ворота, rc=2 за 0 с) — защита от #82 снова
  действует, а не заявлена.

## [2.7.2] — 2026-10-25

Патч-цикл «Этап 1–2 (Ядро и Семантика) до нуля»: закрыто **14 дефектов**, включая
мину **звучимости в собственном пруф-чекере** (найдена ревизией плана и подтверждена
измерением Z3), дрейф канона и три класса ложных срабатываний на собственном коде.

### Fixed — звучимость ядра

- **#349 — `evalConstInt` делил по-разному: ложное тождество + ПАНИКА + мёртвый guard.**
  Прежняя реализация считала `div`/`mod` как floor при ЛЮБОМ знаке делителя,
  а в SMT-LIB2 для сорта `Int` деление **евклидово**. ИЗМЕРЕНО в Z3: `(div 1 (- 2)) = 0`,
  `(mod 1 (- 2)) = 1`, `(div (- 7) (- 2)) = 4` (не `3`). Следствия: **(1)** `(= (div 1 (- 2)) (- 1))`
  принималось как **доказанное**; **(2)** `@mod(a, b)` при `b < 0` в Zig **паникует**
  («modulus is negative»); **(3)** защита от переполнения `-@divFloor(a, -b)` была **мёртвым кодом** —
  литерал `-9223372036854775808` (MIN) вообще не парсился (модуль `2^63` не
  влезает в `i64`), и тест «проходил» по неверной причине.
  Дополнительно: `+%`/`-%`/`*%` (wrapping) — та же тихая подмена математики
  (`(= (+ MAX 1) MIN)` принималось бы как тождество, а в SMT это `2^63`).
  **Исправлено:** евклидовы `div`/`mod` при `b < 0`; явный разбор MIN в обеих
  формах; checked `std.math.add/sub/mul` с отказом на переполнении; guard
  `q == minInt → null` (ответ Z3 для `div(MIN, -1)` = `2^63` — ВНЕ `i64`).
  **Звучимость по §95.4:** четыре теоремы в `formal/FarkasSoundness.lean`
  (`0 sorry`, `lean` rc=0), включая `euclid_neg_denom_unique` — через
  **ядерную** `Int.ediv_emod_unique'` с условием `b < 0`.
  **Тесты:** 8+ точек, негативные обязательны (`(= (div 1 (- 2)) (- 1))`
  отвергается; `(= (div (- 7) (- 2)) 3)` отвергается), guard на ВЫЧИСЛЯЕМОМ MIN,
  три случая переполнения. `evm-proof-check` — по-прежнему `trusted: 0 | holes: 0`.

- **#353 — семь мест брали свойство языка из ЛИТЕРАЛОВ, а не из таблицы.**
  Обязанность «знаковое переполнение при `MIN / -1`» и «есть ли границы типов»
  выводились из расширения файла (`suffix in CLIKE_EXT`), а не из
  `ValueSemantics`. Любой новый язык с иной семантикой молча получал свойства
  C. **Исправлено:** таблица расширена полями `signed_min_div_trap`,
  `signed_min_neg_trap`, `allow_bv_fallback`, `bounded_ints`; код **читает** их.
  **KILL CRITERIA соблюдены:** `codecheck` остался `TP=6, TN=6, FP=0, FN=0`,
  `contracts` — `11 доказано / 4 нарушено`. То есть рефакторинг не сдвинул ни
  одного вердикта.
- **#350 — КАНОН врал о состоянии ядра.** `docs/CHARTER.md` §3 и таблица
  L4/L5 утверждали «6 доказано, 2 не покрыты» и «пруф-чекер вывод отвергает»,
  тогда как `make charter-check` давал `8 | 8 | 0` (класс #303 закрыт 22.10.2026).
  Тот же класс, что #312/#335, но в САМОМ уставе проекта. **Исправлено:**
  таблица → PROVEN, §3 переписан в **историю границы** (не удалён — удалять
  неудобное и есть тот failure mode, против которого проект построен), плюс
  новый гейт `charter-text-check`, сверяющий ТЕКСТ канона с фактическим
  `EXPECTED_UNCOVERED` (5 веток мета-теста).
- **#348 — харнесс МАСКИРОВАЛ вердикт.** `sh_out` вызывал
  `subprocess.run(text=True)` без `errors=`, поэтому любой байт, не сложившийся
  в UTF-8, валил кейс исключением — и прятал настоящий вердикт инструмента.
  Измерено полным прогоном: `ОШИБОК КЕЙСОВ 1` → `0`. Исправлено `errors="replace"`.

### Fixed — парсеры и фронтенды

- **#325 — Allman-стиль (`{` на следующей строке) давал МОЛЧАЛИВЫЙ пропуск.**
  `RE_FN_FN`/`RE_FN_TS`/`RE_FN_GO` требовали `{` в конце строки заголовка,
  поэтому функция с перенесённой скобкой не распознавалась вовсе («всего 0»),
  хотя сбор тела уже умел следующую строку. **Исправлено:** `{` необязательна,
  но строка обязана на ней **закончиться** (`$` защищает от `fn f(a: i32) -> i32;`).
  ИЗМЕРЕНО: Allman → 1 проверка; контроль same-line не изменён. Фикстуры
  `audits/codecheck/zig_allman.zig` (T) и `rust_allman.rs` (F), матрица
  `TP=6, TN=6, FP=0, FN=0`.
- **#322 — три класса ЛОЖНЫХ `[BOUNDS PATH]` в Python.** Само-применение
  `--xray tools/` давало 6 кандидатов, все защищённые. Закрыто: (1) гард в
  условном выражении сужает путь своей ветви; (2) ранний выход `continue`/`break`
  теперь считается выходом из ветви (не только `return`/`raise`); (3) индекс от
  переменной, изменённой в цикле, понижен до честного `[BOUNDS UNKNOWN]`
  (инварианты `while` не моделируются, #315) вместо недостижимого свидетеля;
  (4) согласованы символы длины (`len__b` ↔ `kern_len_b`), распознана граница
  `range(start, min(..., len(arr)))`. ИЗМЕРЕНО: `6 → 1` кандидат, и остаток
  осмыслен.
- **#342 — `lang="evm"` не выставлялся НИ ОДНИМ путём разбора** (строка таблицы
  была мёртвой). **Исправлено:** директива `# @kern:lang evm` / `// @kern:lang evm`
  переключает семантику; проверено **двусторонне** — с директивой `2 PASS`,
  без неё тот же код **нарушает** контракт (иначе директива ничего не меняет).
  Гейт `make evm-lang-check`, невакуумный кейс.
- **#344/#341 — развёртка `define-fun` + константная арифметика.** Z3 в выводе
  ПОДСТАВЛЯЕТ тело объявленной функции, а контракт содержит ВЫЗОВ — посылка не
  привязывалась. Теперь чекер читает `define-fun` из ШАПКИ SMT-файла
  (`loadFunDefs`) и раскрывает вызовы подстановкой аргументов
  (`funExpand`/`substParams`). Две ошибки первой версии названы в реестре:
  `parseSexp` разбирает ОДНО выражение (а SMT-файл — последовательность), и
  общая ветка превращала АТОМ в пустой список. **ИЗМЕРЕНО**: было
  `посылок 0/1 | ДОВЕРЕННЫХ 1 | вывод ОТВЕРГНУТ` → стало `посылок 1/1 |
  ДОВЕРЕННЫХ 0 | дыр 0 | [PROOF VERIFIED]` на всех трёх EVM-тождествах.
  Гейт `make evm-proof-check` (CHECK), невакуумный кейс `evm-fundef`, три
  Zig-теста (включая негативные: подделанная подстановка не проходит,
  неизвестная функция не «угадывается»).


### Fixed — инфраструктура и CI

- **#345 — кейс `temp-isolation` был ВАКУУМНЫМ.** Кейс дописывает
  неизолированный путь `/tmp/kern_unsafe_new_path` в `tools/xray_check.sh`, а
  гейт `make temp-isolation-check` его **игнорировал**: тот же путь стоял в
  списке `SHARED`. Запись имела причину — каталог `tools/` сканируется целиком,
  и литерал в теле кейса делал бы гейт красным ВСЕГДА. Две конфигурации
  исчерпывали выбор: вечно красный гейт (его отключат) либо невидимая диверсия.
  **ИЗМЕРЕНО** полным прогоном: `ВАКУУМНЫХ 1` (было) → `ВАКУУМНЫХ 0` (стало).
  Исправлено: путь собирается **склейкой двух литералов** (`"/tmp/" "kern_..."`),
  запись из `SHARED` убрана с пояснением, почему её нельзя возвращать.
- **#346 — SIGTERM-откат терял бит `+x` у 30 скриптов.** `_emergency_restore`
  писал свой tmp без сохранения режима — та же ошибка, что #157, но исправленная
  только в `write_atomic`. Каждый `SIGTERM` снимал `+x` у 30 `tools/*_check.sh`,
  дерево становилось «грязным», следующий прогон блокировался инъекционным
  стражем, и часть кейсов получала «зелёную» цель по **неверной** причине.
  Исправлено: сигнальный путь использует **тот же** `write_atomic` — единый
  источник правды. Проверено мини-тестом: 0755 → SIGTERM-откат → `0o755`.
- **#347 — шесть стадий CI были красными.** (1) Дрейф метрик: каталог тестов
  (27 против фактических 28 у `kernfs_router.zig`), витрина, паспорт
  (`code_hash`), покрытие замка контрактов — все производные артефакты
  пересобраны. (2) Страж «нет следов харнесса» ловил **сам себя**: литерал
  маркера диверсии стоял в трёх инструментах-детекторах
  (`arith_zig_ref_check.py`, `injection_guard.py`, `trust_scorecard.py`) — тот же
  класс, что #290/#296, метка собрана из частей. (3) Аттестат и манифест требуют
  приватного ключа владельца — это **честная граница**, а не дефект: подпись
  агент создать не может и не должен.
- **#312 — C-функция с `unsigned`/`size_t` получает ВЕРДИКТ, а не SKIP** (запись
  в журнале была помечена «ограничение», хотя гейт `c-types-check` и невакуумный
  кейс `c-types` уже существуют — журнал противоречил коду).
- **#335 — журнал дефектов EN == RU.** Переведены 13 записей (#294–#308),
  множества совпадают (**307 = 307**), и создан гейт
  `make journal-parity-check` с невакуумным кейсом `journal-parity`: он сверяет
  МНОЖЕСТВА номеров записей в обе стороны. Граница названа: гейт считает числа,
  а не формулировки — качество перевода проверяет человек.
- **#351 — последний ложный `[BOUNDS PATH]` на собственном коде.** `@deal.pre`
  не моделировался как предусловие, поэтому защищённый индекс считался опасным.
  ИЗМЕРЕНО: само-применение `--xray tools/` → **0 `[BOUNDS PATH]`, 0 `[CRASH PATH]`**.
  Двусторонняя фикстура `examples/deal_guard_demo.py` в `make xray-check`.

### Added

- **Гейт `charter-text-check`** (`tools/charter_text_check.py`) — ТЕКСТ канона
  обязан совпадать с фактическим множеством непокрытых законов; 5 веток
  мета-теста. Закрывает класс «документ-канон врёт о состоянии ядра» (#350).
- **Гейт `journal-parity-check`** (`tools/journal_parity_check.py`, класс META,
  4 ветки мета-теста: только в RU, только в EN, разный порядок, отсутствующий
  файл) — закрывает класс «дефект, живущий только по-русски, для внешнего
  читателя не записан вовсе».
- **Гейты `evm-lang-check`** и **`evm-proof-check`** — фронтенд `@kern:lang evm`
  и три тождества Yellow Paper проверяются двусторонне.
- **`abs`/`-x`/`min`/`max` в `arith-semantics-check`** — перевод этих форм
  раньше не сверялся с рантаймом НИ РАЗУ. Теперь 180 точек, включая края `i32`:
  **0 расхождений**, и контроль невакумности (наивный `abs` без переполнения
  даёт 4 расхождения).
- **Кейсы:** `journal-parity` (181), `allman-style` (182), `evm-fundef` (184),
  `evm-lang`, `charter-text`, `arith-abs-min-max`. Итог харнесса —
  **188 невакуумных / 0 вакуумных / 0 ошибок кейсов**.
- **Кейсы на странице «почему KERN»** (`docs/EXAMPLE_WHY_KERN.md` и `.ru.md`):
  шесть репозиториев, пять языков, десять случаев — к уже описанным
  `TheAlgorithms/C`, `TheAlgorithms/Rust` и `boltons` добавлены `madler/zlib`,
  `ziglang/zig`, `tigerbeetle/tigerbeetle`, `ghostty-org/ghostty` и
  `openjdk` (баг Блоха), с измеренными вердиктами из `audits/EVIDENCE.md`.

### Changed

- **`z3-solver` 5.1.0.0 → 5.3.1.0**, проверено **адверсариально ДО мержа**:
  смена решателя может изменить форму вывода, и покрытие пруф-чекера могло
  отвалиться. Прогон на новом решателе: `evm-proof-check` `trusted: 0`,
  `proof-tamper` 40 подделок / 0 принято, `charter-check` 8/8, `contracts` 11/4,
  `audits` 0 расхождений, `zig build test` rc=0. Регрессий нет — мерж разрешён.
- **Обновления CI:** `github/codeql-action` 3 → 4, `actions/upload-artifact` 4 → 7.
- **Lean 4: 147 теорем, `0 sorry`** (+4 по §95.4 в этом цикле).

### Known limitations

- `SDIV(MIN, -1) = MIN` на контрактном пути даёт видимый **SKIP**, а не тихий
  пропуск: в целочисленной модели нет границы типа, а BV-путь упирается в
  покрытие пруф-чекера (#118). Граница названа, а не спрятана.
- В `.py` с `@kern:lang evm` рантайм-подтверждение **бессмысленно** (исполняется
  Python, а не EVM) — измерено и записано.
- Явная директива `@kern:bitvec32` сильнее таблицы, но BV-путь доступен только
  для C-like входов.
- Байткод-дизассемблера EVM (`0x6080...`) по-прежнему **нет**: фронтенд
  принимает ВЫРАЖЕНИЯ и контракты, а не байткод.


## [2.7.1] — 2026-10-23

Патч: закрыт рассинхрон версии в JSON-отчёте, найденный ВНЕШНИМ исследователем.

### Fixed
- **#343 — версия в JSON-отчёте была зашита литералом `"2.4.0"`.** К релизу
  v2.6.4 бинарник печатал `v2.6.4`, а отчёт о происхождении — `2.4.0`. Заметил
  **Massimiliano Brighindi**, скачав релизный бинарник и сверив его вывод с
  отчётом. `make version-check` контролировал 11 поверхностей, но не отчёт
  (класс #97/#292). Теперь `_kern_version()` читает версию из `server.json`,
  а **12-я поверхность** гейта проверяет ФАКТИЧЕСКИЙ вывод `--json`.
- **#317 — внешнее подтверждение зафиксировано.** Независимая проверка релиза
  v2.6.4: 0/840 расхождений в Python, 0/840 в C/Zig/Rust, сквозная сверка
  статического бинарника по `SHA256SUMS`, побайтовое совпадение скрипта.
- **#344 — точный диагноз ограничения #341** (развёртка `define-fun` требует
  подстановки аргументов; константная арифметика `(div 7 2) = 3` не покрыта).
  Не выпущено: полуприменённая развёртка в пруф-чекере опаснее отсутствующей.

### Known limitations
- Три EVM-тождества доказаны **решателем**, но не доверенным пруф-чекером
  (#341/#344) — EVM-фронтенд отсутствует (#342).
- Остальные ограничения — см. раздел [2.7.0].

## [2.7.0] — 2026-10-22

Цикл «доверие и прозрачность»: устав, снимок состояния, самопроверка,
детектор флейки, изоляция временных путей и — главное — семантика языка как
объект.

### Added
- **Устав (`docs/CHARTER.md` + `charter/laws.py` + `make charter-check`).**
  18 законов в трёх классах: алгебраические (доказывает KERN), процессные
  (гейты), политика (не проверяется машинно). Каждый закон НАЗЫВАЕТ своего
  проверяющего, и гейт падает, если проверяющего нет. **8/8 законов класса I
  машинно доказаны.**
- **`docs/STATUS.md` (+ RU)** — генерируемый снимок состояния проекта из
  `facts.json`, реестра и журнала; `make status-check` сверяет с источником.
- **`docs/SELF_VERIFICATION.md` (+ RU)** — KERN, применённый к себе: 7 прогонов.
  Ключевой результат: **73 из 74 собственных заявлений получают `e=0`**, потому
  что это проза, а не машинные контракты. Врата не принимают собственный
  README за доказательство.
- **JUnit XML (`make junit`)** — стандартный формат для GitHub Actions и IDE.
  Кэш-попадание билд-раннера помечается `skipped`, а не «успехом».
- **Детектор флейки (`make flake-check`)** — N прогонов набора целей, сравнение
  вердикта КАЖДОЙ цели. Расхождение — это `B(1,1)`: два противоречащих
  свидетельства (`joinK(T, F) = B`), и ни одному прогону нельзя доверять.
  Измерено: 7 целей x 3 прогона, флейков 0.
- **Гейт свежести свидетельств (`make evidence-freshness`)** — логи класса
  `NATIVE_LIVE` обязаны совпадать с текущим деревом, `ENV_DEPENDENT` — нести
  явную метку базовой линии.
- **`VALUE_SEMANTICS` — семантика ЗНАЧЕНИЙ языка как объект** (8 языков:
  python/c/zig/rust/go/ts/js/evm) + `semantics_for()` с правилом I4:
  неизвестный язык — ЯВНЫЙ отказ, а не молчаливый дефолт в Python.
  Гейт `make lang-semantics-check` проверяет полноту таблицы, правило I4,
  отсутствие дисперсии и **совпадение таблицы с фактическими SMT-формулами**;
  отдельно — что флаги таблицы ЧИТАЮТСЯ кодом.
- **EVM как строка таблицы** (шаг 8): `div_zero_value` и `signed` управляют
  набором обязанностей. Добавление третьей семантики стоит ОДНУ строку
  таблицы и НОЛЬ новых `if lang`.

### Fixed
- **#317** — языко-зависимая семантика деления: `//` (floor) в Python,
  `/` (усечение к нулю) в C/Zig/Rust, `/` в Python — честный SKIP.
  840 вычислений: расхождений 0 (наивный `div` разошёлся бы в 530).
- **#318** — условия пути считаются ПО ПОЗИЦИИ, а не накоплением: защищённое
  деление больше не обвиняется.
- **#303** — звучимая свёртка тривиальных связок (`(and X true)` = `X`) в
  пруф-чекере: `--diff-equiv` теперь даёт ДОВЕРЕННЫЙ `EQUIVALENT`.
- **#321** — канонизация типа возврата: обязанность переполнения больше не
  снимается молча.
- **#327 / #318 (остаток)** — контекстные гарды в обоих маршрутах: ленивый
  `and`/`or` и тернарник не обвиняются ни в контрактах, ни в `--xray`.
- **#334** — обязанности переполнения деления (`INT_MIN / -1`, `INT_MIN % -1`)
  и унарного минуса (`-INT_MIN`). Наземная правда: `gcc` -> SIGFPE (rc=136)
  и SIGABRT (rc=134).
- **#336** — долг изоляции `/tmp` закрыт: 39 -> 0. Рабочие файлы прогонов
  в своём каталоге (`mktemp -d` + `trap`), выходные артефакты — в `build/`.
- **#339 / #340** — семантика значений стала объектом; регрессия от
  `@dataclass` (падало 10+ загрузчиков через `importlib`) устранена.
- **#333** — устаревшее свидетельство о числе тестов: переснято (436),
  кросс-архитектура помечена явной базовой линией.
- **#320** — отозвано необоснованное утверждение о `prime_sieve.c`.
- **#330** — 46 логов свидетельств в подкаталогах не попадали в git.
- **#331** — устаревшие числа в `llms.txt`; файл теперь генерируется из
  `facts.json`.

### Known limitations
- **`--auto` (zero-annotation) для C-like** ищет деление на ноль и границы;
  переполнение в этом режиме не подключено (есть в контрактном пути).
- **Инварианты `while`** не моделируются: находки по индексам в циклах —
  кандидаты, а не приговоры (#315, #322).
- **C-экстрактор** принимает `int` и канонизированные типы, но не указатели,
  структуры и макросы (#312 — частично).
- **Windows не поддерживается** (3 POSIX-блокера, `docs/PLATFORMS.md`).
- **Подпись своя** (Ed25519 владельца), не сторонний билдер: SLSA L3 и Rekor
  в backlog.
- **Английский журнал дефектов** отстаёт на 13 записей (#294-#308) — #335.

## [2.6.4] — 2026-10-21

### Fixed

- **#320 — a published claim that did not survive re-verification (our own error).**
  `docs/SHADOW_AUDIT_EXAMPLE.md` called `prime_sieve.c:44` a **REAL logic defect**
  and printed `count(arr, size=10) = 5`. Re-running against the **real** prime
  array from the same program gives `count(arr, 10) = 4`; the `5` came from a
  synthetic array. The source is self-contradictory about its contract (the doc
  block says "upto which" — inclusive; the test comment says "array size" —
  exclusive) and the test uses `size = 10`, the one value that cannot distinguish
  them. Verdict: **an ambiguous contract, not a defect**; the upstream report is
  withdrawn. The harness `docs/evidence/prime_sieve/reproduce.sh` reproduces every
  number, so the claim can be re-derived instead of believed.
- **#312 — the C extractor accepted only `int` parameters.** The parser required
  exactly one word before the parameter name, so `unsigned int c` was skipped while
  `size_t a` worked, although `TYPE_RANGE` already knew `unsigned`. Multi-word types
  are now canonicalised (`unsigned int`, `long long`, `unsigned long`,
  `unsigned short`, `unsigned char`, `int32_t`, `size_t`, …); `char` and `float` are
  refused **with a reason** (`char` signedness is implementation-defined).
- **#321 — the return type was not canonicalised, so the overflow obligation was
  silently dropped (false PROVEN).** Fixing #312 exposed this: `meta["ret"]` stayed
  raw (`'unsigned int'`), `ret in TYPE_RANGE` was false, and the machine-overflow
  obligation was never generated. Measured: `u32_add(unsigned int, unsigned int)`
  returning `a + b` with `ensures result >= a` reported **PROVEN** — while `gcc`
  gives `a=4294967295 b=1 -> result=0`, contract violated. Same class as #180
  (Rust). `ret` is canonicalised; a return type outside the integer subset now
  SKIPs with a reason in the contract path.

### Added

- **`docs/PLAN_v2.6.4.md`** — the active cycle: queue with acceptance and kill
  criteria, repository targets ranked **with the measurement that excludes
  `raylib`** (0 functions with an `int` parameter → outside the subset), open
  limitations. New principle: **every numeric claim in a document must ship with a
  committed harness that reproduces it** (#320 is the reason).
- Gate **`make c-types-check`** (CHECK) with the non-vacuous canfail case
  `c-types`; both sabotages verified red (dropping the `unsigned int` mapping, and
  dropping the `ret` canonicalisation). Registry: **189 targets, CHECK 150/150
  covered, 171 can-fail cases**.
- `docs/evidence/prime_sieve/` — the verbatim upstream file, a runnable harness and
  its output.
- `tests/fixtures/c_types_demo.c` — six functions: four integer types that must
  receive verdicts, two out-of-subset types that must SKIP with a reason.

## [2.6.3] — 2026-10-21

### Fixed

- **#318 — false `[CRASH PATH]` on a guarded division.** Found while sweeping
  `TheAlgorithms/C/math/`: `--xray` accused `y / x` of dividing by zero even when
  the division sits **inside** `if (x != 0) { … }`. Cause: path conditions were
  **accumulated** instead of computed per position — the query for a divisor
  inside the block received `(not cond)`, that is the **negation of its own
  guard**. Conditions are now resolved per position (`_clike_conds_at`), and `if`
  blocks are registered even when they contain no `return`. The fix applies to all
  three queries that consumed the accumulated list — divisors, bounds, and
  allocation overflow. Measured: single guard, nested double guard, and the real
  `cartesian_to_polar.c` → **0 findings**; the same division **without** a guard is
  still accused. Locked in `xray_check.sh` with both cases.

### Added

- **Upstream contribution — [`TheAlgorithms/C#1595`](https://github.com/TheAlgorithms/C/pull/1595)**
  (22,554 ★, opened 2026-10-21, one file, `+7 −0`, CI `triage` passed): the minimal
  fix for the two defects KERN found in `math/catalan.c` — `SIGFPE` on `n = 0` and
  silent wrong output from `n = 11`.
- `docs/pr/catalan_fix.patch` and `docs/pr/thealgorithms_c_PR.md` — the patch as
  submitted and the PR text.

## [2.6.2] — 2026-10-21

### Fixed

- **#317 — integer division semantics (soundness).** Externally reported by
  **Massimiliano Brighindi (PHI-OMEGA / M)**, reproduced here, and escalated from
  "translation mismatch" to **false acceptance**: the translator emitted SMT-LIB
  `div`/`mod` for Python `//` and `%`, but those are *Euclidean* (remainder always
  ≥ 0) while Python is *floor* and C/Zig/Rust *truncate toward zero*. Measured
  consequence: `requires a == 3 and b == -2` / `ensures result >= -1` over
  `a // b` was reported **PROVEN** (`premises bound: 3/3`, `holes: 0`) while live
  Python yields `-2` and violates the contract.
  The translator is now language-aware: `_CURRENT_LANG` is set in
  `parse_clike`/`parse_file`, `expr_smt` takes `lang`; Python `//` uses the floor
  adapter, `%` the identity `a - b*q`, `/` an honest SKIP (true division is
  float); C/Zig/Rust `/` uses truncation, `%` the same identity.
  Measured after the fix: `tools/arith_semantics_check.py` reports **0 mismatches
  out of 840** (the naive `div` would differ in 530), and
  `tools/arith_zig_ref_check.py` confirms both adapters against the **built-in
  Zig operators** `@divFloor`/`@divTrunc` — **0 mismatches out of 1640 pairs**.
  Gates: `arith-semantics-check`, `arith-zig-ref-check`, canfail cases
  `arith-semantics` and `arith-zig-ref` (both non-vacuous), a CI stage, and the
  Zig reference fixture `tests/fixtures/zig_div_reference.tsv`.

### Added

- `docs/CONTRACT_ANY_PROJECT.md` — the 5-step recipe for writing a contract for
  any project, plus a worked example that found a real crash (SIGFPE) in
  `TheAlgorithms/C`.
- `docs/SHADOW_AUDIT_EXAMPLE.md` — two real defects in `TheAlgorithms/C`
  `math/catalan.c` (crash on `n = 0`, silent wrong answers from `n = 11`), the
  correct fix, and the warning that the obvious fix is wrong.
- `docs/pr/` — patch and pull-request text for `TheAlgorithms/C`.

### Known limitations

- **#318 (OPEN)** — the C-like divisor check accuses *guarded* code:
  `int f(int x, int y) { if (x != 0) { return y / x; } return 0; }` still yields
  `[CRASH PATH]`. A false accusation is worse than a miss, so this is filed as a
  defect, not noise.
- `python3 /` (true division) now yields SKIP instead of a wrong verdict — an
  honest reduction in coverage, by design: soundness outranks completeness.

### Credit

The defect was found and reported privately by **Massimiliano Brighindi
(PHI-OMEGA / M)** with a differential reproducer and a proposed floor adapter.
His adapter is what shipped for Python; the C-like truncation adapter was derived
from the same reasoning and is validated against Zig's built-in operators.

## [2.6.1] — 2026-10-21

Real-world hardening: four languages verified, live models measured, and three
defects found by the field tests themselves.

### Added
- `kernc pack-dir <dir> -o out.kimg`: pack a directory tree (a cloned repository)
  into one image; verified on a real clone with `fsck` (20/20 objects), `inspect`
  and `diff` (one changed file detected).
- `kernc prove --query-kind refutation|equivalence`: the premise-binding rule now
  belongs to contract proofs only, so `--diff-equiv` returns a **trusted**
  EQUIVALENT for real refactorings (verified on a live model rewrite of
  `boltons::clamp_int`).
- The code-checking corpus covers **Python, Zig, C and Rust** with machine-type
  bounds: `TP=5, TN=5, FP=0, FN=0, UNKNOWN=4`, including an `i32` overflow
  witness `a = 2147483647, b = 1 -> 2147483648`.
- Idiomatic Rust (tail expression) is now verified instead of skipped.

### Fixed
- #299 `kernc build <directory>` printed a raw Zig stack trace; now a clean
  message and exit code 2 (same for a missing argument).
- #300 `trace_explorer.py` builds parameter domains from standard Python
  annotations when the QuixBugs-style docstring is absent.
- #302 `pack-dir` silently packed 5 of 20 files (relative paths); the skipped
  counter exposed it on the first run.
- #304 `kernc prove` read the file path from a fixed argument position, so a new
  flag was read as a file.
- #306 Rust bodies written as tail expressions were skipped, so live model
  answers were never verified.

### Measured (live models, not opinions)
- 3 free models x 4 languages: round 1 blind **4 proved / 7 refuted / 1 honest N**;
  after KERN’s counterexample **4 of 7 refuted tasks repaired**. The three
  un-repaired ones are the same Zig overflow task, while the Rust twin was fixed.
- Both models tested rewrite `@kern:requires` (never `@kern:ensures`) when the
  contract is unsatisfiable; `contracts-lock-check` catches it.
## [2.6.0] — 2026-10-21

Trust that can be checked from outside, and an exam that can fail.

### Added
- **External attestation**: `docs/keys/kern-owner.pub` ships in the repository,
  so anyone can verify `kern.intoto.jsonl` with `make verify-attestation`
  (no `$HOME` key, no owner machine). `kid` is recorded in the attestation.
- **Secrets scanner** (`make secrets-check`): 9 provider patterns, redacted
  output, self-test with 7 plantings; runs over git-tracked files.
- **Determinism gate**: the same SMT input twice must give the same verdict,
  counterexample, `trusted` and `holes`.
- **Conformance exam** (`make conformance-check`): 12 sections, 95 checks,
  reading facts emitted by the kernel itself; `--selftest` corrupts nine facts
  and requires every section to turn red.
- **Code-checking corpus** (`make codecheck`) with an honest confusion matrix:
  `TP=2, TN=2, FP=0, FN=0, UNKNOWN=8` - `TN` only means "proved clean".
- **Contract classes** `hard` / `advisory`: `T_advisory` never mixes into `T`,
  and the class is part of the lock fingerprint.
- **Read-only abductive report**: `explain --hypotheses` proposes `requires`
  only, re-verifies each candidate, rejects vacuous ones out loud, and never
  writes to the source.
- **Evidence ledger** `add`/`retract` with recomputation, three provenance
  graphs, and rejection of negative recursive SCCs.
- **`kernx graph`** as the single source of the `G_src` graph (byte parity with
  the showcase).
- **KIMG**: unknown-optional vs unknown-required policy, `WrongEndianness`,
  `kernc fsck / inspect / diff`, three golden fixtures.
- **13-field cache key** and **KERN-X shared budget** with quotas.

### Changed
- `kernc` and the C ABI are `v2.6.0`; `kern_kimg_object_count` returns
  `int64_t` and lengths use `size_t` (LLP64-safe).
- QuixBugs: **40/40** tasks diverge (29 value, 10 crash, 1 hang); the seven
  former `EXPLORED` cases were harness bugs, not clean code.
- `artifact-check*` reclassified `CHECK -> BUILD`: they verify a release
  artefact against a hash announced in README, which only exists at release.

### Fixed
- `timeout`, `out_of_fuel` and `invalid_certificate` no longer collapse into
  `F`; a missing solver is `N`, not an accusation (#277).
- `andT`/`orT` were wrong on the pairs (N,B) and (B,N) (#279).
- Harness: rollback now restores file modes (#283); a skipped case under
  `--only` is an error, not a silent pass (#275).
- Two can-fail cases no longer cling to numbers that `make sync` rewrites
  (#282) and cannot silently pass (#281).

### Known limitations
- Bounded intuitionistic mode (`--intuitionistic --worlds N`) is in the
  backlog: the full text of Kamide & Niki 2026 (IGPL, `10.1093/jigpal/jzag024`)
  describes a Gentzen calculus `sQBDi` and is not available locally
  (`read = {false}`); writing Kripke semantics from an abstract is forbidden.
- Windows is not supported (three POSIX blockers in `docs/PLATFORMS.md`).
- The attestation is signed by the owner key, not by a hosted builder
  (Sigstore/Rekor remain in the backlog).
## [2.5.2] — 2026-10-20

Honest showcase and a release pipeline that cannot lie: proof-flow map with
CEGIS arrow, Ego-Lens over the real `@import` graph, `[+][~][-][=]` filter
matrix, zoom on both diagrams, `--diff-equiv` no longer declares identical
files divergent, unknown KIMG flags are honoured, orphan fact-anchors are
caught, Release Drafter no longer hijacks the release tag, and the site
stopped claiming that README, build and asset hashes are equal (#243–#250).

Full release notes: [`docs/RELEASE_NOTES_v2.5.2.md`](docs/RELEASE_NOTES_v2.5.2.md).

## [2.5.1] — 2026-10-20

Honest QuixBugs boundary (6/40 SMT + 33/40 differential), `make sync` with
`docs/facts.json` and anchors, EN/RU parity guard, no AI boilerplate,
canfail 144/0/0/0, scorecard 128/144, attestation with `attests_commit`.

Full release notes: [`docs/RELEASE_NOTES_v2.5.1.md`](docs/RELEASE_NOTES_v2.5.1.md).

## [2.5.0] — 2026-10-19

Full release notes: [`docs/RELEASE_NOTES_v2.5.0.md`](docs/RELEASE_NOTES_v2.5.0.md).
Every number below is produced by a command in this repository; historical measurements
(e.g. the 77.5% mutation score obtained *without* a solver in `PATH`) are kept as history,
not as the current state.

### Added
- **Native Fourier–Motzkin LIA solver** (`src/verifier/builtin_lia.zig`): 100 systems
  checked against Z3 — 0 disagreements; 60/60 metamorphic checks; `--full-file` 18/18.
- **SAT-model validation inside the kernel** (`verifyModelAgainstSmt`): the Z3 model is
  substituted back into every `(assert …)` and evaluated independently; a false model is
  reported as `SPURIOUS MODEL` and **no counterexample is shown**.
- **`musl abs.c`: `SKIP → PROVEN`** (51 steps, `trusted: 0 | holes: 0`) — `intro-def`,
  `lemma`, `def-axiom`, `rewrite` and `monotonicity` are now checked, not trusted.
- **New theories at `trusted: 0`**: IEEE-754 (the NaN trap), QF_S (sanitiser bypass),
  loops (`invariant`/`decreases`), array bounds, state invariants and RLS policies.
- **`--xray` with zero annotations** across 7 languages (`.py .zig .c .rs .ts .js .go`);
  six field adapters (`self.x`, let-inlining, module constants, `min/max/abs`,
  recursive directory walk, length invariant).
- **`--audit-repo <path|owner/repo|url>`**: sandboxed git
  (`core.hooksPath=/dev/null`, `GIT_TERMINAL_PROMPT=0`, `GIT_LFS_SKIP_SMUDGE=1`,
  30 s timeout), `/dev/shm` cleanup on SIGTERM/atexit, junk/symlink filters.
- **Proof-Carrying `.kimg`** (`[PCC VERIFIED]` with no solver) · **Evidence Decay** ·
  **Merkle audit chain** · **Bit-Rot Guard** (30/30 injections caught).
- **WASM kernel** `kernc.wasm` (86,953 bytes; 5 `kern_wasm_*` functions including `kern_wasm_verify_proof`; 7 export entries with `memory`/`__stack_pointer`).
- **8 MCP tools** plus `server.json` / `mcp.json` / `.well-known/mcp.json`
  (generated from `tools/list`) and MCP tool annotations.
- **`llms.txt`**, `--sarif` (SARIF 2.1.0), `action.yml` with an `xray` mode,
  `tools/trust_scorecard.py` and the `#scorecard` section on the site.

### Fixed (selected; the full journal is `docs/CAPABILITY_STATUS.md` §6c–§6d)
- **#155** the proof checker accepted a tampered DAG (a broken `@xN` reference now yields `.bad`).
- **#166** false `unknown` in WASM (the solver picked a variable with a zero coefficient).
- **#171** `bench-semantic`: single source of truth for the Merkle root (`sealImageRoot`).
- **#173** the evidence guard wrongly accused the harness (write-once baseline, artefacts
  outside the baseline, dirty start → `rc=3`).
- **#174** 52 duplicate top-level definitions in `kern_contracts.py` — **resolved
  (52 → 0, −2003 lines)**; `dup_defs_guard` ratchet now at 0. A second
  `if __name__ == "__main__"` (early `main()` before later defs) and the lost
  C-like routing in `cmd_xray` were found and fixed. Field-audit fixes
  **#178–#184** (comment/string stripping, `assert` guards, Rust signatures,
  scorecard profiles, balanced-paren `assert`, type ranges + let-inlining,
  three-valued `_smt_sat`) ship in the same release.
  by the ratchet guard `tools/dup_defs_guard.py`; the refactor is scheduled after the release.
- **#179** mobile layout overflowed by 12 px (the `owner/repo` input had a fixed `size`
  attribute); the scorecard input is now fluid, and `scrollWidth == clientWidth` on both
  360 px and 1425 px viewports.

### Notes
- License: **PolyForm Noncommercial 1.0.0** (source-available); commercial use requires a
  license from the copyright holder.
- `align(32)` in `blake3_simd8`: no measurable speed-up (2.42 vs 2.41 GB/s) — the change is
  harmless but is **not** claimed as an optimisation.


## [2.4.0] — 2026-10-17

### Added
- **Polyglot contract checking**: `@kern:requires` / `@kern:ensures` are read from
  `.py`, `.zig`, `.c` and `.rs`; machine types (`i32`/`u32`/`i64`/`usize`) are enforced,
  so i32 overflow / unsigned underflow and division by zero are caught.
- **Vacuous-requires detector**: a contradictory precondition (`false ⟹ anything`) is
  reported as `[VACUOUS] precondition is unsatisfiable (empty domain) -> B4: N, e = 0`
  instead of a false PASS.
- **Contract lock** (`--lock` / `--verify-lock`): BLAKE3 fingerprints of every contract in
  `docs/contracts.lock.json`; removing or weakening an `@kern:ensures` line is `rc = 2`.
- **Refactoring equivalence without contracts** (`--diff-equiv old.py new.py`): checks
  `∃x: f_old(x) ≠ f_new(x)` over all of ℤ and prints the exact diverging input;
  exposed as the fifth MCP tool `kern_check_equivalence`.
- **Counterexample → pytest** (`--emit-pytest`) and **SARIF 2.1.0** / GitHub annotations
  (`--sarif`, `--github-annotations`) so a refuted contract lands on the exact PR line.
- **Git pre-commit hook** (`--install-hook`, `--git-diff`): an AI agent cannot commit
  broken code or a weakened contract.
- **`make self-verify`**: KERN verifies its own arithmetic functions.
- **`docs/FarkasSoundness.lean`**: soundness of the proof checker formalised in Lean 4
  (`int_not_le_iff`, `farkas_2_sound`, `farkas_3_sound`, `three_valued_check_sound`,
  `vacuous_requires_unsound`, `skip_preserves_belnap_join`) — 8 files, **42 theorems, 0 sorry**.
- **Ed25519-signed SLSA attestation** (`kern.intoto.jsonl` + `kern.intoto.sig`), verified
  by `python3 tools/slsa_provenance.py --check`.
- **`action.yml`**: the reusable GitHub Action now verifies the downloaded binary against
  `SHA256SUMS` (`sha256sum -c`) before running it.
- **English mirrors** of the key documents: `docs/CAPABILITIES.en.md`,
  `docs/ATTESTATION_PASSPORT.en.md`, `docs/CAPABILITY_STATUS.en.md`, `docs/METRICS.en.md`.

### Changed
- **Mutation score 95.0 % (38/40 killed; 2 survivors proven equivalent)** over
  **14 files / 420 sites** (previously 6 files / 63 sites). The mutator now requires a
  solver in `PATH` (`--require-solver`), because the earlier 77.5 % figure was taken with
  8 solver-dependent tests silently skipped (defect #110).
- **Mutator speed**: `KERN_MUTATE_FAST` reduces stress-loop iterations *without disabling
  any test* (11.4 s → 5.8 s per mutant), plus `--jobs N` (2.15×).
- Can-fail harness: **78/78 CHECK targets** have a proven-can-fail case
  (93 non-vacuous cases, 0 vacuous, 0 case errors) and a `--check-anchors` pre-flight.
- Constant-time digest comparison (`std.crypto.timing_safe.eql`) in 5 places (FIPS 140-3).

### Fixed
- **CI #68/#69 went red** because can-fail cases patched a hard-coded hash in `README.md`
  (root cause found via the GitHub API; anchors are now derived from the files).
- Defects **#104–#116**, including: `witness_model` was always `null` (#104), the memory
  leak opened by that fix (#105), sampling bias in the mutation run (#107), a hanging pipe
  regression test (#108), a pipe deadlock in `child.wait()` (#109), environment variables
  that silently did nothing in tests (#112), the mutation score measured without a solver
  (#110), can-fail polluting committed evidence (#114), a vacuous `slsa` case (#115) and
  harness rollback silently discarding edits made during a run (#116).
- Documentation honesty: fabricated cross-architecture numbers (`279/279` where the log
  says `240 passed / 4 skipped / 0 failed`), stale core counts (198 → 279), a stale KERN-Next
  count (37 → 38 executed tests) and several dated snapshots now marked as such.

## [2.2.0] — 2026-10-16

### Added
- MCP server (stdio) with four verification tools, `make mcp-selftest`.
- `docs/contracts.lock.json`-based specification sealing; `--diff-equiv` groundwork.
- GitHub Action with a SARIF output path.

### Fixed
- Release artefact chain (README ↔ build ↔ asset) enforced by `make artifact-check`.

[2.4.0]: https://github.com/newmathphys/kern/compare/v2.2.0...v2.4.0
[2.2.0]: https://github.com/newmathphys/kern/releases/tag/v2.2.0
