# KERN — instructions for AI coding assistants

You are working in **KERN**, a zero-trust verification gateway written in Zig. Read this
before proposing code: the rules below are not style preferences, they are what makes the
project meaningful.

## The one rule

> **A claim is admitted only with machine evidence.** Text is not a proof. A check that
> cannot fail is treated as a defect, not as coverage.

Concretely, for anything you write here:

1. **Never weaken a test, skip a case, relax an assertion or hard-code an expected value**
   to make a build pass. The can-fail harness (`tools/canfail.py`) exists to prove that
   every check *can* go red; if your change makes a check unable to fail, it will be
   reverted and recorded as a defect.
2. **Never delete or weaken a contract line** (`# @kern:requires`, `# @kern:ensures`,
   `// @kern:requires`, `/// @kern:ensures`). Contracts are fingerprinted in
   `docs/contracts.lock.json`; removing or editing one is a hard error (`rc = 2`).
3. **Every number you put in documentation must be produced by a command** that you can
   show. If you cannot run it, write "not measured" — never an estimate.

## Verdict strings are load-bearing

`tools/kern_contracts.py` prints Russian verdicts (`ДОКАЗАНО`, `КОНТРАКТ НАРУШЕН`,
`КОНТРПРИМЕР`, `ПЕРЕПОЛНЕНИЕ`, `ДЕЛЕНИЕ НА НОЛЬ`). Gates depend on those exact strings:

* `tools/canfail.py` patches code containing `if "ДОКАЗАНО" in out`;
* `tools/mcp_selftest.py` greps `КОНТРПРИМЕР` / `ДЕЛЕНИЕ НА НОЛЬ`;
* `tools/edge_cases_check.sh` greps `ПЕРЕПОЛНЕНИЕ типа`.

Do **not** translate or "clean up" tool output. English text belongs in the docs
(`README.md`, `docs/*.en.md`), not in the tool.

## How to run things

```bash
export PATH="$HOME/opt/zig-x86_64-linux-0.17.0:$PATH"   # Zig 0.17.0
zig build && zig build test        # 447 core tests
zig build test-next                # 53 KERN-Next tests
make run-example                   # the 15-second demo (pytest green vs KERN refutation)
make contracts                     # polyglot @kern: contracts (Python/Zig/C/Rust)
./formal/check.sh                  # Lean 4: 8 files, 147 theorems, 0 sorry
make canfail                       # every check must be provably able to fail (~17 min)
python3 tools/canfail.py --check-anchors   # 1-second pre-flight, run this first
python3 tools/bench_json.py --html docs/bench/index.html   # deterministic benchmark
```

`z3` must be in `PATH` (`pip install z3-solver`) — without it the solver-dependent tests
skip silently and the mutation score becomes meaningless (defect #110).

## How to write a contract

```python
# @kern:requires balance >= 0
# @kern:ensures  result <= balance and result >= 0
def withdraw(balance: int, amount: int) -> int:
    ...
```

Then: `python3 tools/kern_contracts.py path/to/file.py`. A `[FAIL]` verdict comes with a
**counterexample** — the exact inputs that break the contract. Fix the code, or fix the
contract; never delete the contract.

For a refactoring with no contracts at all: `make diff-equiv` (checks
`∃x: f_old(x) ≠ f_new(x)` over all of ℤ).

## Gate your own commits

```bash
python3 tools/kern_contracts.py --install-hook    # .git/hooks/pre-commit
python3 tools/kern_contracts.py --git-diff        # check only what this commit touches
```

With the hook installed, a refuted contract blocks `git commit` — for you as well.

## Before you claim a task is done

```bash
python3 tools/canfail.py --check-anchors     # anchors still valid?
python3 tools/gen_test_catalog.py --check    # test catalogue in sync?
python3 tools/registry.py                    # every CHECK target covered?
python3 tools/evidence_gate.py               # evidence logs clean?
python3 tools/slsa_provenance.py --no-build  # re-sign the attestation, then --check
```

Do not run `zig build test` while `make canfail` is running: the harness patches files and
restores them from a snapshot, and both compete for resources.

## Where things live

| Path | What |
|:--|:--|
| `src/verifier/` | the Gate, Z3 bridge, proof checker, SMT theories, CEGIS, DTMC, abstract interpretation |
| `src/core/` | `.kimg` container, KERNFS, Merkle, BLAKE3/SHA-256, codecs |
| `tools/kern_contracts.py` | polyglot contract extractor (Python/Zig/C/Rust) |
| `tools/canfail.py` | the meta-gate: proves every check can fail |
| `tools/mutate_zig.py` | Zig-native mutator (`--jobs`, `--require-solver`) |
| `examples/integrations/` | agent integrations (verified core + framework glue) |
| `docs/CAPABILITY_STATUS.en.md` | what is measured, what is not implemented, and the defect registry |

If you are unsure whether something is real, read `docs/CAPABILITY_STATUS.en.md` first —
it exists precisely so that nobody has to guess.
