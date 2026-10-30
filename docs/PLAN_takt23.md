# A 120-MINUTE PLAN - Tack 2.3

**Topic:** from `1020` trusted steps towards an honest limit, plus a breakdown of
four open questions, each of which is already MEASURED (no guesswork).

**Base slice of the tack:** `main` after commit `#431`. Do not chase HEAD: the SHA
changes at the very moment of committing - already paid for in practice (defect #406).

**Read in this order:** `docs/STATUS.md` -> `docs/NEXT_SESSION.md` -> this plan.

> **Facts (EN/RU, kept in sync by `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->487 · CHECK <!-- fact:check_targets -->183 · cases <!-- fact:canfail_cases -->223 · anchors <!-- fact:anchors -->183 · registry <!-- fact:registry_targets -->239 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff

---

## §0. The base: measured facts (the starting point)

### 0.1 The checker `src/verifier/proof_check.zig` - an audit of official `UNSAT` proofs

| Task | steps | trusted | first unrecognised rule |
|:--|--:|--:|:--|
| `2PhLockVParam_RC-02` | 66 | **0** | - (`[PROOF VERIFIED]`) |
| `2PhLockVParam_RC-07` | 15 | **0** | - (`[PROOF VERIFIED]`) |
| `2PhLockVParam_RC-08` | 7 | **0** | - (`[PROOF VERIFIED]`) |
| `CircularTrains-PT-012_RC-00` | 38 | **0** | - (`[PROOF VERIFIED]`) |
| `storeinv...00002_001.cvc` | 78 | **4** | `lemma` (plus `monotonicity`) |
| `storeinv...` (the second) | 125 | **4** | `lemma` |
| `QF_BV/add_three.4_bit` | 7616 | **1020** | **`def-axiom`** |

Result: the number of tasks with `trusted == 0` is **4 of 7**. False alarms **0**,
holes **0**.

### 0.2 What has already been closed in this tack (so it is not redone)

1. **Constant absorption** (Kleene three-valued logic): `(and false X) = false`,
   `(or true X) = true`. It closed the only trusted step of `RC-07`.
2. **The `commutativity` rule**: equality symmetry via expanding `$x` names.
   It reduced `storeinv` from 5 to 4.
3. **The fallback `remaining.len == 1 && remaining[0] == the goal`**: it closed the
   pattern `(or C lit) and not lit entails C`. It reduced `add_three.4_bit` from
   **2970 to 1020**.
4. **Reverted by measurement:** flattening `or` at the beginning of `checkUnitRes`
   (it would have been 2970 -> 3408). The cause is measured: the premise
   `(not (or A B))` cancels the literal `(or A B)` one-to-one, while flattening
   destroys that literal BEFORE the cancellation.

### 0.3 The two `--xray` corpora (coverage of functions with branches)

| Corpus | verified | of functions with branches | findings |
|:--|--:|--:|--:|
| `cmark-gfm/src` | 173 of 308 | **95.1 %** | 0 |
| `actions/toolkit` | 72 of 150 | **93.5 %** | 0 |

Regression `audits/codecheck`: `checked 13 | trivial 3 | skipped 0`, findings **4**.

### 0.4 The state of the registry and the gates (generated, do not rewrite by hand)

`STATUS.md`: open technical defects **0**, the highest number **431**.
Registry: CHECK **183**, can-fail cases **223**, goals **239**.

---

## §1. Four open questions (each with a number and a command)

### 1.1 `def-axiom` - the new first unrecognised rule in `add_three.4_bit` (1020)

**What is known for sure:** before the fallback there were 2970 trusted steps and the
first rule was `unit-resolution`. After the fallback there are 1020 and the first rule
became `def-axiom`. Hence `unit-resolution` is **no longer first**: the residue is held
by `def-axiom`.

**What is known about `def-axiom` in the code:** the rule IS in `KNOWN_RULES` and has a
tautology check (`verifyDefAxiom`). A dump earlier showed the shape
`(def-axiom (or $x2688 k!140 $x3214))` - that is, with a **skolem constant** `k!140`.

**Hypothesis (to be checked by a dump, NOT believed):** the definition axiom for a
skolem constant is NOT a tautology by itself - it must be checked against the
DEFINITION of `k!140` from the proof (an `anchor`/`sk.` step or `(let ((k!140 ...)))`).

**Command:** dump the first 5 `def-axiom` steps plus their expanded conclusions:
```bash
KERN_DEBUG_TRUSTED=1 ./zig-out/bin/kernc prove ~/.cache/kern/smtlib4/QF_BV/add_three.4_bit.smt2 2>&1 | grep -m 20 'dbg-trusted'
```

### 1.2 `storeinv`: `lemma` x2 and `monotonicity` x2 (4 trusted)

**The S-expressions are already captured** (no need to capture them again):
```
#1 lemma :: (lemma (unit-resolution @x184 @x104 false) $x162)
#2 monotonicity :: (monotonicity @x101 (= (select ?x29 i1) ?x108))
#3 lemma :: (lemma (unit-resolution @x184 @x81 false) $x145)
#4 monotonicity :: (monotonicity @x101 (= ?x140 ?x156))
```

**What is visible to the naked eye:**
* `monotonicity` here is CONGRUENCE: from `@x101` an equality is derived. The code has
  `verifyMonotonicity`, but it did not take these two shapes (probably `@x101` is a
  reference to a step whose conclusion is an equality of terms, while `?x29`/`i1` are
  unexpanded names).
* `lemma` is hypothesis discharge (RAA): the subtree derives `false`, and the conclusion
  negates the hypotheses. The code has `verifyLemma`; one must find WHY it did not take
  exactly these two shapes.

**Command (a dump of the INTERNAL cause is needed, not just the S-expression):**
add a print of the refusal branch to `verifyMonotonicity`/`verifyLemma` under
`KERN_DEBUG_TRUSTED` (following the `[dbg-ur-unver]` pattern) and run `storeinv`.

### 1.3 `premises_unbound`: `1/8` on `storeinv` and `0/188` on `add_three`

**This is NOT the same as trusted steps.** `premises_unbound` is the failure to bind
premises to the CONTRACT of the task. It is exactly why both tasks print
`[!] ПРУФ-ЧЕКЕР ОТВЕРГ вывод решателя` even though `holes 0`.

**Important:** this is a separate boundary. It cannot be "closed" by weakening -
only by a breakdown: which exact `(asserted ...)` steps did not match the contract.

**Command:** the gate `tools/smtlib_proof_check.py` already parses the reason; a dump of
unbound premises is available under `KERN_DEBUG_LIA` (`[dbg-unbound]`).

### 1.4 Reporting: the "resolution" column does not reflect 1950 verified steps

**Measured:** on `add_three.4_bit` the `resolution` column equals `5247` BOTH BEFORE and
AFTER the fallback, even though there are 1950 fewer trusted steps. Hence the column
counts the **number of steps of the rule**, not the **number of verified ones**.

**Why it matters:** the reader of the report cannot see that the work was done. This is
exactly the class of `#428` (the number is there, the answer is not).

**What to do:** separate the counters (`unitres_steps` and `unitres_verified`) and print
both, OR print `verified = steps - trusted - bad`. Acceptance: the sum of the columns must
add up to the number of steps.

---

## §2. Four safeguards (each proven by the practice of THIS tack)

1. **Verify a change BY MEASUREMENT before/after, not by reasoning.** Flattening `or`
   looked sound and logical - the measurement gave `2970 -> 3408` (worse), and it was
   reverted. The opposite example: the fallback `remaining.len == 1` gave `2970 -> 1020`.
   **Both decisions were made by a number, neither by elegance.**
2. **Never run a check in the same batch as an edit to what it checks.** Violated in this
   tack: `ci-fast` and `edge-cases` failed on a file into which I had planted a fake in
   the same batch. Both failures were FALSE.
3. **A two-sided control for every new detector:** a positive (must VERIFY) and an attack
   (must REFUSE). Plus confirmation of NON-VACUITY by a plant (`expected 7, found 1`) -
   otherwise the test can be green by construction.
4. **Run gates with BOTH environment variables:** `ZIG=<binary 0.17>` AND
   `ZIG_DIR=<directory 0.17>`. Different gates read different ones: the `Makefile` guard
   reads `ZIG`, while `tools/ci.sh` reads `ZIG_DIR`. With `.venv/bin` first in `PATH` the
   `zig-guard` refuses (pip-ziglang 0.13, defect #392).

---

## §3. Schedule: 6 blocks of 20 minutes

### Block 1 (0-20 min). A dump of `def-axiom` in `add_three.4_bit` - what exactly holds 1020

1. Capture a dump of the first 5 trusted `def-axiom` steps plus expanded conclusions (the
   command in §1.1).
2. Check the hypothesis of §1.1: is the skolem-contract shape a tautology; if not, find
   where the DEFINITION of `k!NNN` lives in the proof.
3. **Acceptance:** it is named how many of the 1020 are held by `def-axiom` and which
   shapes they are (a list of shapes, not "many").
4. **Risk:** `def-axiom` for a skolem constant may require parsing `anchor` steps - that is
   no longer a "rule" but a context. If so - **do not fix it**, name it as a boundary.

### Block 2 (20-40 min). The cause of the refusal of `verifyMonotonicity` / `verifyLemma` on `storeinv`

1. Add a print of the refusal branch to both functions under `KERN_DEBUG_TRUSTED`
   (following the `[dbg-ur-unver]` pattern).
2. Run `storeinv` and obtain WHY exactly these 4 steps were not taken.
3. **Acceptance:** for each of the 4 steps a concrete cause is named (an unexpanded `$x`,
   a reference to a step instead of a term, the shape of the hypotheses).
4. **Risk:** `lemma` is a rule with a subtree; "fixing" it by weakening would mean
   accepting an unverified subtree. Soundness matters more than the count.

### Block 3 (40-60 min). A breakdown of `premises_unbound` (`1/8` and `0/188`)

1. Dump the unbound `(asserted ...)` steps under `KERN_DEBUG_LIA` (`[dbg-unbound]`).
2. Compare with the contract of the task: what exactly is missing - expansion of
   `define-fun`, a sort, a `let`?
3. **Acceptance:** the class of the non-binding and its size are named.
4. **Risk:** "fixing" the binding by weakening = accepting a proof unrelated to the task
   condition. That is a false proof - the worst class of defect.

### Block 4 (60-80 min). Reporting: separate "steps" from "verified" (§1.4)

1. Introduce `unitres_verified` next to `unitres_checked` (or print
   `verified = steps - trusted`).
2. **Acceptance (arithmetic):** the sum of the report columns adds up to the number of
   steps on all 7 tasks; `smtlib-proof-check` is green.
3. **Risk:** low (printing), but changing the format means fixing the gate's parser IN THE
   SAME commit (otherwise the gate fails, exactly as happened with `#400`).

### Block 5 (80-100 min). Measurement and a decision on `def-axiom`

1. If Block 1 showed a checkable shape - implement the rule plus a two-sided test.
2. Measure `add_three.4_bit` before/after: trusted must become **fewer than 1020**,
   otherwise revert.
3. **Acceptance:** `smtlib-proof-check` green, 0 false alarms, 0 holes.
4. **Risk:** HIGH (a false proof is possible here). A negative control is mandatory: a
   faked `def-axiom` must be refused.

### Block 6 (100-120 min). Hygiene and handover

1. Regression: `ci-fast`, `xray-check`, `edge-cases`, the documentation gates.
2. Update the numbers SHIFTED by the new code (mutation sites, the test catalog) - along
   the lines named by `metrics-guard`.
3. `METRICS` §191 / §169, a journal entry, `NEXT_SESSION`, `make sync`.
4. **Acceptance:** `STATUS.md` open defects 0; `sync-check` idempotent.

---

## §4. Boundaries that will NOT disappear in these 120 minutes

1. **`trusted: 0` on all 7 tasks - do NOT promise it.** The residue of `add_three.4_bit`
   may require the context of definitions (`k!`-constants, `anchor` steps), and that is not
   a "rule" but a proof model.
2. **`premises_unbound` is a separate boundary.** It is not measured by the number of
   trusted steps and is not closed together with them.
3. **The full mutation sweep on the new code was not re-run** (23 min). The site count is
   the fact, but "100 %" refers to the committed log.
4. **The anti-cheat is noisy on arbitrary source** (its rules make sense for a TEST file) -
   the `--test-file` mode is not done (boundary `#429.2`).
5. **The `--xray` residue is calls and bitvectors.** On `cmark` there are 9 unverified, on
   `toolkit` 5; "100 %" there is reachable only by substituting a `_havoc` dummy, i.e. by
   cheating (class `#414`).

---

## §5. Commands that verify each claim (all of them READ-ONLY)

```bash
# 1. An audit of the 7 tasks (trusted, rules, false alarms)
make smtlib-proof-check

# 2. One task with a dump of the rules
KERN_DEBUG_TRUSTED=1 ./zig-out/bin/kernc prove \
    ~/.cache/kern/smtlib4/QF_BV/add_three.4_bit.smt2 | grep -E 'ПРУФ-ЧЕКЕР|dbg-trusted'

# 3. A dump of the premises of a trusted unit-resolution
KERN_DEBUG_TRUSTED=1 ./zig-out/bin/kernc prove \
    ~/.cache/kern/smtlib4/QF_AX/storeinv_t1_np_nf_ai_00002_001.cvc.smt2 | grep -E 'dbg-ur-unver|dbg-trusted'

# 4. Kernel tests (including the hardcore checker tests)
make test

# 5. Both --xray corpora (a solver is required)
make xray-check

# 6. The registry and the documentation
make registry && make docs-map-check && make status-check
make metrics-guard && make claims-audit && make sync-check

# 7. The state (generated - do not edit by hand)
make sync && grep -E 'Open technical defects|Highest defect' docs/STATUS.md
```

**Run with BOTH variables:** `ZIG=<binary>` and `ZIG_DIR=<directory>`.

---

## §6. Seven rules of work (six paid for in practice, the seventh - by this tack)

1. **Never run a check in the same batch as an edit to what it checks.** Paid for: two
   FALSE failures of `ci-fast` and `edge-cases`.
2. **Never commit while `tools/canfail.py` is running** (it mutates tracked files).
3. **Write large new files ATOMICALLY** (`cat > file <<'EOF'`), not as a series of
   `insert_line`.
4. **The real Zig 0.17 must come first in PATH** (pip-ziglang 0.13 breaks the build,
   defect #392).
5. **A new file with `fact:` anchors must be in `SURFACES`** (the orphan guard #246).
6. **A new CHECK goal requires a non-vacuous can-fail case and a `CASE_TARGET` entry.**
7. **NEW: any change that "improves" a number must have a BEFORE/AFTER measurement, and
   if there is no improvement it must be REVERTED with the diagnosis recorded IN THE
   CODE.** Paid for: flattening `or` (`2970 -> 3408`, reverted) and `pkill -f 'g431.sh'`,
   which killed its own command.
