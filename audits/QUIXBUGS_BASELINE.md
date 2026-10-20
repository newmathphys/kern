# QuixBugs baseline — честный замер KERN на мировом бенчмарке

`jkoppel/QuixBugs`: 40 задач, у каждой — багованная (`python_programs/*.py`)
и исправленная (`correct_python_programs/*.py`) версии. Проверка: `--diff-equiv`
(`∃x: f_old(x) ≠ f_new(x)`, контракты НЕ нужны).

## Как воспроизвести

```bash
git clone --depth 1 https://github.com/jkoppel/QuixBugs /tmp/QuixBugs-master
python3 tools/quixbugs_check.py            # 40 пар, классификация исходов
```

## Результат

| Исход | Задач | Что означает |
|:--|--:|:--|
| **DIVERGED** `[RUNTIME CONFIRMED]` | **1** | баг ПОДТВЕРЖДЁН живым вызовом |
| DISCARDED | 4 | SAT-кандидат есть, но живой вызов расхождения НЕ показал |
| UNKNOWN (havoc) | 0 | расхождение недоказуемо |
| **SKIP** (вне подмножества) | **35** | функция не переводится в SMT |

**Поймано:** `gcd` — на входе `a=0, b=1` багованная версия уходит
в бесконечную рекурсию (`RecursionError`), исправленная возвращает `1`.
Это НАСТОЯЩИЙ баг QuixBugs, подтверждённый **живым вызовом обеих версий**,
а не моделью.

**Отброшено (DISCARDED):** `depth_first_search` (25 входов), `find_in_sorted` (25),
`mergesort` (5), `rpn_eval` (не загрузить — вложенный `def`). Модель давала SAT,
но живой вызов расхождения не показал → **не обвинение** (правило №4).

## Механизм (что именно добавлено)

1. **Bounded AST unrolling (K = 2, `KERN_UNROLL_K`)** — `while cond: body` и
   `for i in range(...)` разворачиваются в K копий тела. Это **недо-аппроксимация**:
   годится для поиска контрпримеров, но НЕ для доказательства.
2. **Ограниченный inline саморекурсии** — тело функции подставляется с
   фактическими аргументами на K шагов; на дне бюджета вызов становится havoc.
3. **Live Replay** — каждый SAT-кандидат проверяется РЕАЛЬНЫМ вызовом
   `buggy_fn(**args)` и `correct_fn(**args)` (таймаут 2 с, лимит рекурсии 300,
   перебор малого домена для несвязанных аргументов). `DIVERGED` — только при
   реальном расхождении; иначе `DISCARDED`. Это гарантия **0 ложных обвинений**.
4. `import` / `AnnAssign` / `a, b = e1, e2` / `x op= e` — No-Op или точная
   трансляция вместо `SKIP`.

## По задачам

| Задача | Исход | детали |
|:--|:--|:--|
| `bitcount` | SKIP | бинарный оператор (только + - * / // %) |
| `breadth_first_search` | SKIP | путь без return |
| `bucketsort` | SKIP | нелинейное умножение |
| `depth_first_search` | DISCARDED | 0/0/0/1 |
| `detect_cycle` | SKIP | присваивание не в простую переменную |
| `find_first_in_sorted` | SKIP | путь без return |
| `find_in_sorted` | DISCARDED | 0/0/0/1 |
| `flatten` | SKIP | for по не-range |
| `gcd` | DIVERGED | 1/0/0/0 |
| `get_factors` | SKIP | узел List |
| `hanoi` | SKIP | узел List |
| `is_valid_parenthesization` | SKIP | for по не-range |
| `kheapsort` | SKIP | узел Subscript |
| `knapsack` | SKIP | распаковка нефиксированной длины |
| `kth` | SKIP | узел Subscript |
| `lcs_length` | SKIP | присваивание не в простую переменную |
| `levenshtein` | SKIP | узел Subscript |
| `lis` | SKIP | узел Dict |
| `longest_common_subsequence` | SKIP | литерал '' |
| `max_sublist_sum` | SKIP | for по не-range |
| `mergesort` | DISCARDED | 0/0/0/1 |
| `minimum_spanning_tree` | SKIP | узел Dict |
| `next_palindrome` | SKIP | присваивание не в простую переменную |
| `next_permutation` | SKIP | распаковка не в имена |
| `pascal` | SKIP | узел List |
| `possible_change` | SKIP | распаковка нефиксированной длины |
| `powerset` | SKIP | распаковка нефиксированной длины |
| `quicksort` | SKIP | узел List |
| `reverse_linked_list` | SKIP | присваивание не в простую переменную |
| `rpn_eval` | DISCARDED | 0/0/0/1 |
| `shortest_path_length` | SKIP | узел List |
| `shortest_path_lengths` | SKIP | присваивание не в простую переменную |
| `shortest_paths` | SKIP | узел DictComp |
| `shunting_yard` | SKIP | узел Dict |
| `sieve` | SKIP | узел List |
| `sqrt` | SKIP | нелинейное умножение |
| `subsequences` | SKIP | узел List |
| `to_base` | SKIP | литерал '' |
| `topological_ordering` | SKIP | узел ListComp |
| `wrap` | SKIP | узел List |

## Раскладка блокеров (SKIP, по функциям)

| Причина | Функций |
|:--|--:|
| узел List | 8 |
| присваивание не в простую переменную | 5 |
| for по не-range | 4 |
| распаковка нефиксированной длины | 4 |
| узел Subscript | 3 |
| узел Dict | 3 |
| путь без return | 2 |
| нелинейное умножение | 2 |
| литерал '' | 2 |
| бинарный оператор (только + - * / // %) | 1 |
| распаковка не в имена | 1 |
| узел DictComp | 1 |
| узел ListComp | 1 |

## Вывод без прикрас

* **1 из 40** подтверждён живым вызовом (`gcd`), **4 кандидата отброшены** живой проверкой,
  **35 — вне подмножества**. Ложных обвинений — **0**.
* Главные оставшиеся блокеры: **`list` (8), присваивание в `arr[i]` (5), `for` по не-range (4),
  распаковка переменной длины (4), `dict` (3), нелинейное умножение (2)**.
* QuixBugs — алгоритмы над **списками и словарями**. Следующий честный шаг: модель массивов
  (`QF_AX`, `array_theory.zig`) и присваивание в элемент. Только после этого число
  «поймано» станет расти; заявлять больше, чем есть, нельзя.

