# Десять доказательств: каждая команда сверена с коммитом `0577b49`

> **Статус: ИЗМЕРЕНО.** Каждая команда ниже выполнена из корня репозитория, а
> вердикт скопирован дословно. Там, где число **дрейфует между прогонами**
> (времена), устойчивым утверждением объявлен **порог**, а не секунды — и это
> сказано прямо. Там, где в репозитории лежит только **снимок** чужого кода,
> указан путь снимка, а не несуществующий путь в апстриме.
>
> Спутники: `docs/CAPABILITY_MATRIX.ru.md` (все возможности с воротами),
> `docs/CORPORA.md` (инвентарь корпусов), `docs/EXAMPLE_WHY_KERN.ru.md` (история `lcm`).

> **Факты (EN/RU, синхронизируются `make sync`):** core <!-- fact:core_tests -->451 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->486 · CHECK <!-- fact:check_targets -->183 · cases <!-- fact:canfail_cases -->223 · anchors <!-- fact:anchors -->183 · registry <!-- fact:registry_targets -->239 · META <!-- fact:meta_targets -->41 · Lean <!-- fact:lean_theorems -->147 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff

## 1. Аппаратное переполнение `i32` (Rust)

```bash
python3 tools/kern_contracts.py audits/codecheck/rust_overflow.rs
```
```
[FAIL] add32: ПЕРЕПОЛНЕНИЕ типа `i32` (диапазон [-2147483648, 2147483647])
       [КОНТРПРИМЕР] result = 2147483648, b = 1, a = 2147483647
       [RUNTIME CONFIRMED] вычисленное значение 2147483648 вне диапазона [...]
```
Обратите внимание на знак: контрпример — `result = 2147483648`, то есть значение
**вне** диапазона, а не завёрнутое `-2147483648`.
**Оракул:** `rustc -C overflow-checks=on` → `panic: attempt to add with overflow` (rc=101).

## 2. Незащищённое деление на ноль (C)

```bash
python3 tools/kern_contracts.py --auto audits/codecheck/c_unguarded.c
```
```
[CRASH PATH] ratio: возможно деление на ноль: b == 0
[XRAY SUMMARY] checked 0 / 1 functions, skipped 1 with explicit reasons, findings 1, SMT calls 1
```
**Оракул:** `gcc -fsanitize=undefined` при `b = 0` → `runtime error: division by zero`.

## 3. `SIGFPE` на краевом значении (`TheAlgorithms/C`, PR #1595)

```bash
python3 tools/kern_contracts.py docs/evidence/any_project/catalan_contract.c
```
```
[FAIL] catalan_divisor: КОНТРАКТ НАРУШЕН
       [КОНТРПРИМЕР] n = 0, result = 0
```
Сам апстримный файл в этом репозитории **не лежит** (это чужой код): снимок —
`docs/evidence/any_project/catalan_contract.c`, патч — `docs/pr/catalan_fix.patch`.
**Оракул:** `gcc -O0` на нетронутом апстримном файле при вводе `0` →
`Floating point exception (core dumped)` (SIGFPE, rc=136).

## 4. Знаковое переполнение умножения (`TheAlgorithms/C`, PR #1596)

Воспроизводящая команда — теневой контракт теперь лежит **в репозитории**, значит
вердикт может повторить любой:

```bash
python3 tools/kern_contracts.py docs/evidence/example_why_kern/lcm_numerator.c
```
```
[BV] lcm_numerator (стр. 15): теория битовых векторов (_ BitVec 32, знаковый)
[FAIL] lcm_numerator: КОНТРАКТ НАРУШЕН
       [КОНТРПРИМЕР] a = #x643b3fbb, b = #5a724dfe, result = #x643a7a8a
```
Гардированный близнец `lcm_numerator_guarded.c` (то же тело, честные границы)
**ДОКАЗАН** — значит опровержение выше не вакуумно. Ворота: `make foreign-verdicts-check`.
Исходный прогон сохранён снимком в `docs/evidence/example_why_kern/lcm.log`:
```
[FAIL] lcm_numerator: КОНТРАКТ НАРУШЕН
       [КОНТРПРИМЕР] a = #x643b3fbb, b = #5a724dfe, result = #x643a7a8a
--- gcc (наземная правда) ---
lcm_probe.c:24:16: runtime error: signed integer overflow: 1681908667 * 1517634558
                   cannot be represented in type 'int'
```
Контрпример KERN — в **шестнадцатеричном** виде (`#x…`), а не `a = 50000, b = 50000`.
Пара `50000 * 50000` — это **иллюстрация из описания PR** того же дефекта,
подтверждённая `gcc`, а не контрпример решателя.

## 5. Переполнение `u64` при вычитании (`TheAlgorithms/Rust`, PR #1075)

Воспроизводящая команда — теневой контракт (дословное выражение `n - i` из
апстримного цикла) лежит в репозитории:

```bash
python3 tools/kern_contracts.py docs/evidence/thealgorithms_rust/binom_step.rs
```
```
[FAIL] binom_step: ПЕРЕПОЛНЕНИЕ типа `u64` (диапазон [0, 18446744073709551615])
       [КОНТРПРИМЕР] result = -1, k = 2, i = 1, n = 0
```
Гардированный близнец `binom_step_guarded.rs` (`requires i <= n`) **ДОКАЗАН** —
значит опровержение не вакуумно. Ворота: `make foreign-verdicts-check`.
Сам апстримный файл **не вендорится** — он сохранён дословно снимком:
```bash
cat docs/evidence/thealgorithms_rust/binomial_coefficient.rs   # апстрим, дословно
cat docs/evidence/thealgorithms_rust/binomial_coefficient_fixed.rs
```
**Оракул:** `cargo test` → `attempt to subtract with overflow` (rc=101);
Codecov зафиксировал **100.00 % patch coverage** на добавленном гарде
(`if k > n { return BigInt::from(0); }`).

## 6. Слепые зоны бенчмарка EvalPlus `MBPP+`

Решение из датасета для `Mbpp/265`, **дословно** из
`evalplus_results/samples_mbpp.jsonl`:
```python
def list_split(lst, n):
    result = [[] for _ in range(n)]
    for i, val in enumerate(lst):
        result[i % n].append(val)
    return result
```
(при `n = 0`: `range(0)` даёт пустой внешний список, затем `i % 0` → `ZeroDivisionError`.)

```bash
make mbpp-xray-check
```
Ворота требуют `false_crash_accusations == 0`, **проверенное живым Python**, и
`confirmed_blindspots == 3` (`Mbpp/265`, `Mbpp/292`, `Mbpp/422`). Selftest имеет
четыре ветви: здоровый прогон, ложное обвинение, недобор и **вакуум**.
**Оракул:** живой `python3`: `list_split([1, 2], 0)` → `ZeroDivisionError`.

## 7. Подмена ТЗ ИИ-агентом блокируется (замок)

На **чистом дереве** команда сообщает, что замок цел:
```bash
make contracts-lock-check
```
```
[OK] замок контрактов цел: ни один запечатанный контракт не изменён
  [OK] покрытие замка: 20 файлов с аннотациями
```
Тревога появляется только когда контракт **действительно ослаблен** — это
canfail-кейс `contract-lock` (`[SECURITY] … rc=2`). Живые модели DeepSeek и GLM
сделали именно это на невыполнимом контракте (сузили `requires`, не тронув
`ensures`) — записано в `docs/evidence/live_eval/`.

## 8. Сравнение двух ревизий без контрактов (`--diff-equiv`)

```bash
python3 tools/kern_contracts.py --diff-equiv \
    docs/evidence/real_history/idx_before.py docs/evidence/real_history/idx_after.py
```
```
[DIVERGED] idx_ok: РЕФАКТОРИНГ ИЗМЕНИЛ ПОВЕДЕНИЕ
       [КОНТРПРИМЕР] k = -1, n = 0, res_old = 1, res_new = 0
```
Файлы — снимки коммита `boltons` `5eb6cc0` (реальный фикс), лежат в
`docs/evidence/real_history/`.
**Оракул:** живой Python: старый код возвращал `1` на недопустимом индексе, новый — `0`.

## 9. Катастрофический бэктрекинг (ReDoS) с физическим таймером

```bash
make oracle-redos-check
```
```
  OK CONFIRMED_VULN   (.+)+      сентинел='\n'   физика=1.4237с     ядро=vulnerable
  OK CONFIRMED_SAFE   abc        сентинел=''     физика=0.0001с     ядро=safe
  OK FAIL_CLOSED      (\d+)+     ядро=skip (вердикта НЕТ — верно)
  подтверждено УЯЗВИМЫХ: 6 · безопасных: 3 · ЛОЖНЫХ ОБВИНЕНИЙ: 0 · ПРОПУСКОВ: 0
```
**Устойчивое утверждение — 6/3/0/0 и порог (0.2 с), а не секунды.** Измеренное
время меняется между прогонами (`1.4237 с` здесь, `1.44 с` в более раннем
снимке `docs/METRICS.md` §159), потому что это wall-clock на общей машине.
**Оракул:** реальный движок Python `re` зависает на патологической строке.

## 10. Утечка секрета по времени исполнения (non-interference)

```bash
make oracle-noninterference-check
```
```
[ИЗМЕРЕНО] отношение времён (позиция отличия 1 против 4096, min-of-N):
  constantTimeEqual : CT_RATIO=1.0035  (порог < 3.0)
  earlyExitEqual    : EE_RATIO=86.8099 (порог >= 10.0)
  [CONFIRMED_SAFE] constant-time: модель говорит утечки нет, реальность не зависит
  [CONFIRMED_LEAK] early-exit: модель говорит утечка, реальность зависит от позиции
```
**Здесь устойчивое утверждение — пара порогов** (`CT < 3.0`, `EE ≥ 10.0`) и
классификация; отношения дрейфуют между прогонами (`1.0003`/`68.80` в снимке §163
против `1.0035`/`86.81` здесь). Этот оракул явно помечен **статистическим**:
планировщик ОС вносит шум, поэтому одно число — не доказательство.
**Оракул:** реальный таймер процессора на 4096-байтовом секрете.

## Всё одной командой

```bash
make showcase-live
```
```
[OK  ] Переполнение i32 -> точные числа аварии              (0.8 с)
[OK  ] Деление на ноль -> точные числа аварии              (1.1 с)
[OK  ] Рефакторинг: эквивалентен ИЛИ расхождение с числом  (1.3 с)
[OK  ] Граница --xray по расширениям названа, а не молчалива (0.9 с)
[OK  ] Диагност: чего не хватает функции                   (1.7 с)
[OK  ] Замок: агент не подменил спецификацию               (0.9 с)
[OK  ] Нативный Zig-фронтенд (0 Python): контракты из .zig (0.2 с)
ИТОГ: выполнено 7 строк | провалов 0
```
Две честные оговорки. Во-первых, общее время **не печатается** и оно **не 3.4 с**:
строки выше дают ≈6.9 с на этой машине. Во-вторых, витрина **требует Zig 0.17 в
`PATH`** — иначе цель `zig-guard` отказывает названным `[ОТКАЗ] … rc=2`
(дефект #392) вместо обвинения `build.zig`.

## Чего ничего из этого НЕ доказывает

- KERN — не сканер: он не ищет баги в чужих репозиториях сам.
- `[BOUNDS] … длина НЕ известна` — **кандидат**, а не обвинение.
- SKIP / «вне подмножества» никогда не засчитывается как доказательство корректности.
- Оракулы ReDoS и non-interference — физические **измерения** с порогами,
  а не детерминированные доказательства.
