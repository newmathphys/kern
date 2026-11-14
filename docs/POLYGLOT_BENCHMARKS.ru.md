# Полиглотные бенчмарки: HumanEvalPack (Python/C++/Rust) и DebugBench

Все три корпуса взяты обычным HTTPS (без ключей и 429): `bigcode/humanevalpack` через
публичный Datasets Server (в репозитории только parquet, `pyarrow` в окружении нет),
`Rtian/DebugBench` - сырым `eval.json`. Код написан не нами; `buggy_code` в DebugBench -
баг, **внедрённый GPT-4**.

| Корпус | Язык | Задач | **поймано** | не подтверждено | без находок / SKIP | вне домена |
|:--|:--|--:|--:|--:|--:|--:|
| HumanEvalPack (canonical vs buggy) | Python | 164 | **6** | 2 | 156 | 0 |
| HumanEvalPack (`--xray`, железный критерий) | C++ | 164 | **0** | 2 | 162 | - |
| HumanEvalPack (`--xray`, железный критерий) | Rust | 164 | **0** | 0 | 164 | - |
| DebugBench (баги GPT-4) | Python | 1414 | **2** | 0 | 16 | 1390 |

Поймано в HumanEvalPack по типам бага: {'value misuse': 1, 'excess logic': 3, 'variable misuse': 1, 'missing logic': 1}
Поймано в DebugBench по категориям: {'logic error': 2}

## Честный отрицательный результат по C++ и Rust

Железный критерий `--xray`: находка обязана быть в `buggy` и **исчезнуть** в `canonical`.
Измерено: **0 побед в C++, 0 в Rust** (162/164 и 164/164 задач вообще без находок).
Причина структурная: задачи HumanEvalPack на C++/Rust - это алгоритмы над
`std::vector` / `Vec<String>`, то есть динамические контейнеры и аллокации, которые
C-подобная модель памяти не покрывает. Пишем как измерено, без натяжки.

Каждый Python-`DIVERGED` подтверждён **исполнением** обеих реализаций на контрпримере.
