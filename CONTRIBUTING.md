# Contributing to KERN

Thank you for considering a contribution. KERN is a safety-oriented verification
tool, so the process is deliberately strict: **a check that cannot fail is not a
check.**

## The golden rule

> Every new test must be *proven capable of failing*.

KERN ships a can-fail harness (`tools/canfail.py`) that injects a deliberate fault
into the source and requires the check to go red. If your new test stays green
under the injected fault, it is vacuous and will be rejected.

```bash
make canfail        # 60 non-vacuous checks, 0 vacuous
```

## Environment

| Tool | Version | Needed for |
|:--|:--|:--|
| **Zig** | **0.17.0** | everything (`main` and `zig-0.17-migration` both target 0.17.0) |
| Python | 3.12+ | tooling, benchmarks |
| `z3-solver` | latest | `kernc prove`, SMT theories (`pip install z3-solver`) |
| Lean 4 | 4.34.0 (via elan) | `formal/` proofs |
| Mathlib | v4.34.0 (prebuilt cache) | 5 of the 7 Lean files |

```bash
export PATH="$HOME/opt/zig-x86_64-linux-0.17.0:$PATH"
uv venv .venv && uv pip install --python .venv/bin/python z3-solver
./formal/setup_mathlib.sh          # one-time, ~5-10 min (prebuilt Mathlib cache)
```

## Before opening a pull request

```bash
zig build test              # 191 core tests
zig build test-next         # 37 KERN-Next tests
zig build test-fault        # SIGBUS/SIGSEGV fault injection
make ubsafe                 # ReleaseSafe: undefined behaviour detector
make memcheck               # allocator leak check
make coverage               # decision coverage — must stay at 100.0 %
make canfail                # every check must be able to fail
./formal/check.sh           # Lean: 7 files, 0 errors, 0 sorry
make audit-manifest         # qualification manifest, 10/10
```

If any of these goes red, the pull request cannot be merged.

## Rules for the mathematical core

`src/core/eq2.zig` (Belnap B₄), the Truth Gate (`src/verifier/admission_gate.zig`)
and the Z3 bridge (`src/verifier/z3_bridge.zig`) are the trusted base. If you touch
them:

1. `zig build test` **and** `zig build test-align` **and** `zig build test-pool`
   must pass.
2. `./formal/check.sh` must still report `0 errors, 0 sorry`.
3. New behaviour needs a test **and** a can-fail case in `tools/canfail.py`.
4. Update `docs/METRICS.md` with the measurement that justifies the change.

**Never** let a verdict depend on the AI's own `witness_payload`. Only an external
trusted checker may produce `e = 1`.

## Rules for documentation

Numbers in documentation are claims. If you change behaviour, update the number —
`docs/METRICS.md`, `docs/ATTESTATION_PASSPORT.md`, `README.md` and
`REVISION/HONEST_CAPABILITY_STATUS.md` are cross-checked in review.

`docs/TEST_CATALOG.md` is generated. Regenerate it instead of editing it:

```bash
python3 tools/gen_test_catalog.py            # regenerate
python3 tools/gen_test_catalog.py --check    # verify (runs in CI)
```

## Commit messages

Be descriptive and reference the defect registry when applicable, e.g.
`Fix Defect #55: payloadSlice and objectPayloadRaw disagreed on size`.

If a fix came from a tool (mutator, can-fail harness, benchmark), say so — the
provenance of a discovery is part of the evidence.

## Reporting a defect in KERN itself

Use the private channel described in [`SECURITY.md`](SECURITY.md) for anything
security-relevant. For ordinary bugs, open an issue with:

- the exact command,
- the observed output,
- the expected output,
- whether the check can be made to fail (a minimal can-fail case is ideal).

## Style

- Zig: follow the existing file conventions (`compat` module for I/O, no
  `unreachable` on user-controlled input, checked arithmetic via `std.math`).
- Every source file keeps its copyright header.
- Comments explain *why*, and cite the defect number when the code exists because
  of a past failure.

## License

By contributing you agree that your contribution is licensed under the MIT
License (see [`LICENSE`](LICENSE)).
