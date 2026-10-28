# PLAN v2.6.4 — honest corrections and capability growth

Status: **ACTIVE** (opened 2026-10-21 on `b7ee734`, version `v2.6.3`).

This plan is the follow-up to [`PLAN_v2.5.3.md`](PLAN_v2.5.3.md) (which is
COMPLETED). It was opened because the v2.6.3 cycle produced three things that need
to be carried forward: an upstream contribution, a self-inflicted documentation
error, and a measured list of open limitations.

---

## §0 State at the start of this cycle

| Closed | How it is proven |
|:--|:--|
| **#317** false `PROVEN` on integer division (soundness) | language-aware translator; `arith_semantics_check.py` **0 mismatches / 840**; validated against Zig `@divFloor`/`@divTrunc` (**0 / 1640 pairs**) |
| **#318** false `[CRASH PATH]` on a guarded division | path conditions resolved per position; `xray_check.sh` locks both cases |
| **Upstream PR** [`TheAlgorithms/C#1595`](https://github.com/TheAlgorithms/C/pull/1595) | opened, `+7 −0`, one file, CI `triage` success, `mergeable: true` |
| **Release v2.6.3** | signed tag; release published with **4 assets including `kern.intoto.jsonl` and `.sig`** — the attestation is attached for the first time |
| **Letter to the reporter** | sent by the operator (M. Brighindi, who reported #317) |

Registry: **<!-- fact:registry_targets -->231 targets · <!-- fact:check_targets -->178 CHECK · <!-- fact:canfail_cases -->216 can-fail cases** (all CHECK targets have
a non-vacuous case).

### The new defect this cycle starts with

**#320 — a published claim that did not survive re-verification.** The sweep
section of [`SHADOW_AUDIT_EXAMPLE.md`](SHADOW_AUDIT_EXAMPLE.md) stated that
`prime_sieve.c:44` (`for (int i = 0; i <= size; i++)`) is a **REAL logic defect**
and printed `count(arr, size=10) = 5`. Re-running it against the **real** prime
array from the same program gives `count(arr, 10) = 4`:

```
индексы:  0=0 1=0 2=1 3=1 5=1 7=1 10=0 11=1 13=1
count(arr, 3)  = 2   vs "first 3 elements"  = 1   DIFFER
count(arr, 7)  = 4   vs "first 7"           = 3   DIFFER
count(arr, 10) = 4   vs "first 10"          = 4   same    ← the test uses 10
count(arr, 11) = 5   vs "first 11"          = 4   DIFFER
count(arr, 97) = 25  vs "first 97"          = 24  DIFFER
```

The number `5` came from a **synthetic** array (with `arr[10] = 1`), not from the
real one. And the source is **self-contradictory** about the contract:

| Where | Wording | Reading |
|:--|:--|:--|
| doc block of `count` | `@param size denotes **upto which** prime numbers are to be found out` | **inclusive** → `i <= size` is **correct** |
| test comment | `const int size = 10; /* **array size** */` | **exclusive** → off-by-one |

The test uses `size = 10`, which is exactly the value that cannot distinguish the
two readings. **Verdict: not a bug — an ambiguous contract.** No upstream PR will
be opened for it.

---

## §1 Principles (unchanged, plus one addition)

1. A new CHECK target ships only with its own non-vacuous canfail case.
2. A false accusation is worse than a miss — `FP = 0` is a gate, not a metric.
3. `verified` in the bibliography only with a Crossref snapshot.
4. The second agent is a **read-only reviewer** in a separate worktree.
5. `v2.5.x` / `v2.6.x` tags are immutable; every release is a new tag.
6. After every step: `ci-fast` · `sync` · `metrics-guard` · `docs-parity` ·
   `evidence-gate` · `make seal`.
7. **NEW: every numeric claim in a document must have a committed harness that
   reproduces it.** Otherwise it is text, not evidence. #320 is the reason.


---

## §2 Queue

| # | Task | Acceptance | Kill criteria |
|:--|:--|:--|:--|
| **1** | Operator: revoke the token exposed in chat; store the new one in `~/.config/kern/gh_token` (mode 600) | token absent from all tracked files; `secrets-check` 0 findings | — |
| **2** | **Fix #320**: correct the claim in `SHADOW_AUDIT_EXAMPLE.md` and commit the harness that produced the numbers | the withdrawn claim appears **only inside the correction block** (never as a bare verdict); `docs/evidence/prime_sieve/reproduce.sh` reproduces every number in the table | — |
| **3** | **#312 + #321** — the C extractor accepts only `int` parameters | ✅ **DONE** — `unsigned int`, `long long`, `unsigned long`, `unsigned short`, `unsigned char`, `int32_t`, `size_t`, … all receive verdicts; the **return type** is canonicalised too (#321 had made the overflow obligation vanish silently); `char`/`float` SKIP with a reason. Gate `make c-types-check` + non-vacuous case `c-types` (both sabotages verified red). Ground truth: `gcc` → `4294967295 + 1 = 0`, contract violated | — |
| **4** | **#315** — `while` invariants (wire `chc.zig` into `--auto`) | ⚠️ **PARTIAL — kill criterion applied**. `ast.While` was not handled at all: its body was walked with no narrowing, so `bisect.py` accused `a[mid]` with the unreachable counterexample `kern_len_a = 0, mid = -1`. Now the loop **condition** goes into the path (sound: it holds at every iteration entry) and findings inside a `while` body print as **`[BOUNDS UNKNOWN]` with the reason** instead of a fake counterexample. Length aliases (`n = len(arr)`) are bound to the symbolic length, which removed the false `harmonic_mean` accusation. Measured: `bisect.py` 4 candidates → 4 honest UNKNOWN; `statistics.py` 16 → 11 findings; `heapq.py` PATH 4 / UNKNOWN 18 / 35 "length unknown" / CRASH 0. **Acceptance ("0 candidates with a proof") is NOT met** — a full invariant needs CHC/Horn (`src/verifier/chc.zig`), which is not wired into this analysis — so no rule extension was shipped, only the sound degradation. Two coverage gaps found and fixed on the way (**#326**) | if the rule cannot be made sound — do not ship it |
| **5** | **#310** — `kernx graph` does not resolve imports outside the scanned root | ✅ **DONE** — external `@import` targets are no longer dropped: the JSON always carries `edges_external` (**59** on `lib/std/math`, where the old output read "0 edges"), and `--external` materialises them as nodes (`"external": true`) so the graph is closed (66 nodes, 59 edges). No regression on `src` (88 nodes, 70 edges, 0 external). A serialisation defect was found and fixed on the way: with zero internal edges a leading comma produced invalid JSON; `graph-check` now asserts both | — |
| **6** | Self-application: triage the **4 `[CRASH PATH]` + 15 `[BOUNDS PATH]`** candidates in our own code | ✅ **DONE** — `--xray tools/` over all **91** Python files gave **3 unique `[CRASH PATH]` + 15 `[BOUNDS PATH]`** (the 4th crash line was the summary restating the first). Triage: **1 real defect → #323** (`N=0` from the environment → `ZeroDivisionError`, reproduced live, fixed with an entry check); **2 intentional fixtures** (`div_ok`/`div_bad` in `deal_contracts.py`, which carry `@deal.pre(lambda a, b: b != 0)`); **15 bounds candidates all guarded** → recorded as the analysis boundary **#322** (Python guards are not modelled: early exit on a length, conditional expressions, decorator preconditions). Evidence: `docs/evidence/self_scan/` | — |
| **7** | **Target A: `TheAlgorithms/Rust`** — start with `src/math/catalan_numbers.rs`, `factorial.rs`, `binomial_coefficient.rs` | ✅ **DONE — one real defect found (#324)**. Verdicts: `catalan_numbers.rs` 1/2 checked, 1 SKIP, 0 findings — **the Rust twin does NOT have the C bug**: it is a different algorithm (DP with modulo) and its own test covers `n = 0`; `factorial.rs` 2/7 checked, 5 SKIP, 0 findings (the u64 limit at `21!` is not modelled — BV treats wrap as semantics); `binomial_coefficient.rs` 0/8 checked, 8 SKIP → a **shadow contract on the verbatim sub-expression** `n - i` refuted: `[FAIL] ПЕРЕПОЛНЕНИЕ типа u64`, counterexample `n = 0, i = 1`, reachable as **`binom(0, 2)`**; `rustc` ground truth: debug `panic: attempt to subtract with overflow` (rc=101), release silent garbage. All 7 upstream tests use `k <= n`. Fix submitted upstream: **[`TheAlgorithms/Rust#1075`](https://github.com/TheAlgorithms/Rust/pull/1075)** (+16 −0, one file, with the regression test `test_binom_k_greater_than_n`; verified against the seven existing expectations — no regression). Evidence: `docs/evidence/thealgorithms_rust/`. Side finding: **#325** (`{` on the next line is invisible to the Rust/Zig extractor) | — |
| **8** | **Target B: `py-evm`** — a third division semantics (EVM: `DIV` by 0 → 0, `SDIV` truncates, `MOD` sign from the dividend) | ⚠️ **MEASURED, with a real blocker found (#327)**. Source: `ethereum/py-evm` `eth/vm/logic/arithmetic.py` @ `ffce74f`, verbatim in `docs/evidence/step8_evm/`. The third semantics is confirmed: `div` is `if denominator == 0: result = 0` — division by zero is **defined**, not an error; `sdiv` truncates via `pos_or_neg * (abs(n) // abs(d))`; `smod` takes the sign from the dividend. **Architecture: the semantics is selected in ONE dispatch point** (`expr_smt`, the `if lang == "python"` branch) plus the divisor collector, with `_CURRENT_LANG` set in 3 places — so a third mode is a contained change, not a rewrite. **But it cannot be validated today:** the divisor obligation in Python **ignores guards**, so `return 0 if b == 0 else a // b` is falsely accused (`[FAIL] ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ (делитель: b)`, counterexample `a = 0, b = 0`) — and the `if` form is accused too. For C-like code this was fixed in #318; for Python it was not. Recorded as **#327 (OPEN)** with the reproduction and the root cause | — |

### Removed from the queue

- ~~Second upstream PR: `prime_sieve.c` off-by-one~~ — **withdrawn**, see #320: the
  claim is not supported by measurement, so a PR would be a false report.

---

## §3 Repository targets, ranked with evidence

| Target | Fit | Why |
|:--|:--|:--|
| **`TheAlgorithms/Rust`** (`fed66cb`) | ✅ **1st** | 423 `.rs` files, **87 in `src/math/`**; integer `i32`/`u32` arithmetic is in the subset; contains the **Rust twin** of the bug found in C (`catalan_numbers.rs`, `factorial.rs`) |
| **`py-evm` / `vyper`** | ✅ 2nd | a third division semantics — the real test of whether `lang` extends |
| **`DaveGamble/cJSON`** (`6d9f244`) | ⚠️ 3rd | **blocked by #312** (`unsigned` parameters) — do step 3 first; hex logic already PROVEN here (227 steps) |
| **Zig `lib/std/math`** | ⚠️ | excellent as an **oracle** (`@divFloor`/`@divTrunc` already used for #317), weak as a hunt |
| **`raysan5/raylib`** (`1026cb9`) | ❌ **excluded** | `raymath.h`: 3197 lines, 27 `float` + 71 `Vector3/Matrix/Quaternion` functions, **0 functions with an `int` parameter** → outside the subset. `Vector3Normalize` **already has** `if (length != 0.0f)`, so the assumed defect is not there |
| `TheAlgorithms/Python` | ❌ | 45 modules → 0 divergences; Python has no overflow class |
| `madler/zlib`, CPython stdlib | ❌ | fuzzed 24/7 by OSS-Fuzz; every candidate was a documented precondition |

**Measured funnel on external code** (from `audits/README.md`, unchanged): `requests`,
`humanize`, `flask` → **0** `@kern:` annotations, **0 of 715** functions inside the
extractor subset. This is why a blind "run it over 50 repos" produces a table of
zeros, and why the contract-driven route (one function, one rule) is the only one
that yields verdicts.

---

## §4 Open limitations (not fixed in this cycle, recorded)

- **#307** — an off-by-one involving a power with a variable exponent is outside the subset.
- **#315** — if step 4 fails its kill criteria, `while` invariants stay unsupported.
- **Windows** is not supported: three POSIX blockers plus `-lsqlite3` (`PLATFORMS.md`).
- **Float and strings** are detectors, not proofs.
- The signature is the owner's Ed25519, not a third-party builder (Sigstore/Rekor in backlog).
- **`--auto` finds candidates, not verdicts** for C-like code: control flow and loop
  invariants are not modelled, and the tool says so in its own output.

---

## §5 Not doing

A blind "find vulnerabilities in repositories" sweep · `raylib` (see §3) ·
`@kern:necessary` / `@kern:possible` · auto-writing `@kern:requires` ·
`harness2` as a dependency · rewriting git history · PDFs in the repository.

---

## §6 How to resume

```bash
cd /path/to/kern
export PATH="$HOME/opt/zig-x86_64-linux-0.17.0:$PWD/.venv/bin:$PATH"
export ZIG="$HOME/opt/zig-x86_64-linux-0.17.0/zig"

make ci-fast && make metrics-guard && make sync-check && make docs-parity
make evidence-gate && make seal
```

Order of work: **test → code → canfail → sync → seal → tag**. The cycle closes with
`v2.6.4` once steps 1–3 are done; steps 4–8 may ship in later patches, each with its
own tag.

---

## §7 Definition of Done for this cycle

1. `docs/SHADOW_AUDIT_EXAMPLE.md` contains no claim that a committed harness cannot reproduce.
2. `#320` is recorded in the journal (RU + EN) with the measurement.
3. A C function with an `unsigned` / `size_t` parameter receives a verdict (not `SKIP`).
4. `codecheck` still reports `FP = 0` and `FN = 0`.
5. Every new CHECK target has a non-vacuous canfail case (registry stays at 100% coverage).
6. `make seal` is green and the attestation verifies against `docs/keys/kern-owner.pub`.
