# Echo chamber trial: an LLM author, an LLM reviewer, and KERN as judge

Provider: **локальный Ollama (ключ не задан)**. Model A (author): `qwen2.5:3b`. Model B (reviewer): `qwen2.5:3b`.

Loop: A writes the implementation, B reviews it and prints `VERDICT: LGTM` or
`VERDICT: BUG`, then KERN judges the same code with a one-line law.

**Main result: KERN caught 4 defects and PROVED 2 laws,
while the LLM reviewer flagged 7 of 8 solutions — including
correct ones (false alarm).**

## Which models actually participated

This file is generated from a **real run** of the models named above (локальный Ollama (ключ не задан)).
No frontier output was inserted from any dump: the public datasets
(`evalplus/humanevalplus`, `openai/openai_humaneval`) contain **problems**, not
model completions, and the free OpenRouter tier returned HTTP 429 for the heavy
`gemma-4` models. Claims about GPT-4/Claude/DeepSeek need a key or a row-level
dump that does not exist publicly, so they are not made here.


| Task | Law | A: code valid | B: verdict | KERN | Echo chamber | KERN says |
|:--|:--|:--|:--|:--|:--|:--|
| `fee_split_2way` | `conserves_sum` | yes | BUG | CAUGHT | no | [КОНТРПРИМЕР] fee = 2, result = 1 \| runtime-confirmed |
| `fee_split_3way` | `conserves_sum` | yes | BUG | CAUGHT | no | [КОНТРПРИМЕР] fee = 3, result = 4 \| runtime-confirmed |
| `coupon_split_3` | `conserves_sum` | yes | BUG | SKIP | no | TUPLE_ARITY_MISMATCH или скаляр |
| `tier_ladder` | `monotonic` | yes | BUG | CAUGHT | no | [КОНТРПРИМЕР] result = -100, x_b = 100, x_a = 11 \| runtime-confirmed |
| `tick_round` | `idempotent` | yes | BUG | SKIP | no | ИТОГО: доказано 0 \| T_advisory 0 \| нарушено 0 (из них безопасность: 0) \| НЕ РЕШЕНО 0 \| |
| `clamp_bounds` | `monotonic` | yes | LGTM | PROVEN | no | закон доказан |
| `pages_refactor` | `monotonic` | yes | BUG | PROVEN | no | закон доказан |
| `refund_split` | `non_negative` | yes | BUG | CAUGHT | no | [КОНТРПРИМЕР] paid = -2, used = 0, result = -1 \| no-runtime |

**Result: 8 tasks, 0 echo-chamber agreements**, 14 s.

## Honest limits

LGTM from a reviewer is not proof of correctness, and a KERN `SKIP` is not an
acquittal: it means the law could not be decided for that code.

