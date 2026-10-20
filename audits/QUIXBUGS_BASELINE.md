# QuixBugs baseline — честный замер KERN на мировом бенчмарке

`jkoppel/QuixBugs` — 40 задач, к каждой есть багованная версия 
(`python_programs/*.py`) и исправленная (`correct_python_programs/*.py`).
Проверка: `--diff-equiv` (это и есть `∃x: f_old(x) ≠ f_new(x)`, **без контрактов**).

## Как воспроизвести

```bash
git clone --depth 1 https://github.com/jkoppel/QuixBugs /tmp/QuixBugs-master
python3 tools/quixbugs_check.py   # драйвер: 40 пар, классификация исходов
```

## Результат

| Исход | Задач | Что означает |
|:--|--:|:--|
| **DIVERGED** (баг доказан) | **0** | поведение реально разошлось, есть контрпример Z3 |
| EQUIVALENT | 0 | рефакторинг ничего не изменил |
| **UNKNOWN** (абстракция) | **5** | тело содержит `_havoc_k` → расхождение НЕДОКАЗУЕМО |
| **SKIP** (вне подмножества) | **35** | функция не переводится в SMT (причина в таблице) |

> **Важно (дефект #206).** До фикса эти 5 задач печатались как `DIVERGED` — но это были
> **ложные обвинения**: тела сводились к разным `_havoc_k` (неограниченная абстракция
> вызова), а `(distinct _havoc_2 _havoc_5)` выполняется тривиально. Теперь — `UNKNOWN`.
> Именно так работает правило «0 ложных обвинений»: недоказуемое не выдаётся за баг.

## По задачам

| Задача | Исход | детали / причина |
|:--|:--|:--|
| `bitcount` | SKIP | оператор While (циклы/вызовы вне подмножества) |
| `breadth_first_search` | SKIP | оператор While (циклы/вызовы вне подмножества) |
| `bucketsort` | SKIP | нелинейное умножение |
| `depth_first_search` | UNKNOWN | 0/0/1 |
| `detect_cycle` | SKIP | присваивание не в простую переменную |
| `find_first_in_sorted` | SKIP | оператор While (циклы/вызовы вне подмножества) |
| `find_in_sorted` | UNKNOWN | 0/0/1 |
| `flatten` | SKIP | оператор For (циклы/вызовы вне подмножества) |
| `gcd` | UNKNOWN | 0/0/1 |
| `get_factors` | SKIP | узел List |
| `hanoi` | SKIP | узел List |
| `is_valid_parenthesization` | SKIP | оператор For (циклы/вызовы вне подмножества) |
| `kheapsort` | SKIP | оператор Import (циклы/вызовы вне подмножества) |
| `knapsack` | SKIP | оператор ImportFrom (циклы/вызовы вне подмножества) |
| `kth` | SKIP | узел Subscript |
| `lcs_length` | SKIP | оператор ImportFrom (циклы/вызовы вне подмножества) |
| `levenshtein` | SKIP | узел Subscript |
| `lis` | SKIP | узел Dict |
| `longest_common_subsequence` | SKIP | литерал '' |
| `max_sublist_sum` | SKIP | оператор For (циклы/вызовы вне подмножества) |
| `mergesort` | UNKNOWN | 0/0/1 |
| `minimum_spanning_tree` | SKIP | узел Dict |
| `next_palindrome` | SKIP | оператор While (циклы/вызовы вне подмножества) |
| `next_permutation` | SKIP | оператор For (циклы/вызовы вне подмножества) |
| `pascal` | SKIP | узел List |
| `possible_change` | SKIP | распаковка нефиксированной длины |
| `powerset` | SKIP | распаковка нефиксированной длины |
| `quicksort` | SKIP | узел List |
| `reverse_linked_list` | SKIP | оператор While (циклы/вызовы вне подмножества) |
| `rpn_eval` | UNKNOWN | 0/0/1 |
| `shortest_path_length` | SKIP | узел List |
| `shortest_path_lengths` | SKIP | оператор For (циклы/вызовы вне подмножества) |
| `shortest_paths` | SKIP | узел DictComp |
| `shunting_yard` | SKIP | узел Dict |
| `sieve` | SKIP | узел List |
| `sqrt` | SKIP | оператор While (циклы/вызовы вне подмножества) |
| `subsequences` | SKIP | узел List |
| `to_base` | SKIP | литерал '' |
| `topological_ordering` | SKIP | узел ListComp |
| `wrap` | SKIP | узел List |

## Раскладка блокеров (по функциям, 35 SKIP)

| Причина | Функций |
|:--|--:|
| узел List | 8 |
| оператор While (циклы/вызовы вне подмножества) | 6 |
| оператор For (циклы/вызовы вне подмножества) | 6 |
| узел Dict | 3 |
| распаковка нефиксированной длины | 3 |
| оператор ImportFrom (циклы/вызовы вне подмножества) | 2 |
| узел Subscript | 2 |
| литерал '' | 2 |
| нелинейное умножение | 1 |
| присваивание не в простую переменную | 1 |
| оператор Import (циклы/вызовы вне подмножества) | 1 |
| узел DictComp | 1 |
| узел ListComp | 1 |

## Вывод (без прикрас)

1. **Ни один баг QuixBugs не подтверждён** на текущем фронтенде: 35 задач уходят в SKIP,
   5 — в UNKNOWN. Это **baseline**, а не провал ядра: недостижимы именно входные формы.
2. Главные блокеры — **списки (`list`, 8), циклы (`while` 6 / `for` 6), `dict` 3, срезы/`Subscript` 2**.
   Все 40 задач QuixBugs — алгоритмы над списками, поэтому без модели массива (`QF_AX`, `array_theory.zig`
   и циклов (bounded unroll/инварианты) бенчмарк принципиально не покрывается.
3. Порядок работ, который даст максимум: **`list`/срез (QF_AX) → `for`/`while` (bounded) → повторный прогон**.
   Только после этого имеет смысл говорить «KERN ловит N из 40 QuixBugs»; сейчас честная цифра — **0**.

