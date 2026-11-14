# Frontier echo chamber: two LLMs vs the KERN gate

Provider: **живой API: openrouter**. Model A (author): `google/gemma-4-31b-it:free`. Model B (reviewer): `cohere/north-mini-code:free`.

Loop: A writes the implementation, B reviews it and prints `VERDICT: LGTM` or
`VERDICT: BUG`, then KERN judges the same code with a one-line law.

**Headline metric — echo chamber: B said LGTM while KERN produced a counterexample.**


| Task | Law | A: code valid | B: verdict | KERN | Echo chamber | KERN says |
|:--|:--|:--|:--|:--|:--|:--|
| `fee_split` | `conserves_sum` | no | BUG | SKIP | no | код не компилируется |
| `tier_ladder` | `monotonic` | no | BUG | SKIP | no | код не компилируется |
| `tick_round` | `idempotent` | no | BUG | SKIP | no | код не компилируется |
| `refund_parts` | `non_negative` | no | BUG | SKIP | no | код не компилируется |

**Result: 4 tasks, 0 echo-chamber agreements**, 192 s.

## Honest limits

LGTM from a reviewer is not proof of correctness, and a KERN `SKIP` is not an
acquittal: it means the law could not be decided for that code.

