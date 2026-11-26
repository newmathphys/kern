# KERN verification gate — GitHub Action

Zero-trust gate for AI-generated code. On a pull request it audits **only what this
change introduced** and returns the result as SARIF 2.1.0, so findings appear as
annotations inside the review.

> This directory is the ready-to-publish action repository (`newmathphys/kern-action`).
> The same `action.yml` lives in the main repository at the root and is used there by
> `.github/workflows/kern-pr-delta.yml`. Publishing is one command:
> `gh repo create newmathphys/kern-action --public --source . --push`

## Usage

```yaml
permissions:
  contents: read
  security-events: write      # upload-sarif

steps:
  - uses: actions/checkout@v4
    with: { fetch-depth: 0 }

  - id: kern
    uses: newmathphys/kern-action@v2.8.26
    with:
      path: .
      base: ${{ github.event.pull_request.base.sha }}
      sarif-file: kern-delta.sarif
      # block-on-diverged: 'true'   # also fail when a refactor changes behaviour

  - uses: github/codeql-action/upload-sarif@v3
    if: always() && hashFiles('kern-delta.sarif') != ''
    with: { sarif_file: kern-delta.sarif }
```

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `path` | `.` | directory or file to audit (the head side) |
| `base` | *(empty)* | git ref/sha to compare against; empty = empty tree, so every finding counts |
| `sarif-file` | *(empty)* | write SARIF 2.1.0 for findings **introduced** by this change |
| `block-on-diverged` | `false` | also fail when the change alters a function's behaviour |
| `version` | `v2.8.26` | KERN release whose `kerna-dist` archive is downloaded |

Output: `report` — path to the `audit-delta` JSON report.

## What it does not claim

- **Interprocedural conclusions are not modelled.** "New finding" means "a new detector
  fired", not "this was safe before". The gate blocks on new findings only.
- **Coverage is measured, not assumed**: on C code it recognises 51.5 % of
  overflow-shaped size computations; `break`/`continue`/`goto` are only partly modelled.
  See `formal/certification/KNOWN_LIMITATIONS.md` in the main repository.
- A `SKIP` is a named limitation, not a clean bill of health. The delta reports funnel
  drift (`checked`/`skipped`) even when no new finding appears.

## Integrity

The action downloads a pinned release archive, verifies its SHA-256 and the Ed25519
attestation, runs `kerna --doctor`, and only then audits. The appliance carries its own
Python and solver: the runner needs no `pip install`, no Zig, no `.venv`.

## Measured before publishing (2026-11-26, x86_64-linux)

```
audit_delta (dA: a[d-3]; dB: guarded a[d-3]) -> DIVERGED f, sarif 2.1.0, 5330 байт
```
