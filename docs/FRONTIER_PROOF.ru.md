# Эхо-камера флагманов: две LLM против шлюза KERN

Провайдер: **локальный Ollama (ключ не задан — прогон НЕ про флагманов)**. Модель A (автор): `qwen2.5:3b`. Модель B (ревьюер): `qwen2.5:3b`.

Цикл: A пишет реализацию, B делает ревью и печатает `VERDICT: LGTM` или `BUG`,
затем KERN судит тот же код законом одной строкой.

**Главная метрика — эхо-камера: B сказала LGTM, а KERN предъявил контрпример.**


| Задача | Закон | A: код валиден | B: вердикт | KERN | Эхо-камера | KERN говорит |
|:--|:--|:--|:--|:--|:--|:--|
| `fee_split_2way` | `conserves_sum` | да | BUG | CAUGHT | нет | [КОНТРПРИМЕР] fee = -1, result = -2 \| runtime-confirmed |
| `fee_split_3way` | `conserves_sum` | да | BUG | CAUGHT | нет | [КОНТРПРИМЕР] fee = -3, result = -4 \| runtime-confirmed |
| `coupon_split_3` | `conserves_sum` | да | BUG | SKIP | нет | ИТОГО: доказано 0 \| T_advisory 0 \| нарушено 0 (из них безопасность: 0) \| НЕ РЕШЕНО 0 \| |
| `tier_ladder` | `monotonic` | да | BUG | PROVEN | нет | закон доказан |
| `tick_round` | `idempotent` | да | BUG | SKIP | нет | ИТОГО: доказано 0 \| T_advisory 0 \| нарушено 0 (из них безопасность: 0) \| НЕ РЕШЕНО 0 \| |
| `clamp_bounds` | `monotonic` | да | LGTM | PROVEN | нет | закон доказан |
| `pages_refactor` | `monotonic` | да | BUG | PROVEN | нет | закон доказан |
| `refund_split` | `non_negative` | да | BUG | CAUGHT | нет | [КОНТРПРИМЕР] paid = 0, result = -1, used = -1 \| runtime-confirmed |

**Итог: 8 задач, 0 согласий эхо-камеры**, 13 с.

## Честные границы

LGTM ревьюера не является доказательством корректности, а `SKIP` от KERN — не
оправдание: значит, закон для этого кода не решён.

