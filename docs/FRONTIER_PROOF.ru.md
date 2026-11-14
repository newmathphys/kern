# Echo chamber trial: an LLM author, an LLM reviewer, and KERN as judge

Провайдер: **локальный Ollama (ключ не задан)**. Модель A (автор): `qwen2.5:3b`. Модель B (ревьюер): `qwen2.5:3b`.

Цикл: A пишет реализацию, B делает ревью и печатает `VERDICT: LGTM` или `BUG`,
затем KERN судит тот же код законом одной строкой.

**Главный результат: KERN поймал 4 дефекта и доказал 2 закона, а ревьюер-LLM обвинил 7 из 8 решений — включая корректные (ложная тревога).**

## Кто реально участвовал

Файл сгенерирован из **живого прогона** моделей, названных выше (локальный Ollama (ключ не задан)).
Никакой текст флагманов не подставлялся: открытые датасеты (`evalplus/humanevalplus`, `openai/openai_humaneval`) содержат **задачи**, а не ответы моделей, а бесплатный тир OpenRouter отдавал HTTP 429 на тяжёлые
`gemma-4`. Утверждения про GPT-4/Claude/DeepSeek требуют ключа или построчного
дампа, которого в открытом виде нет — поэтому их здесь нет.


| Задача | Закон | A: код валиден | B: вердикт | KERN | Эхо-камера | KERN говорит |
|:--|:--|:--|:--|:--|:--|:--|
| `fee_split_2way` | `conserves_sum` | да | BUG | CAUGHT | нет | [КОНТРПРИМЕР] fee = 2, result = 1 \| runtime-confirmed |
| `fee_split_3way` | `conserves_sum` | да | BUG | CAUGHT | нет | [КОНТРПРИМЕР] fee = 3, result = 4 \| runtime-confirmed |
| `coupon_split_3` | `conserves_sum` | да | BUG | SKIP | нет | TUPLE_ARITY_MISMATCH или скаляр |
| `tier_ladder` | `monotonic` | да | BUG | CAUGHT | нет | [КОНТРПРИМЕР] result = -100, x_b = 100, x_a = 11 \| runtime-confirmed |
| `tick_round` | `idempotent` | да | BUG | SKIP | нет | ИТОГО: доказано 0 \| T_advisory 0 \| нарушено 0 (из них безопасность: 0) \| НЕ РЕШЕНО 0 \| |
| `clamp_bounds` | `monotonic` | да | LGTM | PROVEN | нет | закон доказан |
| `pages_refactor` | `monotonic` | да | BUG | PROVEN | нет | закон доказан |
| `refund_split` | `non_negative` | да | BUG | CAUGHT | нет | [КОНТРПРИМЕР] paid = -2, used = 0, result = -1 \| no-runtime |

**Итог: 8 задач, 0 согласий эхо-камеры**, 14 с.

## Честные границы

LGTM ревьюера не является доказательством корректности, а `SKIP` от KERN — не
оправдание: значит, закон для этого кода не решён.

