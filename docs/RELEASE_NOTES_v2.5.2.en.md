# KERN v2.5.2 — the showcase stops promising what it cannot show

A release of **corrections to claims**, not new features. Every item below was
found by checking the code, and each is proven by a gate that can fail.

## Fixes

- **#243 `--diff-equiv` accused an identical file of divergence.** The command
treated everything except “PROVED” as a divergence, while `kernc prove` returns
the same exit code for “proved but the checker rejected the proof”
(`premises_unbound`) and for “refuted with a counterexample”. `make diff-equiv`
passed vacuously. Classification now follows the solver output
(`equivalent` / `unverified` / `diverged` / `unknown` / `tool_error`) and there
is a positive control: an identical file must never be accused.
- **#244 the showcase promised interactive elements that did not exist**, and
the hero banner carried “200 T / 422 F,N / 409 B” — a number that exists in no
source. The numbers are replaced by the law `join_K(T,F)=B`, the Belnap arrows
now follow the direction of accumulation (`N→F`, `N→T`, `F→B`, `T→B`), and the
page gained a proof-flow map (`docs/kern-proof-flow.svg`), an Ego-Lens over the
real `@import` graph (radius 1–2) and a `[+][~][-][=]` filter matrix over labels
recomputed from source. Equivalence is marked **CLI only** instead of being
simulated in a browser.
- **#245–#247 the number guards had holes**: an anchor comment hid the number
from its own rule (vacuous check), four files carried anchors that `sync` never
updated, and a documented syntax example was taken for a broken anchor. All
three are fixed, and `sync --selftest` now creates a temporary anchored file and
demands that the guard catch it.

## Release pipeline

- The GitHub Release is now built **draft → upload assets → publish**, so a
published release can never exist without files.
- `Release Drafter` no longer drafts a release named after the next patch tag;
that draft was swallowing the real tag release.
- Release notes are resolved per tag instead of a hard-coded file name.

## Evidence

Numbers are data: `docs/facts.json` + `<!-- fact:key -->` anchors, so README,
the site and the passports cannot drift apart.

```bash
make sync-check        # anchors == measured facts
make showcase-check    # the lens graph == src/ (3 tamperings in --selftest)
python3 tools/slsa_provenance.py --check
```
