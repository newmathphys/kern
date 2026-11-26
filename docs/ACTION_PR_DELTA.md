# KERN on a pull request: delta instead of a whole-repository report

## Why the change of question

An audit of the entire repository on every pull request answers the wrong question. The
reviewer already knows the repository has findings; what they need is **what got worse in
this change**. `--delta BASE HEAD` answers exactly that, and `--sarif` turns the answer into
SARIF 2.1.0, which GitHub renders as annotations inside the diff.

## What was built

| Piece | Where | State |
|---|---|---|
| composite action (download, verify, audit, SARIF) | `action.yml` (repository root) | exists since #497 |
| pull-request workflow | `.github/workflows/kern-pr-delta.yml` | added 2026-11-26 |
| ready-to-publish action repository | `action-repo/` | `gh repo create newmathphys/kern-action --public --source . --push` |

The action pins a release (`version`, default `v2.8.26`), verifies the archive's SHA-256 and
the Ed25519 attestation, runs `kerna --doctor`, and only then audits. The appliance carries
its own Python and solver: the runner needs no `pip install`, no Zig, no `.venv`.

## Measured, not assumed

The delta path was run locally before the workflow was committed:

```
dA: int f(int *a, int d){ return a[d-3]; }
dB: int f(int *a, int d){ if (d <= 2) return 0; return a[d-3]; }

python3 tools/audit_delta.py /tmp/dA /tmp/dB --sarif /tmp/d.sarif
  поведенческая дельта: изменившихся файлов 1, сравнено 1
  СЕМАНТИЧЕСКОЕ РАСХОЖДЕНИЕ (DIVERGED) — 1: ~ x.c: [DIVERGED] f
  sarif: 5330 байт, version=2.1.0
```

## What the gate does not claim

- **Interprocedural conclusions are not modelled.** A "new finding" means "a new detector
  fired", not "this was safe before". Only new findings block.
- **Coverage is measured**: 51.5 % of overflow-shaped size computations are recognised on C;
  `break`/`continue`/`goto` are only partly modelled. See
  [`../formal/certification/KNOWN_LIMITATIONS.md`](../formal/certification/KNOWN_LIMITATIONS.md).
- **Funnel drift is printed even without new findings**: a rise in `skipped` with a drop in
  `checked` means "less was proven", and silence there would be the dishonest case.

## How a stranger closes the T7 pilot

1. Fork any repository, or take your own.
2. Add the workflow above; the action pulls the release itself.
3. Open a pull request. Either the annotations appear, or the job fails with a reason.
4. Send the job log — that log is the T7 receipt. See
   [`PILOT_T7.md`](PILOT_T7.md) for the manual seven-minute variant.
