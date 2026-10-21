# Real-world field test on external repositories (2026-10-21)

> **Scope and honesty.** This run used **real cloned GitHub repositories**, real
> `opencode` model calls and real KERN binaries. It is **not** a leaderboard and
> **not** a full 16-subsystem sweep: §4 lists exactly what was NOT executed and
> why. Artefacts: `/tmp/kern-megatest/` (outside the repository).

## 1. Real external sources

| Repository | Commit | Size |
|---|---|---|
| `github.com/mahmoud/boltons` | `4e5faa3` | 1.7 MB (shallow) |
| `github.com/Hejsil/zig-clap` | `05faf39` | 328 KB (shallow) |

Live models used: `opencode/deepseek-v4.1-flash-free` (and earlier
`glm-5.3-flash-free`, see `docs/LIVE_MODEL_EVAL.md`).

## 2. What was executed against this real data

### 2.1 `kernx graph` on an external Zig repository

```
kernx graph --root /tmp/kern-megatest/repos/zig-clap
nodes 12 | edges 1 | internal-edge hubs: clap/streaming.zig (1) | leaves 11
SCC cycles: 0
```

Honest reading: the scanner counts **internal** `@import` edges of the given
root, and `zig-clap` imports mostly `std` / relative paths that are not part of
the scanned set, so 11 of 12 modules are leaves. The number is a correct
property of the *scanner's scope*, not of the project's coupling. SCC analysis
(Tarjan over the emitted edges) found no cycles.

### 2.2 Real function from `boltons`, proven by KERN

`boltons/mathutils.py::clamp` is float-based with `±inf` defaults; an **integer
adaptation** was used (stated openly, attribution in the file header):

```python
# @kern:requires lo <= hi
# @kern:ensures result >= lo and result <= hi
def clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(x, hi))
```

Verdict: **T** - `[PASS] clamp_int: ДОКАЗАНО` (`trusted: 0`, `holes: 0`).

### 2.3 Live model refactor of that real function, checked by `--diff-equiv`

deepseek rewrote the body as three branches plus an extra `if lo > hi: return lo`.

```
[EQUIVALENT?] clamp_int: решатель доказал эквивалентность, но пруф-чекер
              отверг вывод (premises_unbound) - это НЕ расхождение
ИТОГО: эквивалентных 0 | эквивалентных без пруф-чекера 1 | разошедшихся 0 ...
RC=2
```

This is the honest boundary of the tool: Z3 established equivalence, but the
in-house proof checker does not accept the `ite`-heavy derivation, so KERN
**refuses to claim** equivalence and returns a non-zero code. It is neither a
false accusation nor a silent pass.

### 2.4 Real defect found by the field test

`kernc build <directory>` (the natural "pack this repo" gesture) exits 1 but
prints a **raw Zig stack trace** instead of a diagnostic:

```
$ kernc build /tmp/kern-megatest/repos/zig-clap
RC=1
error: IsDir
/home/.../lib/std/Io/File.zig:472:5: 0x108e928 in readStreaming (std.zig)
... 6 lines of internals
```

Filed as **#299**: a user-facing CLI must say "expected a manifest file, got a
directory", not leak `std` internals.

## 3. Numbers summary

| Check | Result |
|---|---|
| External Zig repo graph | 12 nodes / 1 internal edge / 0 SCC |
| Real function proven (T) | 1 of 1 (`clamp_int`) |
| Live-model refactor equivalence | 0 trusted / 1 solver-proved-but-unchecked / 0 diverged |
| Real CLI defects found | 1 (#299) |

## 4. NOT executed in this round (explicit)

| Planned | Why not |
|---|---|
| HumanEval / MBPP / EvalPlus leaderboard over 10 models | Requires ~10 models x 20+ tasks x verification; a run of that size needs hours and a token budget, and publishing a ranking from a partial run would be dishonest |
| Historical bug-fix commit pairs (before = F, after = T) | Needs per-commit contract authoring; not started |
| `trace_explorer.py` over 50+ arbitrary GitHub functions | The explorer builds its domain from QuixBugs-style `Input:`/`Precondition:` docstrings; on arbitrary code it finds no domain and reports nothing. Running it on adapted functions would be a synthetic task, which the brief forbids |
| `.kimg` packing of an external repo | `kernc build` expects a manifest file, not a directory; the manifest format for "pack a tree" is not documented in the CLI. See #299 |
| KERN-X quotas, KERNFS mount, C-ABI/QEMU, SARIF, live MCP JSON-RPC | Already covered by in-repo gates (`storage-check`, `c-abi-test`, `c-abi-threads`, `sarif-check`, `mcp-selftest`); re-running them here would duplicate evidence, not add external data |

## 5. Reproduce

```bash
git clone --depth 1 https://github.com/mahmoud/boltons /tmp/kern-megatest/repos/boltons
git clone --depth 1 https://github.com/Hejsil/zig-clap /tmp/kern-megatest/repos/zig-clap
./zig-out/bin/kernx graph --root /tmp/kern-megatest/repos/zig-clap > graph.json
python3 tools/kern_contracts.py /tmp/kern-megatest/clamp_real.py
python3 tools/kern_contracts.py --diff-equiv /tmp/kern-megatest/clamp_real.py /tmp/kern-megatest/clamp_opt_deepseek.py
```

## 6. Fixes made after this field test

### 6.1 #299 - `kernc build <directory>` now fails cleanly

```
$ kernc build /tmp/kern-megatest/repos/zig-clap
RC=2
[!] build: «/tmp/kern-megatest/repos/zig-clap» — это КАТАЛОГ, а нужен ФАЙЛ манифеста .kern
    Упаковка дерева появится как `kernc pack-dir`; сейчас см. docs/KIMG.md

$ kernc build              -> RC=2, «нужен путь к ФАЙЛУ манифеста .kern»
$ kernc build /tmp/nope.kern -> RC=2, «не удалось прочитать ...: FileNotFound»
```

No Zig stack trace, and the exit code is no longer 0 for a usage error.
Directory packing (`kernc pack-dir`) is **not** implemented - it is declared in
the message, not pretended to exist.

### 6.2 #300 - `trace_explorer.py` infers domains from Python annotations

When the QuixBugs-style `Input:` block is absent, the explorer now reads standard
annotations (`x: int`, `text: str`, `xs: list[int]`). Measured on the real
`boltons/strutils.py::removeprefix` extracted verbatim from the clone:

| Parameter | Domain before (AST only) | Domain with annotations |
|---|---|---|
| `text` | 60 values (mixed ints + strings) | **23 valid strings** |
| `prefix` | 37 values | **23 valid strings** |

The fallback makes the domain *smaller and valid*: mixed integer inputs only
produced `TypeError` and burned the exploration budget. End-to-end run on that
real function (buggy == reference, so only crashes/hangs can appear):

```
[s2] removeprefix  EXPLORED  250  lines=3/13  нет расхождения на 250 входах
=== STAGE-2 SUMMARY ===  EXPLORED 1
[OK] DIVERGED (живой вызов, 0 ложных по построению): 0/1
```

Honest reading: with an identical reference, zero divergence is the *expected*
outcome; the evidence here is that the typed domain was built at all and the
function was exercised on 250 real combinations instead of being skipped.

### 6.3 Model smoke test after the fixes (5 free models, one contract task)

| Model | `abs_capped` verdict |
|---|---|
| deepseek-v4.1-flash-free | T |
| glm-5.3-flash-free | T |
| mimo-v2.6-flash-free | T |
| minimax-m3.1-flash-free | T |
| nemotron-3.5-lightning-free | T |

All five produced `min(abs(x), 100)`. A simple task does not separate models -
that is itself a result, and it is why the earlier cheating experiment (C2 in
`docs/LIVE_MODEL_EVAL.md`) is the interesting one.

## 7. Known boundary, not a defect (#301): `premises_unbound`

On the live deepseek refactor of `clamp_int` (three branches instead of
`max(lo, min(x, hi))`), `--diff-equiv` returns:

```
[EQUIVALENT?] решатель доказал эквивалентность, но пруф-чекер отверг вывод
              (premises_unbound)
RC=2
```

Z3 proves equivalence; the in-house checker does not cover this `ite`-heavy
derivation, so KERN refuses to claim it. Extending `proof_check.zig` to accept
case-split derivations is a real project (the file is ~6k lines and the rule
must be sound, not permissive), therefore it is **not** attempted here. The
behaviour is recorded as a boundary: no false `EQUIVALENT`, no false `DIVERGED`.

## 8. Variant A - `kernc pack-dir`: external repository packed and verified

```
$ kernc pack-dir /tmp/kern-megatest/repos/zig-clap -o zigclap_v1.kimg
[OK] pack-dir: 20 файлов, 127046 байт -> zigclap_v1.kimg

$ kernc fsck zigclap_v1.kimg
  версия 1.3 · hash_algo 1 · флаги 0x00000000 · объектов 20
  проверено 20, ошибок 0                                   RC=0

$ kernc inspect zigclap_v1.kimg
  {"version":"1.3","hash_algo":1,"object_count":20,
   "objects":[{"path":"example/usage.zig",...,"digest":"3c5fabbcc64302d0..."}, ...]}

# правка одного файла в клоне -> новый образ -> посекционное сравнение
$ kernc pack-dir ... -o zigclap_v2.kimg      # 20 файлов, 127069 байт
$ kernc diff zigclap_v1.kimg zigclap_v2.kimg
  Merkle-корень различается
  объект изменён: build.zig                                RC=1
```

`pack-dir` is a separate command on purpose: `build` compiles a `.kern`
manifest (claims + artefacts), `pack-dir` packs a **directory tree** and claims
nothing about it. `.git/` is skipped, and the count of packed files is printed
together with the number of skipped ones, so a silent loss is visible.

### Defect #302 found by that first run

The first implementation reported **5 packed / 15 skipped** on a 20-file
repository: `walker` returns paths **relative to the opened directory**, while
`readFileAlloc` resolves them from the **current working directory**, so every
file below the top level failed to read. Because the summary prints the skipped
count, the loss was visible immediately instead of producing a 5-file "repo"
image. Fixed by joining the root; the re-run packs 20 files with 0 skipped.

## 9. Variant B - diagnosis of `premises_unbound` (not yet fixed)

Reproduction, with the checker's own debug output:

```
$ kernc prove /tmp/kern-megatest/clamp_diff.smt2      # the diff-equiv query
  [ПРУФ-ЧЕКЕР] шагов 220 | посылок 2/19 | mp 19 | резолюция 56 | Фаркаш 13 |
               rewrite(лин.) 39 | eq 18 | bool 43 | ДОВЕРЕННЫХ 13 | дыр 0
  [i] первое непроверенное правило: rewrite (13 шт.)
  [!] причина: посылки не привязаны к контракту (premises_unbound)
```

Facts, not guesses:

* the derivation is otherwise **fully checked**: 220 steps, `holes 0`,
  `concl_false = true`, 13 trusted lemmas (all arithmetic);
* the checker sees **19 premises** and binds only 2, with **1 unbound** - and a
  single unbound premise is enough to reject;
* the query asserts two `ite`-heavy equalities (`(= res_old ...)`, `(= res_new
  ...)`) plus `(assert (distinct res_old res_new))`;
* the plain (branch-free) `clamp_int` pair passes the same route unchanged, so
  the trigger is the `ite` form of the asserted equality, not diff-equiv itself.

So this is **not** "Z3 is wrong" and not "KERN lies": the binding rule for
`ite`-shaped premises is missing. Two sound ways forward (a decision is needed):

1. **Case-split in the frontend** (smaller, no checker changes): emit one query
   per branch combination with linearised bodies, so no `ite` reaches the
   checker; all UNSAT => equivalent. Requires extracting guards from the AST,
   and an exhaustiveness argument for the branch chain.
2. **Teach the checker** a sound `ite`-premise rule: a premise containing `ite`
   is bound when both case instances are bound. Deeper change inside
   `proof_check.zig` (~6k lines) and must be proved sound, not permissive.

## 10. Variant B - deeper than `ite`: diff-equiv can never be TRUSTED (#303)

Three experiments, all with the checker's own counters (run with `.venv/bin` in
`PATH`, otherwise `kernc` reports "z3 недоступен"):

| Query shape | Checker verdict | Premise binding |
|---|---|---|
| original: two `(= res_* <ite body>)` premises + `(distinct res_old res_new)` | `ДОКАЗАНО (допущено)`, 220 steps, holes 0 | **2/19**, unbound 1 -> rejected |
| inline: goal `(distinct <body_old> <body_new>)`, no extra premises | `ДОКАЗАНО (допущено)`, 185 steps, holes 0 | **0/16** -> rejected |
| trivial linear control: guards asserted, goal `(distinct x x)` | `ДОКАЗАНО (допущено)`, 3 steps, holes 0 | **0/1** -> rejected |

The control is the decisive one. It contains no `ite` at all, yet the checker
still rejects, because **not a single premise is bound**: Z3's proof of an UNSAT
goal does not mention premises that are irrelevant to it, and the checker requires
every premise to be bound. Contract-shaped proofs (where the premises *are* the
contract clauses) always use their premises, so the rule was never exercised this
way; for a goal-only query it is impossible to satisfy.

Consequence, stated plainly: **`--diff-equiv` can detect divergence (SAT case,
which is correct and useful) but can never produce a trusted `EQUIVALENT`.** It
returns rc=2 with "solver proved it, checker rejected". This is a real defect,
not a nuance of `ite` - my earlier reading of it as an `ite`-specific gap was
wrong, and this is the corrected diagnosis.

### The fix is already designed for this: `QueryKind`

KERN already distinguishes query kinds (`refutation` / `satisfiability` /
`equivalence`, see `src/next/state_axes.zig` and `AdmissionGate`). The premise
rule belongs to the **refutation** kind, where the invariant "every premise is
bound" is what stops a vacuous proof. For an **equivalence** query there are no
contract premises to bind by construction, so the rule must not apply.

Plan (not implemented here, on purpose - it changes what the checker accepts):

1. `kernc prove --query-kind equivalence` (default stays `refutation`).
2. In the checker, unbound premises are fatal only for `refutation`; for
   `equivalence` the verdict is reported with the premise counters visible and
   `trusted: 0` semantics unchanged (no trusted lemmas added).
3. A can-fail case: an equivalence query whose proof *does* rely on a premise
   that is not bound must still be rejected, and a genuinely divergent pair must
   still be reported `DIVERGED`.
4. `tools/kern_contracts.py --diff-equiv` passes the kind explicitly and stops
   labelling the result "EQUIVALENT?" without saying which kind was used.

## 11. Variant B implemented: `QueryKind` separation, verified on the live refactor

What changed (4 steps of the §10 plan):

1. `proof_check.zig` gained `QueryKind { refutation, equivalence }` and
   `ProofVerdict.premises_required`. `checksPass()` skips the premise rule only
   when it is not required; `failureReason()` likewise. `verifyProof()` is kept
   as a wrapper over the new `verifyProofKind()` with `.refutation`, so every
   existing call site and test keeps its old behaviour.
2. `kernc prove [--query-kind refutation|equivalence] <file.smt2>` passes the
   kind explicitly and prints it (`вид запроса: ... | привязка посылок
   обязательна: да/нет`).
3. `tools/kern_contracts.py --diff-equiv` sends `--query-kind equivalence`.
4. `make diff-equiv` positive control was **strengthened**: the identical-file
   pair must now yield rc=0 (trusted EQUIVALENT), not merely "not DIVERGED".

Measured on the real DeepSeek refactor of `boltons::clamp_int`:

```
$ python3 tools/kern_contracts.py --diff-equiv clamp_real.py clamp_opt_deepseek.py
  [EQUIVALENT] clamp_int: рефакторинг математически эквивалентен на всём домене Z
               (пруф-чекер принял)
ИТОГО: эквивалентных 1 | без пруф-чекера 0 | разошедшихся 0 | ...   RC=0
```

And the contract path is untouched - the same query as `refutation` is still
rejected, which is what protects contract proofs from vacuity:

```
$ kernc prove clamp_inline.smt2
  [i] вид запроса: refutation | привязка посылок обязательна: да
  [!] причина: посылки не привязаны к контракту (premises_unbound)   RC=2
```

Safety net, not a promise: `holes`, `mp_bad`, `unitres_bad`, `farkas_bad`,
`rewrite_bad` and `proof_concludes_false` remain fatal in **both** kinds, and a
unit test pins exactly that (a hole or a faked step still fails an equivalence
verdict). Two can-fail cases were added/verified:

* `query-kind-leak` - `premises_required = true` for equivalence makes
  `make diff-equiv` red (non-vacuous, rc=2 in 1 s);
* `diff-equiv` - divergence declared equivalent makes the same target red.

### Defect #304 found while wiring step 2

`kernc prove` took the file path as `args[2]`, so `prove --query-kind
 equivalence file.smt2` tried to read the **flag** as a file (Zig stack trace).
The positional argument is now located properly (flags and the `--query-kind`
value are skipped), and a missing file reports cleanly with rc=2.

## 12. Four languages in the code-checking corpus (#305)

The Phase 4B corpus had four Zig and two C files returning `N (no functions)`.
The cause was **not** a missing capability: `tools/kern_contracts.py` already
checks Python, Zig, C and Rust contracts with **machine-type bounds**
(`i8/i32/u32/i64/usize`; see `examples/contracts_demo.{py,zig,c,rs}` and
`TYPE_RANGE`). The corpus files simply carried no `@kern:` annotations, and their
expectations recorded "unsupported".

They now carry real contracts, and two Rust cases were added:

| File | Language | Verdict | Witness |
|---|---|---|---|
| `zig_clean.zig` | Zig | **T** | `ensures result == a + b` proved |
| `zig_div.zig` | Zig | **F** | unguarded `a / b` -> division-by-zero obligation |
| `c_clean.c` | C | **T** | proved with `int` bounds |
| `c_unguarded.c` | C | **F** | unguarded `a / b` in C |
| `rust_clean.rs` | Rust | **T** | proved |
| `rust_overflow.rs` | Rust | **F** | **i32 overflow**: `a = 2147483647, b = 1 -> 2147483648` |

Matrix before and after:

```
before:  TP=2, TN=2, FP=0, FN=0, UNKNOWN=8
now:     TP=5, TN=5, FP=0, FN=0, UNKNOWN=4
```

The remaining four `UNKNOWN` are honest and named in
`audits/codecheck/README.md`: nonlinearity, recursion unrolling, slice-index
reasoning, and a loop body (needs CHC). `FP = 0` and `FN = 0` are unchanged -
the hard gate is not weakened by covering more languages.

Rust detail worth recording: a body written as a bare tail expression
(`a + b`) is rejected as unsupported (`оператор rust: 'a + b'`); the frontend
expects an explicit `return`. The corpus uses `return a + b;`, and the limitation
is noted rather than hidden.

## 13. Two claims re-checked in the repository

* `HumanEval+` baseline **exists**: `docs/ATTESTATION_PASSPORT.md` records
  `0.524 base / 0.500 plus` for 164 tasks, and `docs/CAPABILITIES.md` states the
  measured effect of the static gate on `pass@1` is **0** with the reason: a
  one-shot filter runs *before* the tests, so raising `pass@1` needs an
  **iterative repair loop** driven by counterexamples. That loop is the next
  piece of work, not something claimed here.
* `#303` (`QueryKind.equivalence`) was implemented and verified in commit
  `afdb61b` - see section 11.
