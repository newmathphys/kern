# KERN v2.5.1 — release notes

**Date:** 2026-10-20 · **Base:** v2.5.0 (`54439ee`)

## Highlights

- **Honest QuixBugs boundary:** `6/40` formal SMT (Stage 1, `trusted: 0`) and
  `33/40` live differential (24 value + 8 crash + 1 hang; 9 of 33 need no
  oracle; 7 EXPLORED).
- **`make sync`:** `docs/facts.json` + `<!-- fact:key -->N` anchors; numbers
  are updated in English and Russian together; history is never rewritten.
- **EN/RU parity:** 8 pairs, `make docs-parity`; `make ai-traces-check`
  finds no assistant signatures.
- **`make seal`:** `attests_commit`, `dirtyTree=false`, Ed25519.
- **canfail:** 144 non-vacuous, 0 vacuous, 0 dirty, 0 errors, `RC=0`.

## Metrics

| Metric | Value |
|:--|:--|
| Core | 402 / 402 |
| KERN-Next | 53 / 53 |
| CHECK targets | 128 / 128 |
| can-fail cases | 144 |
| Registry targets | 160 (BUILD 7 · META 21) |
| Lean 4 | 8 files / 147 theorems / 0 sorry |
| Scorecard | 100 / 100 · A+ |

## Artifacts

```bash
curl -fsSLO https://github.com/newmathphys/kern/releases/download/v2.5.1/kernc-x86_64-linux-musl
curl -fsSLO https://github.com/newmathphys/kern/releases/download/v2.5.1/SHA256SUMS
sha256sum -c SHA256SUMS
```

`v2.5.0` remains available as the previous release.
