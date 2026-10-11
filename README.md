# KERN — ядро проверки истины для ИИ-агентов

**Арбитражный шлюз истины для ИИ-агентов.** Заявление получает статус
«доказано» **только при машинной опоре**: вердикт SMT-решателя (Z3), формальное
доказательство (Lean 4) или подтверждённый прогон с кодом возврата.
Всё остальное — честный отказ `e=0`.

**Технологии:** Zig 0.13 (ядро, zero-copy) · Lean 4 (формальные доказательства) ·
Z3 (SMT) · SQLite (каталог KERN-Next) · C-ABI (`libkern.so`).

| Показатель | Значение |
|:--|:--|
| Тесты ядра | **188** (Debug + ReleaseSafe) |
| Тесты KERN-Next | **25** |
| Формальные доказательства | **7 файлов Lean 4**, 0 errors, 0 `sorry` |
| Покрытие инструментированных решений | **100.0%** (30/30) |
| Мутационный score | 92.5% (37/40; 3 эквивалентных → эффективно 100%) |
| Кросс-архитектура | ARM64 и POWERPC64 (big-endian): **188/188** |
| SWE-bench Lite (Docker) | **3/3 resolved**, 0 infra-failures |
| QuixBugs | **31/31** багов реальным исполнением |
| Фаззинг | **1 000 000** мутаций, 0 паник |
| **Полный каталог тестов** | **[`docs/TEST_CATALOG.md`](docs/TEST_CATALOG.md)** |
| **Возможности с доказательствами** | **[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md)** — 11 пунктов: ✅ / ⚠️ / ❌ |
| **Аттестационный паспорт** | **[`docs/ATTESTATION_PASSPORT.md`](docs/ATTESTATION_PASSPORT.md)** — все показатели + сводка поправок |

> **Отдельный проект.** Не часть `nyuui-core`. `nyuui` может им пользоваться,
> но живёт и развивается самостоятельно.

**Статус:** рабочий прототип с измеренными свойствами. Эпистемическая часть
(Врата Истины) исправлена в v1.3 — обход «одним байтом» закрыт, вердикт приходит
только от внешнего чекера (см. `docs/KERN_FIXES_v1_3.md`).

---

## 0. Быстрый старт (5 минут)

```bash
# 1. Окружение: Zig 0.13 в локальный venv (системный Zig не нужен)
make venv && export PATH="$PWD/.venv/bin:$PATH"

# 2. Сборка: kernc (ядро), kernx (KERN-Next), kern-attack (демонстрация)
zig build

# 3. Тесты ядра — 188 штук
zig build test

# 4. Эталонный образ и его проверка
make golden
./zig-out/bin/kernc check-integrity tests/fixtures/valid_v1_3.kimg

# 5. Сквозная демонстрация (сборка образа, чтение, Врата, KERN-Next)
make demo
```

**Увидеть вердикт `e=1` (ДОКАЗАНО)** — нужен Z3:
```bash
uv pip install --python .venv/bin/python z3-solver
./zig-out/bin/kernc prove formal/example.smt2     # e=1 — доказано решателем
make bridge                                        # мост «текст → контракт»
```

**Список всех целей:** `make help`

**Аттестационный статус одной командой** (все строки — реальные прогоны):
```bash
make audit-manifest
```
```
[KERN QUALIFICATION AUDIT SUITE v1.3.1]
Core (Debug)          : PASS — 188/188 tests
Memory Safety         : PASS — ReleaseSafe, 0 UB
Kernel Invariants     : PASS — Lean 4 (7 files, 0 errors, 0 sorry)
Target Systems        : PASS — ARM64 POWERPC64
Attack Surface        : PASS — 2/2 (0xAA-обход закрыт, KERNFS согласован)
Decision Coverage     : PASS — 100.0% (порог 95%)
Mutation Coverage     : PASS — 92.5%
Formal Theories       : PASS — 5/5 (UNSAT-core, QF_AX, CHC, QF_S, CEGIS)
Payload Integrity     : PASS — Merkle + SHA-256 (PayloadTampered)
```

**Детерминированный симулятор** (VOPR-стиль, как TigerBeetle):
```bash
make sim    # 80 000 операций, 4 сида, инварианты I1–I4
```
Тот же сид даёт ту же историю на любой машине; при падении сид воспроизводит
его с точностью до операции.

---

## 1. Состав

```
kern/
├── README.md                       этот файл
├── LICENSE                         MIT
├── OWNERSHIP.md                    защита авторства (токен, ключ-замок)
├── Makefile                        62 цели: build/test/coverage/mutate/bridge/…
├── build.zig                       сборка: kernc, kern-attack, kernx, libkern.so
│
├── docs/                           ДОКУМЕНТАЦИЯ (начните с docs/README.md)
│   ├── README.md                   КАРТА документации — что где лежит
│   ├── TEST_CATALOG.md             ПОЛНЫЙ каталог 213 тестов + бенчмарки
│   ├── METRICS.md                  ЖУРНАЛ ПОКАЗАТЕЛЕЙ (все цифры из прогонов)
│   ├── KERN_FIXES_v1_3.md          16 устранённых дефектов, с доказательствами
│   ├── VERIFICATION_GOLD_STANDARDS.md  мировые бенчмарки
│   ├── EXECUTION_RUNNER.md         переход N→T через машинные свидетельства
│   ├── SPEC_ANCHORS_DEMO.md        мост «текст → контракт» (@kern:spec)
│   ├── KERN_TERMINOLOGY_v0.1.md    нормативная терминология
│   ├── evidence/                   свидетельства прогонов (JSON/JSONL)
│   └── archive/                    исторические аудиты (KERN*_AUDIT.md)
│
├── formal/                         ФОРМАЛЬНЫЕ ДОКАЗАТЕЛЬСТВА
│   ├── check.sh                    компиляция всех теорем + проверка на 'sorry'
│   ├── KernAllMath.lean            Белнап, де Морган, JOIN_K, анти-вакуум
│   ├── KernDfsTermination.lean     завершаемость, граница топлива
│   ├── KernTalk.lean / KernTalkND.lean   унификация требований
│   ├── KernConvergence.lean        сходимость итерации
│   ├── KernZeroCopy.lean           изоморфизм zero-copy
│   ├── KernSemanticGap.lean        разрыв ℤ ↔ i32
│   ├── gate_mask.smt2              контракт для моста (пример)
│   └── certification/              TQD: трассируемость, soundness, security target
│
├── src/                            ИСХОДНИКИ
├── tools/                          утилиты: сканер, бенчмарки, мутатор, раннер
├── tests/                          фикстуры и внешние сьюты
├── examples/                       примеры .kern, C-ABI демо
├── archive/                        сырые материалы (лог чата-спецификации)
└── REVISION/                       честный статус возможностей
```

**Карта документации:** [`docs/README.md`](docs/README.md)
**Полный каталог тестов:** [`docs/TEST_CATALOG.md`](docs/TEST_CATALOG.md)

---

## 2. Зачем это

KERN — «таможня истины» между ИИ-агентом и реальным кодом. Идея:

1. ИИ генерирует код и **утверждение** («функция безопасна», «тесты прошли»).
2. Утверждение допускается только при **машинной опоре** (прогон, доказательство).
3. Следующему агенту передаётся **компактный пакет**: что доказано, что
   проверять, что открыть, что нельзя трогать.

Математическая основа — **решётка Белнапа-Данна B4**: факт имеет два независимых
бита (подтверждение `p` и опровержение `n`).

| код | статус | смысл |
|:--:|:--|:--|
| 0 | **N** | ничего не известно (гипотеза ИИ) |
| 1 | **T** | доказано |
| 2 | **F** | опровергнуто (найден контрпример) |
| 3 | **B** | конфликт: тесты зелёные, но прувер нашёл баг |

---

### 1.1 Подробнее: `src/` и `tools/`

```
├── main.zig                        CLI kernc (читает образ .kimg)
├── attack.zig                      демонстрация: обе атаки закрыты
├── test_root.zig                   корень тестов ядра (188 тестов)
├── core/
│   ├── eq2.zig                     KERN-EQ2: Белнап, joinK/meetK, andT/orT/notB
│   ├── object_entry.zig            96-байтный дескриптор + Merkle-корень
│   ├── kimg_reader.zig             128-байтный заголовок + безопасная арифметика
│   ├── kimg_writer.zig             сборка .kimg (атомарная запись + fsync)
│   ├── kernfs_router.zig           VFS: валидация путей, монтирование, AccessDenied
│   ├── mmap_guard.zig              перехват SIGBUS (обрыв mmap)
│   └── sigbus_guard.zig            обработчик сигнала
├── verifier/
│   ├── admission_gate.zig          Врата Истины: вердикт ТОЛЬКО от внешнего чекера
│   ├── z3_bridge.zig               Z3 SMT-LIB2 мост (таймаут, graceful)
│   ├── unsat_core.zig              локализация ошибки (get-unsat-core)
│   ├── array_theory.zig            QF_AX: аксиомы Маккарти, алиасинг
│   ├── chc.zig                     CHC/Horn: инварианты циклов (SPACER)
│   ├── string_theory.zig           QF_S: инъекции, path traversal
│   ├── cegis.zig                   CEGIS/SyGuS: синтез кода
│   ├── proof_check.zig             независимая проверка шагов Z3
│   ├── dtmc.zig                    вероятностный анализ (PCTL)
│   ├── abstract_interp.zig         абстрактная интерпретация (интервалы)
│   ├── noninterference.zig         невмешательство (HyperLTL)
│   ├── nra_quant.zig               нелинейная арифметика + кванторы
│   └── redos.zig                   ReDoS-анализ регулярных выражений
├── runtime/kern_x.zig              KERN-X: fuel-bounded VM (без зависаний)
├── next/                           KERN-Next (движок `kernx`, 25 тестов)
│   ├── ast.zig · parser.zig        модель + парсер языка .kern
│   ├── validate.zig                валидатор (10 правил)
│   ├── catalog.zig                 SQLite-каталог .kdb
│   ├── snapshot.zig · cache.zig    снапшоты/diff + инкрементальность
│   ├── export.zig · engine.zig     agent packet, отчёт, конвейер
│   ├── truth.zig                   Белнап-аккумулятор (N→T/F/B)
│   └── main.zig                    CLI kernx
├── proof_cache.zig                 кэш доказательств (потокобезопасный)
├── attest.zig · owner.zig          аттестация Ed25519 + токен авторства
├── atomic_write.zig                атомарная запись (tmp+fsync+rename)
├── capi.zig                        C-ABI (libkern.so, 7 функций)
├── concolic.zig                    конколическое исполнение
├── fuzz_ast.zig                    1 000 000 мутаций, 0 паник
├── smt_stress.zig · kimg_stress.zig  стресс Z3 и .kimg (1 млн объектов)
├── perf_bench.zig · smt_bench.zig · chc_bench.zig · stress_real.zig  бенчмарки
└── tests/
    ├── exhaustive_suite.zig        security-сьют (SEC/MATH/AI/RES)
    ├── alignment_stress.zig        Эшелон 1: выравнивание + endianness
    ├── pool_saturation.zig         Эшелон 3: изнурение пула потоков
    ├── mcdc_gates_test.zig         MC/DC-векторы решений Врат
    ├── litmus_memory_test.zig      слабые модели памяти
    ├── oom_stress.zig · z3_crash_test.zig · smt_incremental_test.zig
    ├── fault_injection_test.zig    сбои памяти (SIGBUS)
    └── coverage_report_test.zig    покрытие инструментированных решений

├── tools/
│   ├── scan_to_kern.py             сканер проекта → .kern (+ якоря @kern:spec)
│   ├── golden_v1_3.py              эталонный образ .kimg v1.3
│   ├── kern_exec_runner.py         Execution Runner (N→T через прогон)
│   ├── mutate_zig.py               мутационное тестирование (работает на копии)
│   ├── quixbugs_full.py            QuixBugs 31/31
│   ├── refactory_diff.py           Refactory (дифференциальный)
│   ├── solver_crosscheck.py        Z3 ↔ cvc5
│   ├── cache_avalanche_bench.py    лавина хэша (100 000 мутаций)
│   ├── humaneval_api.py            HumanEval/HumanEval+ через API
│   ├── binlevel_verify.py/.sh      бинарный уровень (translation validation)
│   ├── cross_arch_test.sh          ARM64 + POWERPC64 под QEMU
│   └── push_to_github.sh           выгрузка закрытого репозитория
```

---

## 3. Запуск

```bash
# 1. Компилятор Zig 0.13 (более новые версии НЕ подходят)
uv venv .venv
uv pip install --python .venv/bin/python ziglang==0.13.0
export PATH="$PWD/.venv/bin:$PATH"

# 2. Эталонный образ
python3 tools/golden_v1_3.py

# 3. Сборка (kernc, kern-attack, kernx)
zig build

# 4. Тесты: ядро (36) и KERN-Next (12)
zig build test
zig build test-next        # требует libsqlite3

# 5. Демонстрация: обе атаки закрыты
./zig-out/bin/kern-attack

# 6. CLI kernc
./zig-out/bin/kernc check-integrity tests/fixtures/valid_v1_3.kimg
./zig-out/bin/kernc ls  tests/fixtures/valid_v1_3.kimg
./zig-out/bin/kernc cat tests/fixtures/valid_v1_3.kimg /raw/src/main.zig
./zig-out/bin/kernc verify tests/fixtures/valid_v1_3.kimg

# 6a. РЕАЛЬНОЕ доказательство через Z3 (e=1) — нужен z3 в PATH
uv pip install z3-solver                      # даёт бинарник .venv/bin/z3
export PATH="$PWD/.venv/bin:$PATH"
./zig-out/bin/kernc prove formal/example.smt2 # e=1 ДОКАЗАНО / e=0 (контрпример)
./zig-out/bin/kernc audit                    # 5 теорий: UNSAT-core, массивы, CHC, строки, CEGIS
make theories                                # те же 5 теорий тестами
make echelons                                # 4 эшелона: выравнивание, лавина, пул, семант. разрыв

# 6b. Финальная спецификация: сборка, унификация, KERN-X, handoff
./zig-out/bin/kernc build examples/project.kern -o release.kimg
./zig-out/bin/kernc unify 50 120            # RLAIF: конфликт + градиент ошибки
./zig-out/bin/kernc run release.kimg --fuel 100   # KERN-X (если есть байткод)
./zig-out/bin/kernc handoff release.kimg    # agent_packet.json из образа

# 7. KERN-Next
./zig-out/bin/kernx build examples/project.kern --out .kernnext --scope issue-42
./zig-out/bin/kernx status examples/project.kern
./zig-out/bin/kernx report examples/project.kern
./zig-out/bin/kernx packet examples/project.kern --scope issue-42
./zig-out/bin/kernx diff <snapA> <snapB>

# 8. Формальные доказательства Lean 4 (0 ошибок, 0 sorry)
./formal/check.sh
```

---

## 4. Что **работает** (измерено)

| Свойство | Как проверено |
|:--|:--|
| **Zero-copy чтение через mmap** | срез памяти, копирования нет |
| **CONF-13: path traversal** | все отказы: нет `/`, `//`, `.`, `..`, NUL |
| **CONF-15: reserved-байты** | порча байта 95 → `InvalidReservedBytes` |
| **Безопасная арифметика** | offset bomb → `OutOfBoundsOffset` в Debug И ReleaseFast |
| **Алгебра Белнапа** | таблицы join/meet, законы де Моргана полным перебором |
| **Merkle-корень** | пересчёт совпадает; подмена байта → `MerkleRootMismatch` |
| **Врата Истины** | `e=1` только по вердикту внешнего чекера; 0xAA → `e=0` |
| **KERNFS находит объекты** | `/raw/...`, `/claims/.../status`, `/claims/.../contract.json` |
| **Запись запрещена** | `write()` → `AccessDenied` (CONF-06) |
| **CLI читает образ** | `check-integrity`, `ls`, `cat`, `verify`, `report` |
| **KERN-Next конвейер** | `.kern` → SQLite-каталог → snapshot → packet/report → diff |
| **Инкрементальность** | неизменённый `.kern` → обработка пропускается |
| **Сборка .kern → .kimg** | `kernc build` → образ v1.3, читается KERNFS |
| **RLAIF-унификация** | `kernc unify 50 120` → конфликт `B` + градиент ошибки 70 |
| **KERN-X (топливо)** | `kernc run` → `HALT OK` или `OutOfFuel` (зависание невозможно) |
| **Z3-мост** | `uv pip install z3-solver` → **реальный прувер**: `kernc prove` → `e=1` (доказано) / `e=0` (контрпример) |
| **SMT-стресс** | 18/18: парадокс `x>5∧x<2`→vacuous, overflow i32→контрпример, NIA `x*x≥0`→proved, Alive2-пары |
| **Кросс-проверка решателей** | Z3 ↔ cvc5: **9/9 согласие, 0 расхождений** |
| **Целостность payload** | подмена байта содержимого → `PayloadTampered` |
| **Ресурсы ОС** | 0 утечек FD, 0 зомби-процессов, «пчелиный рой» 64 потока → 1 miss + 63 hits |
| **Crash-consistency** | атомарная запись (temp + rename) — нет битых образов |
| **Эшелон 1: выравнивание** | 8/8: невыровненный разбор (смещения 1,2,3,5,7) безопасен на ARM64/RISC-V |
| **Эшелон 2: лавина хэша** | SHA-256: лавина **50.0%**, 0 коллизий, макс. цепочка **7** (наивный: 3.1%, цепочка 100000) |
| **Эшелон 3: пул потоков** | 128 запросов на 4–8 воркеров: лимит соблюдён, голодания нет |
| **Эшелон 4: семант. разрыв** | `KernSemanticGap.lean`: **8 теорем** — разрыв ℤ vs i32 доказан формально |
| **UNSAT Core (локализация)** | `(get-unsat-core)` → точные имена конфликтующих строк (`line_10`, `goal`) |
| **Теория массивов (QF_AX)** | аксиомы Маккарти: `select(store(a,i,v),i)=v` и независимость ячеек — **ДОКАЗАНО** |
| **CHC / Horn (инварианты циклов)** | `set-logic HORN` (SPACER): `while(x<10) x++` ⇒ `x≥10` — **ДОКАЗАНО** |
| **Строки (QF_S)** | санитайзер `/` без `..` → **УЯЗВИМОСТЬ**; нуль-байт достижим |
| **CEGIS (синтез кода)** | по спецификации `x*8` **синтезировано `x<<3`** (доказано на 2³² входах) |
| **Перехват SIGBUS (реальный)** | `siglongjmp`: чтение PROT_NONE и обрезанный mmap-файл — **3/3**, процесс жив |
| **Аттестация `.kimg`** | `kernc attest sign/verify`: Ed25519-сертификат 136 Б; подмена образа/сертификата → **отвергнуто** |
| **Покрытие решений** | `make coverage`: **100.0%** (30/30 инструментированных решений, порог 95%) |
| **MC/DC (DO-178C)** | `mcdc_gates_test.zig`: каждое условие Врат влияет независимо |
| **Инкрементальный SMT** | `push/pop`: 30 запросов **527 мс → 26 мс (20×)**; 0 ложных `proved` |
| **Крах решателя** | SIGPIPE/мёртвый пайп → KERN жив, `ToolError`, Врата закрыты |
| **OOM (2 МБ)** | `FixedBufferAllocator` → `error.OutOfMemory`, без panic |
| **Фаззинг 1M** | 1 000 000 мутаций за 362 мс → **0 паник** |
| **C-ABI** | `libkern.so` + `kern.h`: вызов из Python/C без CLI-процесса |
| **Герметичная сборка** | `zig build hermetic` → статический musl, **sha256 бит-в-бит совпадает** |
| **Tool Qualification** | `formal/certification/`: матрица 53 требований + DO-333 + CC ST |
| **Слабые модели памяти** | литмус SB/MP: `SeqCst`/`release-acquire` → **0 запрещённых исходов** |
| **Конколика (Driller/QSYM)** | `KERN` найден за **4 обращения к Z3** (перебор: ~2³²) |
| **Вероятностный чекинг (DTMC)** | PCTL `P≤p [F fail]`; 3 попытки по 0.9 → **0.001** |
| **Абстрактная интерпретация** | widening/narrowing: инвариант `[0,9]` **без SMT** |
| **Нелинейная арифметика (QF_NRA)** | ∀x,y. `x²+y²≥0` **доказано**; `x²+y²>2` — контрпример |
| **Кванторы (E-matching)** | триггеры; Matching Loop DoS обезврежен таймаутом |
| **Невмешательство (HyperLTL)** | taint: ветвление/индекс по секрету → **утечка**; constant-time ~1.0× |
| **ReDoS (CWE-1333)** | `(a+)+`, `(a|a)*` → **уязвимы**; `(a|b)*` — нет |
| **Кросс-архитектура** | **ARM64** и **POWERPC64 (big-endian)** под QEMU: **188/188** каждый |
| **Мост «текст → контракт»** | `make bridge`: фраза из Markdown → `.smt2` → **`e=1` ДОКАЗАНО** |
| **Binary-level soundness** | дайджест одинаков на Debug/ReleaseSafe/ReleaseFast (translation validation) |
| **Constant-time на ассемблере** | taint-анализ: **0** ветвлений от данных (контроль: 1 обнаружен) |

---

## 4b. Официальные мировые бенчмарки (измерено)

| Бенчмарк | Результат | Модель нужна? |
|:--|:--|:--:|
| **HumanEval** (EvalPlus, NeurIPS) | **pass@1 = 0.524** | да (API) |
| **HumanEval+** (edge-cases) | **pass@1 = 0.500** | да (API) |
| **KERN-гейт: точность блокировок** | **100.0%** (55/55, 0 ложных) | нет |
| **SWE-bench Lite** (официальный, Docker) | **3/3 resolved**, 0 infra-failures | нет |
| **QuixBugs** (реальное исполнение) | **31/31 багов (100%)** | нет |
| **Refactory** (differential) | 1438/1782 (80.7%) | нет |
| **Hacker's Delight / Alive2** (Z3) | **8/8** (6 эквивалентны, 2 контрпримера) | нет |
| **Мутационный score (Zig-код)** | **92.5%** (40 мутантов: 37 убито, 3 эквивалентных*) | нет |
| **Стресс .kimg (1 млн объектов)** | случайный доступ **0.0006 мс** (цель < 0.005) | нет |

> \* **Три выживших мутанта — эквивалентные (не дыры в тестах).** Разбор:
> 1. `kernfs_router.zig:69` `offset >= len` → `>>`: при `offset ≥ len` мутант может
>    дать `0` (для `len ≤ offset < 2^len`), но следующий цикл `while (offset+i < len)`
>    не выполняется и возвращается **пустой срез** — результат тот же, что и у
>    оригинала. Поведенчески неразличим.
> 2. `kimg_writer.zig:141` `dfd >= 0` → `dfd`: отличается только при `fd == 0`
>    (каталог через fd 0 не открывается), а `fsync(-1)` даёт ошибку, которая и так
>    игнорируется (`catch {}`).
> 3. `kernfs_router.zig:109` `compression_codec != 0` → `== 0`: **недостижимая ветвь** —
>    сжатие в формате v1.3 не реализовано, `codec` всегда 0 и
>    `compressed_size == uncompressed_size`, поэтому обе ветки дают одно число.
>
> Эффективный score = **100%** (37/37 неэквивалентных убито).
>
> ⚠️ **О скорости чтения честно.** «76 ГБ/с» — это скорость **чистой адресации**
> среза (RAW). **Безопасное** чтение (со сверкой `SHA-256(payload)` против
> digest дескриптора) идёт на **~230 МБ/с** — в 330× медленнее, потому что
> хеш-функция доминирует. Оба числа измеряются `make perf`. Раньше в отчётах
> фигурировало только RAW-число как «скорость чтения» — это исправлено.

Полные отчёты: `docs/VERIFICATION_GOLD_STANDARDS.md`, `docs/METRICS.md`.
Сырые свидетельства: `docs/evidence/`.

> ⚠️ Полный честный статус «что измерено / что нет» — в
> `REVISION/HONEST_CAPABILITY_STATUS.md`. Он обязателен к прочтению: часть
> спецификации (облако, WASM, плагины, аппаратная аттестация) — **не реализована**.

---

## 5. Что **исправлено** в v1.3 (было «НЕ работает»)

Полные доказательства — в `docs/KERN_FIXES_v1_3.md`.

| Было (v1.2) | Стало (v1.3) |
|:--|:--|
| 🔴 Врата Истины обходились **одним байтом** `0xAA` | вердикт формирует `TrustedChecker`; без внешнего чекера → `e=0` |
| 🔴 KERNFS не находил **ни одного** файла (Фазы 1/3 несовместимы) | образ v1.3: пул строк + объекты с путями + относительные смещения |
| `report` писал фиксированный текст | читает образ и строит отчёт из содержимого |
| `verify`/`ls`/`cat` — заглушки | монтируют KERNFS и реально читают образ |
| `MerkleRootMismatch` объявлен, но не возвращался | целостность действительно проверяется |
| `AccessDenied` объявлен, но возвращался `FileNotFound` | `write()` возвращает `AccessDenied` |
| маска `allowed_checkers` вела себя неочевидно | задокументирована + `VerificationPolicy.allows()` + тест |

---

## 6. KERN-Next (`kernx`)

Язык описания **проектной истины** и движок: `parse → validate → catalog →
snapshot → packet/report`, с инкрементальным кэшем.

- **Язык `.kern`**: `project`, `artifact`, `claim`, `proof`, `module`, `link`.
- **Статусы** (§7): `proven`, `refuted`, `verified`, `tested`, `compiled`,
  `empirical`, `hypothesis`, `blocked`, `unknown`, `not_found`, `not_yet_reproducible`.
- **Каталог `.kdb`**: SQLite (§9) — таблицы, индексы, CHECK по статусам.
- **Snapshot `.ksnap`**: детерминированный отсортированный текст → побайтово
  воспроизводим и удобен для `diff`.
- **Agent packet** (§17): только выжимка для следующего ИИ — proven / blocked /
  contradictions / next_steps.

Критерии готовности (§20): чтение `.kern`; SQLite-каталог; извлечение
утверждений/свидетельств/связей; snapshot; отчёт; agent packet; diff; тесты
парсера и валидатора; стабильные ID; пропуск неизменённых файлов — **все 10
выполнены** (см. `docs/KERN_FIXES_v1_3.md`, раздел «KERN-Next»).

---

## 7. Ограничения (честно)

- **Внешний прувер Z3 — сконфигурирован** (`z3-solver` через pip, без apt):
  `kernc prove` реально даёт **`e=1` (ДОКАЗАНО)** и `e=0` (контрпример);
  `kernc audit` прогоняет 5 теорий. Если `z3` нет в PATH — Врата безопасно
  деградируют в `e=0` (`ToolError`), паники нет. Lean 4 используется как
  **независимый аудитор** (7 файлов, 0 `sorry`), а не как runtime-прувер.
- **Скорость чтения**: «76 ГБ/с» — это **RAW-адресация**; безопасное чтение
  (со сверкой `SHA-256(payload)`) идёт на **~231 МБ/с** (330× медленнее). Оба
  числа печатает `make perf`. См. §4 (таблица метрик) и `docs/METRICS.md` §4.
- **`hash_algo`**: спецификация называет BLAKE3, реализация использует SHA-256.
  Алгоритм зафиксирован ОДИН (SHA-256) — иначе ломается сквозная сверка.
- **KERN-Next** использует системную `libsqlite3` (есть в окружении). Это
  единственная внешняя зависимость; правило «No Dependencies» относится к
  языку Zig, а не к системным библиотекам.
- **kernc (KIMG)** и **kernx (KERN-Next)** — два вертикальных среза одной идеи;
  их форматы (`.kimg` и `.kdb/.ksnap`) пока не связаны автоматически.

---

## 8. Связь с nyuui-core

`nyuui-core/evidence.py` реализует **родственные** идеи на Python:
типизированную уверенность, журнал решений, пакет агенту (`handoff`),
эпистемическое слияние графов и поручительство человека (Ed25519, статус
`attested` — намеренно **отдельный** от `proven`).

KERN и `nyuui-core` **не связаны кодом** — общая только идея. KERN быстрее
(mmap, zero-copy), `nyuui-core` — рабочий и покрыт тестами.

---

## Автор

* **Vital Kalinousky** — создатель и главный архитектор KERN.

## Лицензия

Этот проект распространяется под лицензией **MIT** — подробности в файле
[LICENSE](LICENSE).

```
Copyright (c) 2026 Vital Kalinousky
```

Каждый исходный файл (`src/**/*.zig`, `formal/*.lean`) содержит заголовок
Copyright — даже при копировании отдельного файла авторство сохраняется.

## Аттестация вердиктов

Вердикт `e=1` можно криптографически подписать (`src/attest.zig`, Ed25519) —
получается **сертификат удалённой аттестации**: клиент проверяет, что вердикт
выдан неизменённым ядром. В проде корень доверия — аппаратный (TPM/SGX/Nitro);
крипто-конвейер реализован и покрыт тестами.
