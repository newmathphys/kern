# KERN — КАТАЛОГ ТЕСТОВ (полный)

> **СГЕНЕРИРОВАНО** из исходников (`python3 tools/gen_test_catalog.py`).
> Каждое имя ниже — реальный тест, который можно запустить.
> Пропусков и «планируемых» тестов нет. Рассинхрон с кодом ловит
> `python3 tools/gen_test_catalog.py --check` (стадия CI).

**Всего объявлений тестов:** 230

| Группа | Файлов | Тестов |
|:--|--:|--:|
| Ядро формата и ФС (L0/L3) | 6 | 41 |
| Верификатор (Врата, SMT, теории) | 13 | 72 |
| Специализированные сьюты | 11 | 53 |
| KERN-Next (парсер, каталог, конвейер) | 9 | 36 |
| Среда исполнения | 1 | 5 |
| Корень `src/` | 6 | 23 |



## Ядро формата и ФС (L0/L3)


### `src/core/eq2.zig` — 6

- EQ2: кодировка p | (n << 1)
- 🔴 СПЕКА: Eq2.encode(p,n) и псевдонимы p()/n() (полный API спеки)
- EQ2: T JOIN F = B (изоляция противоречий)
- EQ2: биты p и n независимы
- MATH: де Моргана для порядка истинности (полный перебор)
- MATH: таблица отрицания notB (закрывает выживший мутант |->&)


### `src/core/kernfs_router.zig` — 15

- CONF-13: path traversal и валидация формата
- SEC-03: NUL-инъекция и побег через /claims
- ФИКС ФАЗ 1/3: mountFromBytes находит файл и отдаёт zero-copy срез
- 🔴 МУТАНТ: getString отвергает смещение ЗА пределами пула строк
- 🔴 МУТАНТ: objectPayloadRaw не проверяет хеш, objectPayload — проверяет
- ФИКС CONF-06: запись в KERNFS отвергается AccessDenied
- ФИКС MERKLE: подмена байта в образе ломает монтирование
- ФИКС МУТАНТ: payloadSlice выбирает размер по compression_codec
- ФИКС МУТАНТ: hasPath требует флаг HAS_LOGICAL_PATH (бит 1)
- ФИКС МУТАНТ: /raw/ ищет только объекты типа Source (0x0002)
- ФИКС МУТАНТ: /claims/ ищет только объекты типа Claim (0x0005)
- TAMPER: порча 1 байта в середине .kimg блокирует монтирование
- TRUNCATION: обрезанный образ отвергается без паники
- ФИКС ЦЕЛОСТНОСТИ: подмена payload отвергается (digest-сверка)
- ГРАНИЦЫ: payload_offset за пределами региона -> FileNotFound


### `src/core/kimg_reader.zig` — 11

- KimgHeader.parse: валидный заголовок
- 🔴 СПЕКА: мажорная версия != 1 отвергается (UnsupportedVersion)
- 🔴 СПЕКА: hash_algo вне {1,2} отвергается (InvalidHashAlgo)
- KimgHeader.parse: битый magic отвергается
- KimgHeader.parse: таблица за пределами файла отвергается
- KimgHeader.parse: слишком короткий файл отвергается
- SEC-01: переполнение offset+size отвергается (не паника, не приём)
- MERKLE: пересчёт корня совпадает и ловит подмену
- SEC: гигантский object_count не вешает парсер (DoS-защита)
- KimgHeader.parse: неверный размер заголовка отвергается (BadHeaderSize)
- KimgHeader.parse: payload за границей файла отвергается (PayloadOutOfBounds)


### `src/core/kimg_writer.zig` — 5

- KIMG-WRITER: сборка образа и чтение через KERNFS (roundtrip)
- ГРАНИЦА: пустой Builder -> BuildError.Empty
- ГРАНИЦА: объект с пустым содержимым и длинным путём
- CRASH-CONSISTENCY: запись атомарна, .tmp не остаётся
- ДОЛГОВЕЧНОСТЬ: данные сброшены на носитель (fsync), образ читается


### `src/core/mmap_guard.zig` — 2

- SIGBUS: обработчик устанавливается, флаг сбрасывается/читается
- SIGBUS: страница PROT_NONE создаётся и освобождается (инфраструктура)


### `src/core/object_entry.zig` — 2

- CONF-15: ObjectEntry разбирается и держит 96-байтную раскладку
- CONF-15: мусор в reserved-байтах отвергается


## Верификатор (Врата, SMT, теории)


### `src/verifier/abstract_interp.zig` — 5

- ABSINT: widening гарантирует завершение (растущий счётчик -> +inf)
- ABSINT: цикл x:=0; while(x<10) x+=1 — инвариант [0,9], выход x>=10
- ABSINT: шаг 2 — инвариант [0,9], выход x>=10
- ABSINT: интервалы — join/meet/widen/narrow корректны
- ABSINT: уход к переполнению — widening видит +∞ (потенциальный overflow)


### `src/verifier/admission_gate.zig` — 8

- CONF-30.4: отвергается устаревший сертификат (несовпадение AST)
- ФИКС АТАКИ 1: ОДИН БАЙТ 0xAA больше НЕ даёт e=1
- ФИКС АТАКИ 1: внешний решатель-стаб НЕ принимает одиночный байт
- успех: структурно корректный свидетель от ВНЕШНЕГО чекера даёт e=1
- CONF-04: анти-вакуумный шлюз захлопывается (вердикт внешнего чекера)
- политика: allowed_checkers — битовая маска 1 << checker_id
- 🔴 ФИКС: checker_id >= 32 НЕ получает прав checker 0 (заворот маски)
- доверие к пруверу: запрещённый checker_id отвергается


### `src/verifier/array_theory.zig` — 5

- ARRAY: скрипт содержит аксиому Маккарти (select(store))
- ARRAY (РЕАЛЬНЫЙ Z3): select(store(a,i,v),i) = v доказано (unsat)
- ARRAY (РЕАЛЬНЫЙ Z3): независимость ячеек при i≠j доказана (unsat)
- ARRAY (РЕАЛЬНЫЙ Z3): защищённая запись безопасна (unsat = доказано)
- ARRAY (РЕАЛЬНЫЙ Z3): OOB-индекс достижим (sat = уязвимость видна)


### `src/verifier/cegis.zig` — 5

- CEGIS (РЕАЛЬНЫЙ Z3): x*8 ≡ x<<3 доказано на ВСЕЙ области (unsat)
- CEGIS (РЕАЛЬНЫЙ Z3): x*8 ≢ x<<2 — контрпример найден (sat)
- CEGIS (РЕАЛЬНЫЙ Z3): СИНТЕЗ x*8 → найдено (bvshl x 3)
- CEGIS (РЕАЛЬНЫЙ Z3): СИНТЕЗ x*16 → найдено (bvshl x 4)
- CEGIS (РЕАЛЬНЫЙ Z3): x*3 невыразим сдвигом → НЕ найдено (честный отказ)


### `src/verifier/chc.zig` — 4

- CHC: скрипт содержит индуктивную схему (inv, forall, HORN)
- CHC (РЕАЛЬНЫЙ Z3): цикл x:=0; while(x<10) x++; даёт x>=10 — ДОКАЗАНО (sat)
- CHC (РЕАЛЬНЫЙ Z3): ложное постусловие x<5 — инварианта НЕТ (unsat = БАГ)
- CHC (РЕАЛЬНЫЙ Z3): инвариант чётности x:=0; while(x<10) x+=2 — чётность ДОКАЗАНА


### `src/verifier/dtmc.zig` — 4

- DTMC: смещённая монета — P(провал) = 0.01
- DTMC: 3 попытки с p=0.9 — P(провал) = 0.1³ = 0.001
- DTMC PCTL: проверка порога P≤0.01 [ F fail ]
- DTMC: нестохастическая матрица отвергается (модель некорректна)


### `src/verifier/noninterference.zig` — 6

- NONINTERFERENCE: ветвление по секрету = УТЕЧКА (Spectre-класс)
- NONINTERFERENCE: индекс массива по секрету = УТЕЧКА (cache-timing)
- NONINTERFERENCE: constant-time select НЕ даёт утечки ветвления
- NONINTERFERENCE: taint распространяется через присваивания
- NONINTERFERENCE: constant-time сравнение эквивалентно обычному
- NONINTERFERENCE: constant-time НЕ зависит от позиции отличия (ранний выход — ЗАВИСИТ)


### `src/verifier/nra_quant.zig` — 6

- NRA: x² < 0 неразрешимо (квадрат вещественного неотрицателен)
- NRA (∀): x² + y² ≥ 0 доказано для ВСЕХ вещественных
- NRA: единичный круг — точка (0.9, 0) внутри (sat)
- NRA: x² + y² > 2 недоказуемо (контрпример x=y=0 есть)
- QUANT: с явным триггером — противоречивый контракт (unsat)
- QUANT: квантор без триггера ограничен таймаутом (Matching Loop обезврежен)


### `src/verifier/proof_check.zig` — 4

- PROOF: баланс скобок распознаёт битый вывод
- PROOF: счётчик шагов вывода
- PROOF (РЕАЛЬНЫЙ Z3): вывод получен, структурно корректен, ядро минимально
- PROOF (РЕАЛЬНЫЙ Z3): выполнимая формула НЕ даёт подтверждения


### `src/verifier/redos.zig` — 6

- REDOS: (a+)+ распознан как уязвимый (вложенный квантор)
- REDOS: (a*)* распознан как уязвимый
- REDOS: (a|a)* — неоднозначная альтернатива под квантором
- REDOS: безопасная регулярка (a|b)* — НЕ уязвима
- REDOS: простой литерал без кванторов безопасен
- REDOS (РЕАЛЬНЫЙ Z3): уязвимая регулярка принимает экспоненциальный вход


### `src/verifier/string_theory.zig` — 5

- STRINGS: скрипт содержит строковые ограничения SMT-LIB
- STRINGS (РЕАЛЬНЫЙ Z3): строка с '..' существует (sat)
- STRINGS (РЕАЛЬНЫЙ Z3): УЯЗВИМОСТЬ — '..' проходит при вырезании '/' (sat)
- STRINGS (РЕАЛЬНЫЙ Z3): нуль-байтовая инъекция достижима (sat)
- STRINGS (РЕАЛЬНЫЙ Z3): regex a* корректно исключает 'b' (unsat)


### `src/verifier/unsat_core.zig` — 4

- UNSAT CORE (mock): извлечение имён ядра из вывода Z3
- UNSAT CORE (mock): sat не даёт ядра
- UNSAT CORE (скрипт): содержит :named и get-unsat-core
- UNSAT CORE (РЕАЛЬНЫЙ Z3): локализация точной конфликтующей строки


### `src/verifier/z3_bridge.zig` — 10

- Z3BRIDGE: отсутствие z3 не роняет мост (graceful degradation)
- Z3BRIDGE: без Z3 контракт НЕ подтверждается (verifyContract=false)
- Z3BRIDGE → ВРАТА: без Z3 один байт 0xAA даёт e=0
- Z3 РЕАЛЬНЫЙ: валидный контракт подтверждается
- Z3 РЕАЛЬНЫЙ: неверный контракт отвергается (контрпример)
- ВРАТА + РЕАЛЬНЫЙ Z3: корректный контракт даёт e=1 (ПЕРВЫЙ РАЗ!)
- ВРАТА + РЕАЛЬНЫЙ Z3: багованный контракт даёт e=0 (контрпример)
- Z3 + КЭШ ДОКАЗАТЕЛЬСТВ: второй вызов не дёргает решатель
- ГРАНИЦА: мусорный SMT не роняет мост
- РЕСУРСЫ: 50 запросов Z3 не текут FD и не плодят зомби


## Специализированные сьюты


### `src/tests/alignment_stress.zig` — 8

- ALIGN comptime: заголовок .kimg — ровно 128 байт, выравнивание 8
- ALIGN comptime: записи таблицы читаются как [96]u8 (alignment = 1)
- ALIGN comptime: ObjectEntry — ЛОГИЧЕСКАЯ структура (72 байта), НЕ раскладка диска
- ALIGN runtime: разбор при смещениях 0..7 — одинаковый результат
- ALIGN runtime: записи таблицы читаются при смещениях 1,2,3,5,7
- ALIGN runtime: невыровненная таблица НЕ ломает Merkle (полный образ)
- ENDIAN: многобайтные поля читаются Little-Endian
- ALIGN strict: isStrictlyAligned различает выровненные и нет


### `src/tests/coverage_report_test.zig` — 1

- ПОКРЫТИЕ: отчёт по инструментированным решениям


### `src/tests/exhaustive_suite.zig` — 11

- MATH-01: таблица Белнапа-Данна B4 (Join и Meet)
- MATH-02: законы де Моргана в порядке истинности
- SEC-01: атака переполнения в заголовке KIMG (offset bomb)
- SEC-02: троян в reserved-байтах (CONF-15)
- SEC-03: path traversal и NUL-инъекция
- AI-01: текстовый свидетель ≥8 байт НЕ отвергается (реальное поведение)
- AI-01b: короткий свидетель без внешнего чекера не допускается
- AI-02: устаревший сертификат (несовпадение хеша AST)
- AI-03: вакуумное предусловие (анти-вакуумный шлюз)
- ФИКС АТАКИ 1: ОДИН БАЙТ 0xAA НЕ даёт e=1 (уязвимость закрыта)
- RES-01: исчерпание топлива — это N, а не F


### `src/tests/fault_injection_test.zig` — 2

- SIGBUS РЕАЛЬНЫЙ: чтение PROT_NONE перехвачено, процесс жив
- SIGBUS РЕАЛЬНЫЙ: файл, обрезанный после mmap (выдернутый носитель)


### `src/tests/litmus_memory_test.zig` — 5

- LITMUS SB: SeqCst НЕ допускает исход r1=r2=0 (запрещён моделью SC)
- LITMUS SB: relaxed — исход возможен на слабой модели (отчёт, не приговор)
- LITMUS MP: release/acquire НЕ допускает «флаг без данных»
- LITMUS MP: relaxed ДОПУСКАЕТ нарушение (обоснование барьеров в KERN)
- LITMUS: аксиоматика — допустимые исходы SC/TSO для SB


### `src/tests/mcdc_gates_test.zig` — 8

- MC/DC-1: базовый вектор — все условия T -> e=1 (Врата открыты)
- MC/DC-2: ТОЛЬКО ast_ok=F (остальные T) -> AstHashMismatch (условие независимо)
- MC/DC-3: ТОЛЬКО contract_ok=F (остальные T) -> ContractHashMismatch (независимо)
- MC/DC-4: ТОЛЬКО allowed=F (остальные T) -> UntrustedChecker (независимо)
- MC/DC-5: ТОЛЬКО вердикт=Counterexample -> e=0, F (независимо)
- MC/DC-6: VacuousPrecondition + require_anti_vacuity=true -> PolicyViolation
- MC/DC-7: анти-вакуумность ИНВЕРТИРУЕТ исход при прочих равных
- MC/DC-8: таблица истинности VerificationPolicy.allows (все 32 бита)


### `src/tests/oom_stress.zig` — 3

- OOM: сборка образа на 2 МБ -> error.OutOfMemory (не паника)
- OOM: запись образа на 2 МБ -> контролируемая ошибка
- OOM: парсер заголовка не аллоцирует (zero-copy) — работает при любом лимите


### `src/tests/os_stress_test.zig` — 4

- ОС-СТРЕСС 1: вывод > 64 КБ (буфер пайпа) — взаимной блокировки НЕТ
- ОС-СТРЕСС 2: вывод > лимита 4 МБ — аккуратный отказ, НЕ паника
- ОС-СТРЕСС 4: инъекция сбоев 5% (pipe/spawn/read) — нет паник, нет утечек FD
- ОС-СТРЕСС 3: флуд spawn (12 потоков × 8 запросов) — без паник и утечек FD


### `src/tests/pool_saturation.zig` — 4

- POOL: 128 запросов на пуле из 4 — лимит соблюдён, все выполнены
- POOL: пик не превышает лимит при 8 воркерах и 128 запросах
- POOL: пул из 1 сериализует (никогда не более 1)
- POOL + РЕАЛЬНЫЙ Z3: 16 независимых формул через пул из 4


### `src/tests/smt_incremental_test.zig` — 3

- SMT push/pop: контекст ИЗОЛИРОВАН (нет протечки между мутантами)
- SMT push/pop: пачка из 50 «мутантов» — нет ложных proved
- SMT push/pop: 30 запросов в ОДНОМ процессе быстрее 30 отдельных


### `src/tests/z3_crash_test.zig` — 4

- Z3 CRASH: решатель завершается сразу -> ToolError, KERN жив
- Z3 CRASH: 1 МБ в мёртвый пайп -> нет SIGPIPE, ToolError
- Z3 CRASH: несуществующий бинарник решателя -> ToolError (spawn fail)
- Z3 CRASH: Врата НЕ открываются при мёртвом решателе (fail-closed)


## KERN-Next (парсер, каталог, конвейер)


### `src/next/ast.zig` — 12

- AST: Status.fromString знает ВСЕ объявленные статусы
- AST: Status.fromString отвергает неизвестное (регистр важен)
- AST: conflicted — часть словаря статусов (Белнап B)
- AST: Kind.fromString и RelationKind.fromString — круговой обход
- AST: nodeCount считает проект + все коллекции
- AST: stableId детерминирован и формата kind:name
- AST: stableId различает вид при том же имени
- AST: slugify — нижний регистр, пробелы в подчёркивания
- AST: slugify сохраняет длину (не расширяется в байтах)
- AST: slugify понижает КИРИЛЛИЦУ (дефект #54)
- AST: slugify идемпотентен (повторная нормализация не меняет)
- AST: isKnownStatus согласован со Status.fromString


### `src/next/cache.zig` — 2

- УТЕЧКИ: Cache.load/save полностью освобождаются (testing.allocator)
- CACHE: хэш стабилен, неизменённый файл распознаётся


### `src/next/catalog.zig` — 4

- CATALOG: схема, вставка проекта и запрос по статусу
- CATALOG РЕГРЕССИЯ: одинарная кавычка в id/тексте не ломает SQL
- SQL-ИНЪЕКЦИЯ: кавычки в version/root/kind/code экранируются
- PARSER РЕГРЕССИЯ: повторный evidence дедуплицируется


### `src/next/engine.zig` — 1

- ENGINE: build пишет каталог, снапшот, packet и report


### `src/next/export.zig` — 3

- EXPORT: agent packet содержит proven/blocked и валиден как JSON-структура
- EXPORT: human report содержит разделы
- ФИКС JSON: управляющие символы экранируются (валидный JSON)


### `src/next/parser.zig` — 5

- PARSER: полный проект из примера §6
- PARSER: неизвестный статус даёт диагностику, но не падает
- PARSER: стабильный ID не меняется при повторном разборе
- ФАЗЗИНГ: случайные и битые .kern не паникуют
- ФИКС: нечисловая метрика — ОШИБКА, а не ложный ноль


### `src/next/snapshot.zig` — 3

- SNAPSHOT: сборка детерминирована и отсортирована
- УТЕЧКИ: Snapshot/Diff полностью освобождаются (проверка testing.allocator)
- DIFF: добавленное утверждение видно


### `src/next/truth.zig` — 4

- TRUTH: один зелёный тест переводит claim в tested (N -> T)
- TRUTH: один красный тест переводит claim в refuted (n=1)
- TRUTH КЛЮЧЕВОЙ: зелёный + красный = КОНФЛИКТ B (не перезапись!)
- ФИКС: NaN/битая метрика exit_code не паникует


### `src/next/validate.zig` — 2

- VALIDATE: чистый проект без ошибок
- VALIDATE: битый хэш и дубликат ID ловятся


## Среда исполнения


### `src/runtime/kern_x.zig` — 5

- KERN-X: HALT завершает, топливо остаётся
- KERN-X: исчерпание топлива невозможно обойти (бесконечный цикл)
- KERN-X: неизвестный опкод отвергается
- KERN-X: PUSH/STORE/LOAD/ADD работают
- KERN-X: STORE за границей памяти отвергается


## Корень `src/`


### `src/atomic_write.zig` — 3

- ATOMIC: файл записан целиком, .tmp не остаётся
- ATOMIC: перезапись поверх — старое содержимое не смешивается с новым
- ATOMIC: пустые данные — валидный пустой файл


### `src/attest.zig` — 6

- АТТЕСТАЦИЯ: валидный сертификат проверяется
- АТТЕСТАЦИЯ: подмена вердикта отвергается
- АТТЕСТАЦИЯ: подмена Merkle-корня отвергается
- АТТЕСТАЦИЯ: чужой ключ не подтверждает подпись
- АТТЕСТАЦИЯ: сериализация сертификата (round-trip) — 136 байт
- АТТЕСТАЦИЯ: битый сертификат отвергается (magic/версия)


### `src/compat.zig` — 1

- COMPAT: io доступен в тестах


### `src/concolic.zig` — 3

- CONCOLIC: обычный перебор НЕ находит магические байты (2^32 вариантов)
- CONCOLIC (РЕАЛЬНЫЙ Z3): магическая строка за число шагов = длине
- CONCOLIC: без решателя движок не падает (фолбэк по ветви)


### `src/owner.zig` — 3

- АВТОРСТВО: ключ-замок валиден (подпись соответствует публичному ключу)
- АВТОРСТВО: подмена подписи отвергается
- АВТОРСТВО: tokenHex даёт ожидаемую строку


### `src/proof_cache.zig` — 7

- PROOF-CACHE: второй вызов берётся из кэша
- PROOF-CACHE: ключ зависит от payload
- КЭШ: ключ детерминирован (нет коллизий разных формул)
- КЭШ: эвикция при переполнении (без утечек)
- КЭШ: efficiencyPct считает правильно
- SINGLE-FLIGHT ПО КЛЮЧУ: РАЗНЫЕ формулы считаются ПАРАЛЛЕЛЬНО
- ПЧЕЛИНЫЙ РОЙ: 64 потока -> 1 miss + 63 hits (single-flight)


---

## Внешние бенчмарки (не в `zig test`, запускаются отдельно)

| Бенчмарк | Команда | Результат | Модель нужна? |
|:--|:--|:--|:--:|
| **SWE-bench Lite** (Принстон/OpenAI, Docker) | `swebench.harness.run_evaluation` | **3/3 resolved**, 0 infra-failures | нет |
| **QuixBugs** (31 алгоритм с багами) | `python3 tools/quixbugs_full.py` | **31/31 багов** реальным исполнением | нет |
| **Refactory** (дифференциальный) | `python3 tools/refactory_diff.py` | 1438/1782 (80.7%) | нет |
| **Hacker's Delight / Alive2** | `zig run src/smt_bench.zig` | **8/8** (6 доказано, 2 контрпримера) | нет |
| **CHC / Horn (стиль SV-COMP)** | `zig run src/chc_bench.zig` | **11/11** совпало с ожиданием | нет |
| **HumanEval / HumanEval+** (EvalPlus, NeurIPS) | `tools/humaneval_api.py` + `evalplus.evaluate` | base **0.524**, plus **0.500** | **да (API)** |
| **CyberSecEval** (Meta) | `python3 tools/cyberseceval_check.py` | 28/351 (8.0%) — простые правила | нет |
| **SMT-LIB / cvc5 cross-check** | `python3 tools/solver_crosscheck.py` | 9/9 согласие, 0 расхождений | нет |
| **Кросс-архитектура** | `./tools/cross_arch_test.sh` | ARM64 и POWERPC64 (big-endian): **188/188** | нет |
| **Мутационное тестирование** | `python3 tools/mutate_zig.py` | 40 мутантов: 37 убито, 3 эквивалентных | нет |
| **Фаззинг парсера** | `zig run src/fuzz_ast.zig` | **1 000 000** мутаций, 0 паник / 0 SIGSEGV | нет |
| **Стресс .kimg** | `zig run src/kimg_stress.zig` | 1 млн объектов, случайный доступ 0.0006 мс | нет |
| **Производительность** | `make perf` | RAW 55–76 ГБ/с · безопасное чтение 164–231 МБ/с | нет |
| **Покрытие решений** | `make coverage` | **100.0%** (30/30, порог 95%) | нет |
| **Сбои памяти (SIGBUS)** | `zig build test-fault` | 3/3, реальный mprotect | нет |

---

## Как запускать

```bash
# --- Всё сразу ---
make test-all          # ядро + KERN-Next + Lean + бенчмарки
make formal-ci         # ядро + Lean-доказательства
make echelons          # 4 эшелона: выравнивание, лавина хэша, пул, семантика

# --- Ядро ---
zig build test         # 188 тестов ядра (Debug)
zig test src/test_root.zig -O ReleaseSafe   # без UB
zig build test-next    # 25 тестов KERN-Next
zig build test-fault   # сбои памяти (реальный SIGBUS)

# --- Формальные доказательства ---
./formal/check.sh      # 7 файлов Lean 4, 0 errors, 0 sorry

# --- Артефакты ---
zig build              # kernc, kernx, kern-attack
zig build lib          # libkern.so + libkern.a + include/kern.h (C-ABI)

# --- Демонстрации ---
make demo              # сквозной прогон kernc + kernx
make bridge            # мост «текст → контракт»: фраза → .smt2 → e=1
make audit             # 5 теорий SMT на реальном Z3
make attack            # демонстрация закрытых атак
```

---

## Что означает «тест пройден» в KERN

| Уровень | Критерий |
|:--|:--|
| `TESTED` | `zig test` → exit 0, без утечек (`testing.allocator`) |
| `MEASURED` | есть команда + код возврата + число |
| `e=1` | вердикт внешнего решателя (Z3 `unsat`) или подтверждённое исполнение |
| `e=0` | нет машинной опоры — **честный отказ**, не «неизвестно» |

> Тест, который «зелёный», но ничего не проверяет, в KERN считается
> **вакуумным** и блокируется (анти-вакуумная проверка `assert` в
> `tools/kern_exec_runner.py`).
