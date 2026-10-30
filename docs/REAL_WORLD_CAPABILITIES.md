# Real-world capabilities — the measured matrix

Status: **measured** by `make real-cases-check`. Every row carries the engine
**mode** and both halves; nothing here is typed by hand.

## Two strictness rules

**Rule A — `SKIP` is not success.** Every row needs BOTH halves: `bad` caught by
its **exact marker** AND `good` **PROVEN** (`PROVEN` / `[PASS] ДОКАЗАНО`). A row
where only one half holds is **not closed**. A capability that mentions a
technique in its title but proves nothing is a claim, not coverage.

**Rule B — the engine mode is named.** `a * b` of two variables is non-linear in
Int theory (QF_LIA cannot solve it) and needs bit-vectors (QF_BV). Lumping
"proven in QF_LIA" and "proven in QF_BV" into one tick would hide **how** it was
proven — so the mode is a column.

## The matrix

| # | Capability | Engine / mode | `bad` (caught) | `good` (proven) |
|:--|:--|:--|:--|:--|
| 1 | Python contracts | QF_LIA | `[FAIL]` | `[PASS] ДОКАЗАНО` |
| 2 | C contracts, hardware `idiv` trap | QF_LIA + `TYPE_RANGE` | `[FAIL]` | `[PASS] ДОКАЗАНО` |
| 3 | **Go polyglot** (`int32`) | QF_LIA | `[FAIL] badGo` | `[PASS] clampGo` |
| 4 | **TypeScript polyglot** (`int32`) | QF_LIA | `[FAIL] badTs` | `[PASS] clampTs` |
| 5 | Bounds without annotations (`--xray`) | QF_LIA over a literal length | `[BOUNDS PATH]` | no finding |
| 6 | **Loops: 4 Floyd–Hoare obligations** | QF_LIA + variant | 4 named obligations | `[PASS] count_up: PROVEN` |
| 7 | Overflow in **explicit BV mode** | **QF_BV** (`@kern:bitvec32`) | `[BV]` + `[FAIL]` | (BV path proven) |
| 8 | **AMM fee / anti-arbitrage** | QF_LIA + preset | `no_arbitrage REFUTED` | `PROVEN (trusted: 0 \| holes: 0)` |
| 9 | SQL / RLS tenant isolation | QF_LIA over paths | `[FAIL] rls_buggy` | `[PASS] rls_safe` |
| 10 | Timing side-channel | 2-safety | `[FAIL] check_pin_leaky` | `[PASS] constant_time_op` |
| 11 | `--diff-equiv` Python | Int theory | — | `[EQUIVALENT]` |
| 12 | `--diff-equiv` **C-like** (#361) | Int theory + `CLIKE_EXT` | `[DIVERGED]` + counterexample | — |
| 13 | Path traversal `../` | **QF_SLIA** | (weak sanitizer) | `ДОКАЗАНО`, `trusted: 0` |
| 14 | **IEEE-754 NaN** | **Int + Bool** (NOT QF_FP) | — | `ДОКАЗАНО`, `trusted: 0` |
| 15 | Contract lock (tampering) | contract hashes | `[SECURITY] контракт ИЗМЕНЁН` | — |
| 16 | Anti-cheat (5 sub-classes) | AST rules | `CHEAT DETECTED` ×5 | clean → `[OK] чисто` |
| 17 | MCP: injection + invisible Unicode | schema scanner | `PROMPT INJECTION` + `INVISIBLE UNICODE` | clean schema |

## Anatomy of one function — six modes in a row

Run on a **linear** function so that every mode stays inside the decidable
subset (mode 5, `--diff-equiv`, compares bodies in Int theory — a non-linear body
would fall out of the chain):

| # | Mode | Measured |
|:--|:--|:--|
| 1 | `--xray` finds the risk **without annotations** | `[CRASH PATH] … деление на ноль: b == 0` |
| 2 | a contract **REFUTES** it | `[FAIL] … ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ` |
| 3 | `--explain-hypotheses` is **read-only** | `sha256` unchanged |
| 4 | `--heal` really patches it | `T (1,0)`, guard inserted |
| 5 | `--diff-equiv` confirms the change **at the bug point** | `[DIVERGED]` + `[КОНТРПРИМЕР] b = 0, res_old = -1, res_new = 0` |
| 6 | `--gen-tests` / `--concolic` produce **live tests** | 2 tests, `branches covered 4/4 (dead 0)` |

## What this matrix does NOT claim

- **IEEE-754 NaN is NOT real FP here, and `@kern:float` does not exist.** The
  fixture `tests/fixtures/ieee754_nan.smt2` models NaN as an **Int + Bool pair**
  (`x_nan`, `r_nan`) under `(set-logic ALL)` — it contains **no**
  `(_ FloatingPoint 11 53)` and the translator emits none. So the `trusted: 0` on
  that row is true **of the Int+Bool model**, not of IEEE-754. **Real QF_FP is
  measured at 213 trusted steps** (`docs/METRICS.md` §89.1), where claiming
  `trusted: 0` would be a lie. A source-level `# @kern:float` directive that
  translated `.ts`/`.js` `number` into `Float64` would therefore land in that same
  gap — it is **not implemented**, and this is named instead of faked.
- Mode 6 (`--gen-tests`/`--concolic`) works **by branches**: on a function
  without branches it honestly returns 0 ("the test would be vacuous"), so the
  anatomy uses a branchy linear function for that step.
- Each row is **one concrete task**, not "the language is fully supported".
- The gate measures **interception on fixtures**, not completeness.

## Reproduce

```bash
make real-cases-check
python3 tools/real_cases_check.py --selftest
```

## Registry facts this page is consistent with

<!-- fact:core_tests -->451 core tests · <!-- fact:next_tests -->53 next tests ·
<!-- fact:catalog -->487 catalog · <!-- fact:check_targets -->183 CHECK ·
<!-- fact:canfail_cases -->223 can-fail cases · <!-- fact:anchors -->183 anchors ·
<!-- fact:registry_targets -->239 registry targets ·
<!-- fact:meta_targets -->41 meta · <!-- fact:lean_theorems -->147 Lean theorems ·
QuixBugs: <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.
