# Execution Runner: переход `empirical → N` в `tested → T (e=1)`

Закрывает эпистемический разрыв: система не только ЧИТАЕТ код, но физически
фиксирует факт исполнения.

## Цепочка

```
README "✅ проверено" → Сканер → Claim(empirical, N)
                                     │  Execution Runner (запуск теста)
                                     ▼  exit_code + sha256 логов
                       Claim(execution) + evidence + link(supported_by)
                                     │  Белнап-аккумулятор joinK
                                     ▼
              Врата: e=1 ТОЛЬКО при строгом T (p=1,n=0)
```

## Файлы

| Файл | Роль |
|:--|:--|
| `tools/kern_exec_runner.py` | изолированный запуск, тайм-аут, хэши, маскирование секретов, анти-вакуум |
| `tools/run_project_verification.py` | АВТО-дискавери тестов (без ручного списка) |
| `src/next/truth.zig` | Белнап-аккумулятор `joinK` (резолюция статусов) |

## 4 усиления из аудита — реализованы

### 1. Белнап-аккумулятор (не перезапись!) — `src/next/truth.zig`

```zig
pub fn join(a: Bit, b: Bit) Bit { return .{ .p = a.p or b.p, .n = a.n or b.n }; }
```

Если один тест зелёный (p=1), а другой красный (n=1) → `joinK(T,F) = B` (КОНФЛИКТ),
`e=0`. Перезапись «последним тестом» — уязвимость, она закрыта.
Тест: `TRUTH КЛЮЧЕВОЙ: зелёный + красный = КОНФЛИКТ B (не перезапись!)`.

### 2. Анти-вакуум (Zero-Assertion Pass)

`test_is_non_vacuous()` парсит AST теста и требует `assert`/проверок.
Пустышка с `exit_code=0` НЕ даёт `T` — помечается `vacuous`.

### 3. Авто-дискавери тестов

`discover()` сам находит `test_*.py` и цель `test:` в Makefile — ручной список
`targets` больше не нужен.

### 4. Маскирование секретов (Secret Scrubbing)

`scrub_secrets()` вычищает API-ключи, токены, JWT, `Bearer`, `sk-` **ДО** записи
лога и вычисления sha256 — секрет не попадает ни в лог, ни в `.kimg`.

## Демонстрация на «БИБЛИОТЕКА-КОНВЕЙЕР»

```
test_kern_demo.py        exit=0, non_vacuous=True   → T  (доказано)
test_async_search.py     exit=124 (тайм-аут), vacuous → F  (опровергнуто)
test_repair.py           exit=124 (тайм-аут), vacuous → F  (опровергнуто)
```

**Реальная находка:** «тесты» проекта оказались сетевыми бенчмарками без
единого `assert` — KERN это вскрыл (анти-вакуум + тайм-аут).

## Самоанализ: KERN на самом себе

```
kernx build /tmp/kern_self.kern   → 16 утверждений
статус tested: 6   (5 машинных прогонов exit=0 + 1 тест-файл)
статус verified: 9 (документация)
статус blocked: 1  (TODO)
ошибок: 0
```

Пять машинных свидетельств: `zig build test`, `zig build test-next`,
`./formal/check.sh`, `src/stress_real.zig`, `src/kern_bench.zig` — все `exit=0`.
