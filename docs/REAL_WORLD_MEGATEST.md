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
