# KERN — Матрица трассируемости (Traceability Matrix)

> Назначение: DO-330 / ISO 26262-8 (Tool Qualification) и Common Criteria.
> Без матрицы трассируемости аудит не принимается: каждое требование к
> инструменту (TOR) обязано иметь ПРОВЕРЯЕМОЕ свидетельство.
>
> Все записи ниже — не декларации, а прогоны. Колонка «Свидетельство» —
> файл и имя теста, которые можно выполнить командой `zig build test`.

**Версия:** v1.3 · **Дата:** 2026-10-11 · **Всего тестов ядра:** 155
**Команды прогона:** `zig build test` · `zig build test-next` · `zig build test-fault` · `./formal/check.sh`

---

## 1. Формальная основа (Belnap B₄)

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-BEL-001 | Решётка Белнапа-Данна B₄: операции Join/Meet по полной таблице | `src/tests/exhaustive_suite.zig` :: `MATH-01: таблица Белнапа-Данна B4 (Join и Meet)` | ✅ |
| TOR-BEL-002 | Законы де Моргана в порядке истинности | `src/tests/exhaustive_suite.zig` :: `MATH-02: законы де Моргана…` | ✅ |
| TOR-BEL-003 | `joinK` коммутативен/ассоциативен/идемпотентен | `formal/KernAllMath.lean` (Lean 4, 0 sorry) | ✅ |
| TOR-BEL-004 | Изоляция конфликта: `T ⊔ F = B` (не перезапись!) | `formal/KernAllMath.lean` :: `contradiction_isolation` | ✅ |
| TOR-BEL-005 | Анти-вакуум: пустое предусловие не даёт `T` | `src/tests/exhaustive_suite.zig` :: `AI-03: вакуумное предусловие…` | ✅ |

## 2. Врата Истины (Admission Gate)

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-GATE-001 | Вердикт формирует ТОЛЬКО внешний чекер (не payload ИИ) | `src/tests/exhaustive_suite.zig` :: `ФИКС АТАКИ 1: ОДИН БАЙТ 0xAA НЕ даёт e=1` | ✅ |
| TOR-GATE-002 | Криптографическая привязка AST-дайджеста | `src/tests/exhaustive_suite.zig` :: `AI-02: устаревший сертификат…` | ✅ |
| TOR-GATE-003 | Маска доверия чекеров (`1 << checker_id`) | `src/tests/mcdc_gates_test.zig` :: `MC/DC-8: таблица истинности VerificationPolicy.allows` | ✅ |
| TOR-GATE-004 | Анти-вакуумная политика инвертирует исход | `src/tests/mcdc_gates_test.zig` :: `MC/DC-6`, `MC/DC-7` | ✅ |
| TOR-GATE-005 | Fail-closed: мёртвый решатель НЕ открывает Врата | `src/tests/z3_crash_test.zig` :: `Z3 CRASH: Врата НЕ открываются при мёртвом решателе` | ✅ |
| TOR-GATE-006 | MC/DC: каждое условие независимо влияет на исход | `src/tests/mcdc_gates_test.zig` :: `MC/DC-1 … MC/DC-7` | ✅ |
| TOR-GATE-007 | Таймаут решателя — это `N`, а не `F` | `src/tests/exhaustive_suite.zig` :: `RES-01: исчерпание топлива — это N, а не F` | ✅ |

## 3. Формат образа `.kimg` (L0)

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-KIMG-001 | Заголовок ровно 128 байт, выравнивание 8 (comptime) | `src/tests/alignment_stress.zig` :: `ALIGN comptime: заголовок .kimg — ровно 128 байт` | ✅ |
| TOR-KIMG-002 | Безопасная арифметика: offset bomb отвергается | `src/tests/exhaustive_suite.zig` :: `SEC-01: атака переполнения в заголовке KIMG` | ✅ |
| TOR-KIMG-003 | Merkle-корень пересчитывается и сверяется | `src/core/kimg_reader.zig` :: `KimgHeader.verifyMerkleRoot` + тесты | ✅ |
| TOR-KIMG-004 | Порча байта → `MerkleRootMismatch` (монтирование блокируется) | `src/core/kernfs_router.zig` :: TAMPER-тест | ✅ |
| TOR-KIMG-005 | Целостность СОДЕРЖИМОГО (payload), не только таблицы | `src/core/kernfs_router.zig` :: `PayloadTampered` | ✅ |
| TOR-KIMG-006 | Little-Endian декодирование всех многобайтных полей | `src/tests/alignment_stress.zig` :: `ENDIAN: многобайтные поля читаются Little-Endian` | ✅ |
| TOR-KIMG-007 | Невыровненный разбор безопасен (ARM64/RISC-V) | `src/tests/alignment_stress.zig` :: `ALIGN runtime: … смещения 1,2,3,5,7` | ✅ |

## 4. Виртуальная ФС (KERNFS)

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-FS-001 | Path traversal и NUL-инъекция отвергаются | `src/tests/exhaustive_suite.zig` :: `SEC-03` | ✅ |
| TOR-FS-002 | Запись запрещена (`AccessDenied`) | `src/core/kernfs_router.zig` :: тест `AccessDenied` | ✅ |
| TOR-FS-003 | Zero-copy чтение объектов (без копирования) | `src/perf_bench.zig` (51 ГБ/с) | ✅ |

## 5. SMT-мост и теории

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-SMT-001 | Отсутствие решателя → `ToolError`, не паника | `src/verifier/z3_bridge.zig` :: `Z3BRIDGE: отсутствие z3 не роняет мост` | ✅ |
| TOR-SMT-002 | Жёсткий таймаут решателя (поток-убийца) | `src/verifier/z3_bridge.zig` :: тесты таймаута | ✅ |
| TOR-SMT-003 | Крах решателя → нет SIGPIPE, KERN жив | `src/tests/z3_crash_test.zig` :: `1 МБ в мёртвый пайп` | ✅ |
| TOR-SMT-004 | Инкрементальный `push/pop`: нет протечки контекста | `src/tests/smt_incremental_test.zig` :: `контекст ИЗОЛИРОВАН` | ✅ |
| TOR-SMT-005 | 50 мутантов без ложных `proved` | `src/tests/smt_incremental_test.zig` :: `пачка из 50 «мутантов»` | ✅ |
| TOR-THEORY-001 | Теория массивов: аксиомы Маккарти доказаны | `src/verifier/array_theory.zig` :: `ARRAY (РЕАЛЬНЫЙ Z3)` | ✅ |
| TOR-THEORY-002 | CHC/Horn: синтез инвариантов циклов | `src/verifier/chc.zig` + `src/chc_bench.zig` (11/11) | ✅ |
| TOR-THEORY-003 | Строки QF_S: разрыв санитайзера обнаруживается | `src/verifier/string_theory.zig` :: `STRINGS (РЕАЛЬНЫЙ Z3)` | ✅ |
| TOR-THEORY-004 | UNSAT-core: локализация виновной строки | `src/verifier/unsat_core.zig` :: `UNSAT CORE (РЕАЛЬНЫЙ Z3)` | ✅ |
| TOR-THEORY-005 | CEGIS: синтез доказан на всей области (2³²) | `src/verifier/cegis.zig` :: `CEGIS (РЕАЛЬНЫЙ Z3)` | ✅ |
| TOR-SMT-006 | Независимый кросс-чек вторым решателем (cvc5) | `tools/solver_crosscheck.py` (9/9, 0 расхождений) | ✅ |

## 6. Кэш доказательств

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-CACHE-001 | Ключ кэша криптографически зависит от payload | `src/proof_cache.zig` :: `ключ зависит от payload` | ✅ |
| TOR-CACHE-002 | Потокобезопасность + single-flight (1 miss + 63 hits) | `src/proof_cache.zig` :: `ПЧЕЛИНЫЙ РОЙ: 64 потока` | ✅ |
| TOR-CACHE-003 | Эвикция при переполнении без утечек | `src/proof_cache.zig` :: `эвикция при переполнении` | ✅ |
| TOR-CACHE-004 | Устойчивость к Hash Flooding (лавина 50 %, цепочка ≤ 8) | `tools/cache_avalanche_bench.py` | ✅ |

## 7. Ресурсы ОС и отказоустойчивость

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-OS-001 | Нет утечек файловых дескрипторов (50 запросов) | `src/verifier/z3_bridge.zig` :: `РЕСУРСЫ: 50 запросов Z3 не текут FD` | ✅ |
| TOR-OS-002 | Нет процессов-зомби (`wait()` пожинает) | тот же тест (`countZombieChildren == 0`) | ✅ |
| TOR-OS-003 | Пул решателей: 128 запросов на 4–8 воркеров без голодания | `src/tests/pool_saturation.zig` (4 теста) | ✅ |
| TOR-OS-004 | Дефицит памяти → `error.OutOfMemory`, не panic | `src/tests/oom_stress.zig` (3 теста) | ✅ |
| TOR-OS-005 | Реальный SIGBUS/SIGSEGV на mmap перехвачен (процесс жив) | `src/tests/fault_injection_test.zig` (2 теста) | ✅ |
| TOR-OS-006 | Атомарная запись образа (crash-consistency) | `src/core/kimg_writer.zig` :: тест crash-consistency | ✅ |

## 8. Безопасность и авторство

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-SEC-001 | Троян в reserved-байтах отвергается | `src/tests/exhaustive_suite.zig` :: `SEC-02` | ✅ |
| TOR-SEC-002 | Фаззинг парсера: 0 паник на битых входах | `src/next/parser.zig` :: фаззинг-тест | ✅ |
| TOR-SEC-003 | Аттестация вердикта (Ed25519), подмена отвергается | `src/attest.zig` (6 тестов) | ✅ |
| TOR-SEC-004 | Аттестация `.kimg`: подмена образа/сертификата отвергается | `kernc attest verify` + `src/attest.zig` | ✅ |
| TOR-SEC-005 | Ключ-замок авторства валиден (вшитый публичный ключ) | `src/owner.zig` :: `АВТОРСТВО: ключ-замок валиден` | ✅ |
| TOR-SEC-006 | Токен автора физически присутствует в бинарнике | `strings zig-out/bin/kernc \| grep ed53cd2f…` | ✅ |

## 9. Воспроизводимость сборки

| ID | Требование | Свидетельство | Статус |
|:--|:--|:--|:--|
| TOR-BUILD-001 | Герметичная статическая сборка (x86_64-linux-musl) | `zig build hermetic` → ELF static | ✅ |
| TOR-BUILD-002 | Бит-в-бит воспроизводимость sha256 при пересборке | 2 сборки → `a2a09f14…` (идентичны) | ✅ |
| TOR-BUILD-003 | C-ABI: встраивание без CLI-процесса | `zig build lib` → `libkern.so` + `include/kern.h` | ✅ |
| TOR-BUILD-004 | Отсутствие UB: тесты проходят в ReleaseSafe | `zig test -O ReleaseSafe src/test_root.zig` | ✅ |

---

## Сводка

| Категория | Требований | Покрыто |
|:--|--:|--:|
| Belnap B₄ | 5 | 5 |
| Врата Истины | 7 | 7 |
| Формат `.kimg` | 7 | 7 |
| KERNFS | 3 | 3 |
| SMT и теории | 11 | 11 |
| Кэш | 4 | 4 |
| Ресурсы ОС | 6 | 6 |
| Безопасность | 6 | 6 |
| Сборка | 4 | 4 |
| **ИТОГО** | **53** | **53** |

**Не покрыто (честно):** верификация на уровне машинного кода
(binary-level soundness / translation validation LLVM) — вне объёма v1.3,
см. `SOUNDNESS_ARGUMENT.md`, раздел «Границы».
