# Frontier echo chamber: two LLMs vs the KERN gate

Provider: **живой API: openrouter**. Model A (author): `cohere/north-mini-code:free`. Model B (reviewer): `inclusionai/ling-3.2-flash:free`.

Loop: A writes the implementation, B reviews it and prints `VERDICT: LGTM` or
`VERDICT: BUG`, then KERN judges the same code with a one-line law.

**Headline metric — echo chamber: B said LGTM while KERN produced a counterexample.**


| Task | Law | A: code valid | B: verdict | KERN | Echo chamber | KERN says |
|:--|:--|:--|:--|:--|:--|:--|
| `fee_split` | `conserves_sum` | yes | LGTM | PROVEN | no | закон доказан |
| `tier_ladder` | `monotonic` | no | BUG | SKIP | no | код не компилируется |

**Result: 2 tasks, 0 echo-chamber agreements**, 106 s.

## Honest limits

LGTM from a reviewer is not proof of correctness, and a KERN `SKIP` is not an
acquittal: it means the law could not be decided for that code.

