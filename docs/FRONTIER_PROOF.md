# Frontier echo chamber: two LLMs vs the KERN gate

Provider: **локальный Ollama (ключ не задан — прогон НЕ про флагманов)**. Model A (author): `qwen2.5:3b`. Model B (reviewer): `qwen2.5:3b`.

Loop: A writes the implementation, B reviews it and prints `VERDICT: LGTM` or
`VERDICT: BUG`, then KERN judges the same code with a one-line law.

**Headline metric — echo chamber: B said LGTM while KERN produced a counterexample.**


| Task | Law | A: code valid | B: verdict | KERN | Echo chamber | KERN says |
|:--|:--|:--|:--|:--|:--|:--|
| `fee_split_2way` | `conserves_sum` | yes | BUG | CAUGHT | no | [КОНТРПРИМЕР] fee = -1, result = -2 \| runtime-confirmed |
| `fee_split_3way` | `conserves_sum` | yes | BUG | CAUGHT | no | [КОНТРПРИМЕР] fee = -3, result = -4 \| runtime-confirmed |
| `coupon_split_3` | `conserves_sum` | yes | BUG | SKIP | no | ИТОГО: доказано 0 \| T_advisory 0 \| нарушено 0 (из них безопасность: 0) \| НЕ РЕШЕНО 0 \| |
| `tier_ladder` | `monotonic` | yes | BUG | PROVEN | no | закон доказан |
| `tick_round` | `idempotent` | yes | BUG | SKIP | no | ИТОГО: доказано 0 \| T_advisory 0 \| нарушено 0 (из них безопасность: 0) \| НЕ РЕШЕНО 0 \| |
| `clamp_bounds` | `monotonic` | yes | LGTM | PROVEN | no | закон доказан |
| `pages_refactor` | `monotonic` | yes | BUG | PROVEN | no | закон доказан |
| `refund_split` | `non_negative` | yes | BUG | CAUGHT | no | [КОНТРПРИМЕР] paid = 0, result = -1, used = -1 \| runtime-confirmed |

**Result: 8 tasks, 0 echo-chamber agreements**, 13 s.

## Honest limits

LGTM from a reviewer is not proof of correctness, and a KERN `SKIP` is not an
acquittal: it means the law could not be decided for that code.

