# KERN — a zero-trust verification gateway for AI-generated code

[![Zig 0.17.0](https://img.shields.io/badge/Zig-0.17.0-F7A41D?logo=zig&logoColor=white)](https://ziglang.org/)
[![Core tests](https://img.shields.io/badge/core_tests-191%2F191-brightgreen)](src/)
[![KERN-Next tests](https://img.shields.io/badge/KERN--Next_tests-37%2F37-brightgreen)](src/next/)
[![Lean 4](https://img.shields.io/badge/Lean_4-7_files_%C2%B7_32_theorems_%C2%B7_0_sorry-blue)](formal/)
[![MC/DC](https://img.shields.io/badge/MC%2FDC_decision_coverage-100%25-brightgreen)](src/cov.zig)
[![Can-fail](https://img.shields.io/badge/can--fail_harness-60%2F60-blueviolet)](tools/canfail.py)
[![Cross-arch](https://img.shields.io/badge/ARM64_%2B_POWERPC64-191%2F191-informational)](#cross-architecture)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**A green CI means nothing if the test itself cannot fail.**

KERN is an L0–L5 verification gateway that sits between an AI coding agent and your
repository. It replaces the boolean illusion of "tests passed" with a
four-valued verdict backed by an SMT solver and formal proofs — and it refuses
to open the gate unless the claim is *machine-checkable*.

Written in **Zig 0.17**, verified in **Lean 4**, powered by **Z3**.

---

## The problem: the epistemic gap

AI agents now write code faster than humans can review it. Under pressure to get a
green pipeline, they produce two failure modes that no ordinary CI can see:

| Failure mode | What CI sees | What actually happened |
|:--|:--|:--|
| **Vacuous test** | ✅ `1 passed` | The test contains no `assert`. It cannot fail. |
| **Hallucinated fix** | ✅ `1 passed` | The edge case (`amount = -1`) was never sampled. |

Both are invisible to `pytest`, `jest`, or any test-counting tool, because both
produce **exit code 0**.

KERN attacks the gap from two sides:

1. **Can-fail discipline** — every check in KERN's own suite must be *proven
   capable of failing*. A harness (`tools/canfail.py`) deliberately injects a
   fault and requires the check to go red. 60 checks, 60 proven non-vacuous.
2. **Machine contracts** — a claim becomes `e = 1` only if an external trusted
   checker (Z3) proves it, or if a reproducible execution record backs it.
   Prose is never proof.

---

## See it in 15 seconds

```bash
make run-example
```

The example (`examples/toy_ai_hallucination/`) simulates an agent that was asked to
fix a withdrawal function. The agent "fixed" it — but dropped the check for
negative amounts — and wrote a test with **no assertions** so CI would go green.

```
=== [1] Ordinary CI: pytest on the agent's "test" ===
1 passed in 0.01s                      <-- green. The bug ships to production.

=== [3] KERN: Truth Gate (the verdict comes from Z3) ===
  claim `withdraw never increases the balance`: declared status = N
    contract `.../contract_refuted.smt2`: SAT -> e=0 (F) COUNTEREXAMPLE
  claim `fixed withdraw never increases the balance`: declared status = T
    contract `.../contract_fixed.smt2`: UNSAT -> e=1 (T) PROVED
[i] TOTAL: proved 1, counterexamples 1, without contract 0
[i] e=1 is granted ONLY by the solver verdict. Claims without a bound
    contract stay at e=0 — that is the honest status.
```

The solver did not sample inputs. It quantified over **all** of `ℤ` and returned a
counterexample (`amount = -1` makes the balance *grow* on a withdrawal).

---

## Core ideas

### Belnap B₄ logic — results accumulate, they never overwrite

Each claim carries two independent support channels: `p` (positive) and `n`
(negative).

| `(p, n)` | Value | Meaning |
|:--|:--|:--|
| `(0,0)` | **N** | no evidence |
| `(1,0)` | **T** | proven / positive only |
| `(0,1)` | **F** | refuted / negative only |
| `(1,1)` | **B** | **conflict** — positive *and* negative evidence coexist |

A newly passing test **joins** with history, it does not replace it:

```
JOIN_K(T, F) = B        -- a conflict can never be silently resolved into a pass
```

This is the mechanism that makes "one green run" unable to hide a previously
observed failure. (Defect #46 in the project's own registry was exactly the
opposite behaviour — status overwrite — and was found by the can-fail harness.)

### The Gate is closed by default

```
e = 1  <=>  policy allows  AND  provenance hash matches  AND  checker verdict = SUCCESS
            AND  Belnap status = T  AND  coverage complete  AND  no scope ambiguity
```

Timeout, missing solver, unknown answer, or a fake textual witness all yield
`e = 0`. The AI's own `witness_payload` **never** influences the verdict — only
the external trusted checker does.

---

## Architecture (L0 – L5)

| Layer | What it is |
|:--|:--|
| **L0** — container | `.kimg`: 128-byte little-endian header, 96-byte object descriptors, Merkle root, `comptime` layout invariants, atomic write (tmp + `fsync` + `rename` + directory `fsync`) |
| **L1** — crypto | SHA-256 over every payload, checked on read → `PayloadTampered`; Merkle root over the descriptor table |
| **L2** — KERNFS | read-only virtual filesystem over a sealed image; path-traversal and NUL-injection rejected; writes return `AccessDenied` |
| **L3** — Truth Gate | Belnap B₄ accumulator, admission policy, trusted-checker-only verdicts |
| **L4** — SMT theories | Z3 bridge via child processes (0 FD leaks, hard timeout, solver pool). QF_LIA/BV, QF_AX (arrays), CHC/Horn (loop invariants), QF_S (strings), QF_FP, CEGIS synthesis, UNSAT-core fault localisation |
| **L5** — formal proofs | 32 theorems in 7 Lean 4 files, 0 `sorry` |

The verification engine (`kernx`, "KERN-Next") reads a `.kern` project DSL and
produces a SQLite catalogue, snapshots, diffs, reports and an agent hand-off
packet.


---

## Measured, not claimed

Everything below was produced by a real run on Zig 0.17.0. Reproduce with
`make test-all`, `make audit-manifest`, `make canfail`.

### Core health

| Check | Result |
|:--|:--|
| Core test suite (Debug + ReleaseSafe) | **191 / 191** |
| Core test suite with `z3` in `PATH` | **195 / 195** (the extra 4 exercise the solver) |
| KERN-Next test suite | **37 / 37** |
| Memory leaks (GeneralPurposeAllocator) | **0 bytes** |
| Undefined behaviour (ReleaseSafe) | **none detected** |
| File-descriptor leaks (50 solver requests, `NOFILE=20`) | **0** |
| Zombie processes | **0** |
| Decision coverage (MC/DC-style, instrumented) | **100.0 %** (30 / 30) |
| Mutation score (Zig-native mutator) | **92.5 %** (37 / 40 killed; 3 provably equivalent) |
| Can-fail harness | **60 non-vacuous / 0 vacuous** |

### Cross-architecture

| Target | Property under test | Result |
|:--|:--|:--|
| x86_64 | TSO memory model | **191 / 191** |
| **ARM64** (QEMU) | strict alignment — no `Bus Error` | **191 / 191** |
| **POWERPC64** (QEMU) | **big-endian** byte order | **191 / 191** |

### External benchmarks

| Benchmark | Result | Needs a model? |
|:--|:--|:--|
| **QuixBugs** (real buggy algorithms) | **31 / 31** bugs found | no |
| **Hacker's Delight / Alive2-style** | **8 / 8** (6 proved, 2 counterexamples) | no |
| **SWE-bench Lite** (Docker harness) | **3 / 3 resolved**, 0 infra failures | no |
| **Refactory** (student solutions) | 1438 / 1782 bugs detected | no |
| **CHC / Horn** (loop invariants) | **11 / 11** | no |
| **SMT-LIB** (official suite) | 1104 / 1104 verdicts matched, **0 divergences**, **0 false accepts** | no |
| **HumanEval / HumanEval+** (EvalPlus) | 0.524 / 0.500 | yes (API) |
| **MBPP / MBPP+** (EvalPlus) | 0.812 / 0.698 | yes (API) |

> **Honest note on the gate.** In the HumanEval experiment the static gate blocked
> 55 samples — **all 55 genuinely failed**, zero false blocks (100 % precision),
> but it did **not** raise `pass@1`. A static gate fires before execution; it
> cannot fix logic. Raising the score requires execution evidence, not AST
> inspection. This is stated because the alternative — reporting a flattering
> number — would violate the project's own rule.

### Performance

| Path | Throughput |
|:--|:--|
| Raw zero-copy addressing (`/raw/`) | ~76 GB/s (memory-bus bound) |
| Safe read with SHA-256 verification | ~231 MB/s |
| Random access, 1 000 000-object image | ~0.0006 ms |

The 330x gap is the cost of integrity checking every byte — and it is the reason
a tampered payload cannot be served.

### Reproducibility (measured)

Two clean builds each (`rm -rf .zig-cache` in between):

| Configuration | Build 1 | Build 2 | Verdict |
|:--|:--|:--|:--|
| Debug (default) | `35748ca0...` | `9dc521bb...` | differs (non-deterministic DWARF in Zig 0.17) |
| **ReleaseFast** | `e6c8e38c...` | `e6c8e38c...` | **identical** |
| **Hermetic** (ReleaseSafe, static musl) | `e4cc7449...` | `e4cc7449...` | **identical** |


---

## Quick start

**Requirements:** Zig **0.17.0**, Python 3.12+, `z3` (via `pip install z3-solver`),
and Lean 4 (only for `formal/`).

```bash
# 1. Toolchain (Zig 0.17.0)
export PATH="$HOME/opt/zig-x86_64-linux-0.17.0:$PATH"

# 2. Build: kernc (core CLI), kernx (KERN-Next), kern-attack (attack demo)
zig build

# 3. Core test suites
zig build test          # 191 core tests
zig build test-next     # 37 KERN-Next tests

# 4. The 15-second demo: green CI vs. mathematics
make run-example

# 5. Prove a contract with real Z3
uv pip install --python .venv/bin/python z3-solver
./zig-out/bin/kernc prove formal/example.smt2

# 6. Formal proofs (Lean 4): 7 files, 32 theorems, 0 sorry
./formal/setup_mathlib.sh    # one-time: fetch prebuilt Mathlib
./formal/check.sh

# 7. Full qualification manifest — every line is a real run
make audit-manifest
```

**One command for everything:**

```bash
make test-all      # build + tests + UB detector + SMT + perf + mutation
make canfail       # prove that every check is capable of failing
```

### Docker

```bash
docker build -t kern:2.0 .
docker run --rm kern:2.0                        # integrity check on the golden image
docker run --rm kern:2.0 verify /kern/toy.kimg  # run the Truth Gate
```

---

## Certification package

For safety-critical and regulated environments (`formal/certification/`):

| Document | Purpose |
|:--|:--|
| `TOR.md` | Tool Operational Requirements — 53 atomic requirements |
| `TRACEABILITY_MATRIX.md` / `.csv` | every requirement mapped to its test and source |
| `SOUNDNESS_ARGUMENT.md` | why KERN cannot report a false negative |
| `SECURITY_TARGET.md` | security functional requirements + formal model |
| `TAS.md` | Tool Accomplishment Summary |
| `KNOWN_LIMITATIONS.md` | **25 documented limitations**, each with a detection method |

Mapped to **DO-178C / DO-333 (DAL A)**, **ISO 26262 (ASIL D)**, **Common Criteria
EAL6+/EAL7**, **FIPS 140-3** and **ACID / crash consistency** — with the evidence
file backing each row.

---

## Honest limitations

This project's own rule is that a claim without evidence is not a claim. So:

- **Z3 is an external dependency.** If it is absent, the Gate stays closed
  (`e = 0`) — safe degradation, not a failure. The tool never lies about it.
- **Debug builds are not bit-reproducible** under Zig 0.17 (non-deterministic
  DWARF). Attested artefacts are ReleaseFast. See the table above.
- **The static gate does not raise `pass@1`.** It has 100 % precision and ~70 %
  recall on the HumanEval set; it removes bad code, it does not improve good code.
- **Alethe/LFSC proof objects are not implemented.** `src/verifier/proof_check.zig`
  performs structural validation only — not a full independent proof checker.
- **No hardware attestation.** The Ed25519 ownership/attestation pipeline is
  implemented in software; there is no TPM/SGX integration (no such hardware here).
- **SLSA attestation is unsigned** (no `cosign` in the environment) — structurally
  valid, but not SLSA Level 3.
- **Object compression (zstd) is declared in the format but not implemented.**
- The full list lives in `formal/certification/KNOWN_LIMITATIONS.md` and
  `REVISION/HONEST_CAPABILITY_STATUS.md`.

---

## Repository layout

```
src/            Zig core: .kimg format, KERNFS, Truth Gate, Z3 bridge, 5 SMT theories
src/next/       KERN-Next: .kern DSL, SQLite catalogue, snapshots, agent hand-off
formal/         Lean 4 proofs (32 theorems) + certification package
examples/       toy_ai_hallucination/ — the "green CI" demo
tools/          can-fail harness, mutation tester, benchmarks, cross-arch runner
docs/           PROJECT_SPECIFICATION.md, METRICS.md, TEST_CATALOG.md, evidence/
REVISION/       honest capability status + defect registry (#1-#59)
```

**Key documents**

| Document | What's inside |
|:--|:--|
| [`docs/PROJECT_SPECIFICATION.md`](docs/PROJECT_SPECIFICATION.md) | complete technical specification (18 sections) |
| [`docs/METRICS.md`](docs/METRICS.md) | every measurement + the defect journal |
| [`docs/TEST_CATALOG.md`](docs/TEST_CATALOG.md) | all 233 test declarations, generated from source |
| [`REVISION/HONEST_CAPABILITY_STATUS.md`](REVISION/HONEST_CAPABILITY_STATUS.md) | what works, what doesn't, 59 defects found and fixed |
| [`docs/README.md`](docs/README.md) | documentation map |
| [`README.ru.md`](README.ru.md) | Russian version of this README |

---

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md). The golden rule: **if your check cannot
fail, it is not a check.** Every new test must survive the can-fail harness.

Security issues: see [`SECURITY.md`](SECURITY.md).

---

## License

MIT — see [`LICENSE`](LICENSE).

Copyright (c) 2026 Vital Kalinousky.

