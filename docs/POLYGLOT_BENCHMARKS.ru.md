# Полиглотные бенчмарки: HumanEvalPack и DebugBench под KERN

Оба корпуса взяты обычным HTTPS (без ключей и 429): `bigcode/humanevalpack` через
публичный Datasets Server (в репозитории только parquet), `Rtian/DebugBench` как
`eval.json` (20 МБ). Код написан не нами; `buggy_code` в DebugBench - баг, **внедрённый GPT-4**
в рабочее решение LeetCode.

| Корпус | Язык | Задач | DIVERGED подтверждено | неподтверждено | честный SKIP | вне домена |
|:--|:--|--:|--:|--:|--:|--:|
| HumanEvalPack (canonical vs buggy) | Python | 164 | **6** | 2 | 156 | 0 |
| DebugBench (баги GPT-4) | Python | 1414 | **2** | 0 | 16 | 1390 |

Поймано в HumanEvalPack по типам бага: {'value misuse': 1, 'excess logic': 3, 'variable misuse': 1, 'missing logic': 1}
Поймано в DebugBench по категориям: {'logic error': 2}

## Честные границы

Оба корпуса почти целиком про списки и строки: `SKIP` и `вне домена` - объявленная
граница модели KERN, а не спрятанные неудачи. Каждый `DIVERGED` подтверждён
**исполнением** обеих реализаций в Python на контрпримере решателя.

C++ и Rust из HumanEvalPack **не покрыты**: нужен железный критерий `--xray`
(находка есть на `buggy_solution` и исчезает на `canonical_solution`) - отдельный
пайплайн, в этом окне не построен.
