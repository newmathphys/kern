# KERN v2.8.3 — the release where every claim carries a receipt

**One command to check it yourself** (25 MB appliance, no Zig, no Python, no root):

```bash
base=https://github.com/newmathphys/kern/releases/download/v2.8.3
curl -4 -fsSL -O $base/kerna-dist-v2.8.3.tar.gz -O $base/SHA256SUMS
sha256sum -c SHA256SUMS && tar -xzf kerna-dist-v2.8.3.tar.gz
cd kerna-dist-v2.8.3 && ./kerna --doctor
```

## What is new in 2.8.3

### 1. Every claim now names its receipt
`docs/capabilities_receipts.json` maps **claim → command → receipt file → markers that must be
inside it**. `make receipts-check` (class CHECK) fails if a receipt is missing, empty, lacks a
marker, or contains a forbidden one. Markers that prove nothing ("OK", "PASS") are rejected — a
marker must carry a number or a verdict. Non-vacuous: a selftest covers 7 failure classes and the
can-fail case `receipts-blind` turns the gate red.

### 2. Lean and the kernel are linked where the domain is finite
`make lean-zig-bridge` compares `KernBelnapTable.lean` with `src/core/eq2.zig` on **all 40 inputs**
of the B₄ lattice (16 joins, 16 meets, 4 negations, 4 conflations). For a finite domain, exhaustion
**is** the proof of functional equality, so the Lean theorems now speak about the kernel, not about
a parallel definition. A silent flip of one table row is caught by `--selftest` and by the can-fail
case `lean-zig-bridge-blind`.

### 3. Live AI vs KERN — and why ordinary tests are not enough
`make ai-vs-kern`: free opencode models write code from a specification, KERN judges it
(anti-vacuum first: 3 reference implementations must be PROVEN and a knowingly broken one REFUTED).
Measured: **9/9 PROVEN** across three free models.

`tools/ai_cegis_ab.py` adds the A/B/C experiment on 32-bit edge traps:

| trap | naive formula | ordinary tests (`gcc`) | KERN | fixed formula |
|:--|:--|:--|:--|:--|
| `midpoint_i32` | `(lo+hi)/2` | **GREEN** | **REFUTED** (overflow at `2^30+2^30`) | **PROVEN** |
| `bounds_ok` | `offset+len <= cap` | **GREEN** | **REFUTED** (overflow bypasses the check) | **PROVEN** |
| `capacity_ok` | `used+add <= cap` | **GREEN** | **REFUTED** | **PROVEN** |

Round 2 (CEGIS) sends KERN's counterexample back to the same model; the fixed code is checked again.

### 4. Defects closed (`#551`–`#562`)
Journal caught up with the changelog (725/725 lines RU/EN), `#476` closed —
**open technical defects: 0**, `data[i] = v` writes are checked again (`#552`), the proof-parser
limit is no longer reported as an accusation about the code (`#554`, `cwe-twins-check` **J = 1.00**),
a contract written inside the function body is read (`#559`), the registry no longer overstates its
own numbers (`#560`), and the sign convention of `kernc lia` is printed and pinned by a
discriminating test (`#561`).

## Measured, with the boundaries stated

* **Blind exam P1**: 942 files of `curl/lib` + `redis/src` + `tigerbeetle/src` — 35 findings,
  **0 false alarms, precision 1.00**; 357 CUDA/C++ files of DeepSeek — 0 false alarms.
* **Go, the WHOLE corpus** (`TheAlgorithms/Go 5ba447ec`): 494 files, 1273 functions, 6 findings,
  at least 2 proven false positives of one class ("division under a loop guard").
  Precision on Go is **0.67 < 0.90** — the threshold is **NOT met**, the class is named, and
  fixing it means modelling loop invariants rather than rounding a number.
* **Lean ↔ kernel**: the B₄ lattice is linked exhaustively; LIA, Farkas and the proof checker are
  still at "proved rules + tested instances", which is stated in `LIMITS` §3b, not glossed over.

## Licence

AGPL-3.0-or-later, with a commercial option — see `LICENSE` and `LICENSE-COMMERCIAL.md`.
