## What does this change?

<!-- One paragraph. Link the issue if there is one. -->

## Evidence (required)

KERN's rule: **no claim without a machine that produced it.** Tick what you actually ran.

- [ ] `zig build test` → rc=0 (**279/279**)
- [ ] `zig build test-next` → rc=0 (**38/38**)
- [ ] `./formal/check.sh` → 0 errors, 0 sorry (if `formal/` changed)
- [ ] `python3 tools/registry.py` → every CHECK target covered
- [ ] `python3 tools/evidence_gate.py` → all logs clean
- [ ] `python3 tools/gen_test_catalog.py --check` (if tests changed)
- [ ] `make canfail` — **if a check or Make target was added/changed, it must be proven
      capable of failing** (a check that cannot go red is treated as a defect)
- [ ] attestation re-signed (`python3 tools/slsa_provenance.py --no-build`) and `--check` valid

## Honesty checklist

- [ ] I did **not** weaken a test, skip a case, relax an assertion or hard-code an expected
      value to make this pass
- [ ] Every number added to `README.md` / `docs/` is produced by a command included here
- [ ] If a claim changed, the **old** value and the reason are stated in the diff
- [ ] If this touches `docs/evidence/`, the logs are from **one** run, not two (defect #81)
- [ ] I did not edit a `FAULTABLE` file while `make canfail` / `make evidence` was running
      (defects #69/#88/#116)

## Notes for the reviewer

<!-- Anything that is NOT proven yet, and why. Honest gaps are welcome; hidden ones are not. -->
