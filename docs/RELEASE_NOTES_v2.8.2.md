# KERN v2.8.2 — the first release proven on unfamiliar code

**Zero-trust verification gateway.** A claim about code is admitted only with machine evidence:
an SMT solver, a formal proof, or a reproducible execution fact — never because of text, docs or a
green CI.

## What is in this release

- **Zero-dependency appliance `kerna-dist-v2.8.2.tar.gz` (27 MB).** Unpack and run: `./kerna
  --doctor`, then `./kerna /path/to/project`. No Python, no Zig, no `pip install` needed on the
  client. It ships `kerna`, the static `kernc`, the `z3` solver, both licences and **`LIMITS`
  next to the binary** — what is proven and what is not, before the first audit.
- **`action.yml` that really runs the release archive.** It downloads the tarball, verifies its
  SHA-256 **before** extracting (then the contents again), runs `--doctor` and fails a pull request
  only on findings **this change introduced** (`audit-delta` base → head). Exit codes are proved,
  not promised: `0` clean / `1` new finding / `2` incomplete distribution / `3` bad artifact.
- **Machine ABI `--xray-json` (schema 1.0)**, differential audit `audit-delta`, audit passport
  `kern_scan`, showcase `make tour`, capability map, dual licensing (AGPL-3.0-or-later +
  commercial).
- **Self-control:** 200/200 CHECK gates, 245 non-vacuous `canfail` cases, 1597/1597 killed Zig
  mutants, `0` subprocesses without a timeout, `LIMITS` synchronised with the gates.

## The number this release is about

Before publishing, the analyzer was measured on **three repositories it had never seen** (blind
run: no edits to the analyzer first, fixed SHAs, deterministic slice):

| corpus | files | functions | findings | false accusations |
|:--|--:|--:|--:|--:|
| `curl/lib` @155f6f76 | 60 | 161 | 0 | 0 |
| `redis/src` @5b69ba2c | 60 | 1684 | 8 | 0 |
| `tigerbeetle/src` @68958eb7 | 57 | 315 | 0 | 0 |
| **total** | 177 | **2160** | 8 | **0** |

**Precision 1.00** (threshold 0.90) with **SV-COMP `signedintegeroverflow-regression` TPR 1.00 /
FPR 0.00** unchanged. All eight findings are «UB in the signature domain» (`INT_MIN`/`INT_MAX`
arguments that no in-tree caller passes) — they are named as such, not upgraded to bugs.

The blind run is what produced the six fixes below; every one was minimised to ≤15 lines first and
guarded by a **two-sided** control (false accusation → 0 **and** the true finding stays found):

- `#500` a struct field's OLD value survived the field being rewritten (3 of 5 false accusations);
- `#501` an unsigned index was modelled with `Int` arithmetic (`size_t 0-1` is `SIZE_MAX`, not `-1`);
- `#501b` an unknown index type (macro type) was silently treated as signed;
- `#502` the same finding was counted twice (identical text, no line numbers in `[DEAD BRANCH]`);
- `#503` `switch` cases were glued into straight-line code, so a live branch looked dead;
- `#504` the bit-vector form ignored LOCAL declaration types, so `long long value < 0` became
  `bvult value 0` — always false.

## Verify it yourself

```
sha256sum -c SHA256SUMS                     # both assets
tar -xzf kerna-dist-v2.8.2.tar.gz && cd kerna-dist-v2.8.2
sha256sum -c SHA256SUMS && ./kerna --doctor
```

The attestation (`kern.intoto.jsonl` + `kern.intoto.sig`) is checked by the **public** key in
`docs/keys/kern-owner.pub` — no private key and no `$HOME` needed:

```
make verify-attestation
```

## Limits, stated plainly

Read `LIMITS.md` inside the archive. Precision is measured on a **slice** (60 files per corpus),
not on whole repositories; the four surviving `[OVERFLOW PATH]` classes are reachable only for
arguments outside every in-tree call site; interprocedural reasoning is not modelled; `switch`
bodies are skipped for dead-branch claims; unsigned index arithmetic is a **named skip** because a
correct claim would need the array length we do not have.
