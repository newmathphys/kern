# KERN v2.8.26

Release of 2026-11-24. The theme is **the bug hunt becomes part of CI**: the trunk that
found the last real defect now runs on every push instead of on request.

## What changed

* **`api-hunt-check` runs in the fast contour.** `tools/api_hunt.py --selftest` and the
  size-overflow witnesses of `tools/_witness.py` were reachable but never called by
  `tools/ci.sh`, so the trunk could have rotted silently while the showcase stayed green.
  The orphan-gate check (`#633`) caught it; the stage now sits next to `law-hunter-check`.
* **Freshness filter on `pushed_at`, not on repository age.** `repo_age_days > 730` cut
  every mature library, including the live ones that actually take patches. The rule is now
  `pushed_at >= "2025-06-01"`, and `has_issues == False` no longer disqualifies a
  repository — private Security Advisories work with the Issues tab switched off.
* **Honest witnesses in the `z3-alloc` trunk (calibration 21).** The witness is built from
  genuinely tainted factors only. A local `channels = 1` no longer produces a silent
  `65536 × 65536`; when a known channel name is the only candidate, the literal weight is 4
  and the assumption is printed inside the witness.
* **Showcase states what upstream actually did.** `zed` merged, `iio` pull request open,
  `typst` and `gleam` closed by their authors as intended behaviour. Two of the last three
  large reports were settled by intent rather than by a counterexample, which is why the
  roadmap now requires an intentionality check before a report is sent.

## Facts

Counts are the ones `make sync` writes into `docs/facts.json`; the release notes do not
restate them, so they cannot drift.

## Verification

`make ci-fast` (37 green stages), `make seal`, Ed25519 attestation verified with the
external key, `action-check` on the published archive.
