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

Registry: **<!-- fact:registry_targets -->188 targets · <!-- fact:check_targets -->149 CHECK · <!-- fact:canfail_cases -->170 can-fail cases** (all CHECK targets have
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
| **3** | **#312** — the C extractor accepts only `int` parameters | a `cJSON` function with an `unsigned int` parameter is no longer `SKIP`; `codecheck` shows no regression; new CHECK + canfail | if widening the types breaks the proof checker on >2 fixtures, stage it: `size_t` first, then `unsigned`, then `long` |
| **4** | **#315** — `while` invariants (wire `chc.zig` into `--auto`) | `bisect.py` / `statistics.py`: either **0 candidates with a proof**, or a confirmed counterexample | **if the rule cannot be made sound — do not ship it.** Soundness outranks completeness |
| **5** | **#310** — `kernx graph` does not resolve imports outside the scanned root | on `lib/std/math` the edge count is **> 0**; `graph-parity` stays green | if resolution needs the whole `std` tree, document it as a boundary instead |
| **6** | Self-application: triage the **4 `[CRASH PATH]` + 15 `[BOUNDS PATH]`** candidates in our own code | each classified: false → fix + test; real → journal entry | — |
| **7** | **Target A: `TheAlgorithms/Rust`** — start with `src/math/catalan_numbers.rs`, `factorial.rs`, `binomial_coefficient.rs` | a verdict per function (`T` / `F` / `SKIP` with a reason); every `F` reproduced with `rustc -C overflow-checks=on` | no finding → report "not found" honestly; never invent one |
| **8** | **Target B: `py-evm`** — a third division semantics (EVM: `DIV` by 0 → 0, `SDIV` truncates, `MOD` sign from the dividend) | the `lang` architecture accepts a third language without breaking Python or C | if `lang` does not extend, that is an architecture defect — record it |

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
