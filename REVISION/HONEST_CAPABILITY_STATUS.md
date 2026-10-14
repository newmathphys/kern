# HONEST CAPABILITY STATUS — KERN

**Дата:** 2026-10-10 · **Принцип:** уровень присваивается ТОЛЬКО по факту
запуска (команда → код возврата → вывод). Никаких «работает» по описанию.

Уровни: **MEASURED** (прогнано, есть число) · **TESTED** (есть тест) ·
**SMOKE** (запускается, но без строгой проверки) · **FRAMEWORK** (написан
каркас, не измерен) · **NOT IMPL** (отсутствует).

---

## 1. Что ИЗМЕРЕНО (ядро, `kernc` / Zig)

| Возможность | Уровень | Доказательство |
|:--|:--|:--|
| Сборка на Zig 0.13.0 | MEASURED | `zig build` → exit 0 |
| Алгебра Белнапа B4 (join/meet/де Морган) | TESTED | полный перебор, тесты OK |
| Заголовок .kimg (128 б) + безопасная арифметика | TESTED | SEC-01 offset bomb |
| Дескриптор .kimg (96 б) + reserved-байты | TESTED | CONF-15 |
| Merkle-корень (пересчёт + подмена) | TESTED | `MERKLE: ... ловит подмену` |
| Сборка образа .kimg v1.3 из .kern | MEASURED | `kernc build examples/project.kern` → 6 объектов |
| KERNFS (пути, статус, контракт, zero-copy) | MEASURED | `kernc cat` → `T`, `{}`, контент |
| Path-traversal / NUL-инъекция | TESTED | CONF-13, SEC-03 |
| Запись запрещена (`AccessDenied`) | TESTED | CONF-06 |
| Врата Истины: вердикт ТОЛЬКО внешний | TESTED | 0xAA → e=0 |
| Z3-мост (SMT-LIB2, дочерний процесс) | **MEASURED** | `z3-solver` установлен; `kernc prove` → **e=1 (ДОКАЗАНО)** и `e=0` (контрпример). Таймаут с потоком-убийцей. Без z3 — graceful `ToolError`→e=0 |
| KERN-X VM (топливо, HALT, опкоды) | TESTED | OutOfFuel на 10k NOP |
| Кэш доказательств (AST→вердикт) | TESTED | hits/misses, single-flight, eviction |
| CLI: build/check-integrity/ls/cat/verify/unify/run/handoff/report/audit/prove | MEASURED | все прогнаны |
| 5 теорий SMT (UNSAT-core, массивы, CHC, строки, CEGIS) | MEASURED | `kernc audit` → 5/5 отработали на реальном Z3 |
| C-ABI (`libkern.so`, 7 функций) | MEASURED | `zig build lib` + `examples/capi_demo.py` (Python) и C |

**Числа:** `zig test src/test_root.zig` → **191/191 OK** (Debug И ReleaseSafe).
Эталон `valid_v1_3.kimg` → Merkle совпадает Python↔Zig (подтверждено в обе стороны).
Покрытие решений → **100.0%** (30/30). Мутации → 92.5% (37/40; 3 эквивалентных).

---

## 1b. Формальные доказательства (Lean 4) — MEASURED

| Файл | Теоремы | Компиляция |
|:--|:--|:--|
| `formal/KernAllMath.lean` | де Морган ×2, инволюция, JOIN_K comm/assoc/idem, дистрибутивность, `contradiction_isolation : T⊔F=B`, анти-вакуум, **`fuel_bounds_influence`** | ✅ Lean 4.34.0, **0 ошибок, 0 sorry** (Pure Core) |
| `formal/KernDfsTermination.lean` | `traversal_terminates`, **`fuel_bounds_influence`** + своя лемма `foldl_congr_list` | ✅ Pure Core |
| `formal/KernTalk.lean` | `ai_hallucination_yields_conflict`, `consistent_yields_truth` | ✅ Mathlib (ℝ) |
| `formal/KernTalkND.lean` | `nd_violation_yields_conflict` (N-мерная унификация) | ✅ Mathlib |
| `formal/KernConvergence.lean` | СИЛЬНАЯ `convergence_guaranteed` + `convergence_guaranteed_weak` (настоящее следствие) | ✅ Mathlib |
| `formal/KernZeroCopy.lean` | `zero_copy_is_lossless`, `slice_subset`, `slice_idempotent` | ✅ Mathlib |
| `formal/KernSemanticGap.lean` | разрыв ℤ ↔ i32 (8 теорем) | ✅ Mathlib |

**Доказательство:** `./formal/check.sh` → `ALL LEAN PROOFS OK (0 errors, 0 sorry)`.

**Честность (исправлено 2026-10-11).** Две теоремы были **ТАВТОЛОГИЯМИ** и
заменены содержательными:
* `fuel_bounded_dfs_always_terminates` имела вид `∃ res, f u = res := ⟨_, rfl⟩` —
  в Lean все функции тотальны, поэтому такая «теорема» верна для ЛЮБОЙ функции
  и ничего не доказывает. Заменена на `fuel_bounds_influence` (топливо
  ограничивает зону влияния — реальная индукция).
* `convergence_guaranteed_weak` доказывалась свидетелем `human_max`
  (рефлексивность `≤`) и не зависела от `adapt` — теперь это настоящее
  следствие сильной теоремы.
* `traversal_terminates` честно помечена как разворот определения
  (`WellFounded r` ≡ `∀ a, Acc r a`).

Также: в документе теорема `ai_hallucination_yields_conflict` содержала `sorry`
(заглушку). Здесь она доказана по-настоящему (через `le_max_right`/`min_le_left`).

---

## 1c. Сертификационный контур (DO-178C / ISO 26262 / EAL7) — MEASURED

| Возможность | Уровень | Доказательство |
|:--|:--|:--|
| Покрытие решений (self-instrumented) | MEASURED | `make coverage` → **100.0%** (30/30, порог 95%) |
| MC/DC-векторы на решения Врат | TESTED | `src/tests/mcdc_gates_test.zig` (8 тестов) |
| Инкрементальный SMT `push/pop` | MEASURED | 527 мс → 26 мс (**20×**), 0 ложных `proved` |
| Крах решателя (SIGPIPE) | TESTED | `src/tests/z3_crash_test.zig` (4 теста), KERN жив |
| Дефицит памяти (2 МБ) | TESTED | `src/tests/oom_stress.zig` → `error.OutOfMemory` |
| Реальный SIGBUS на mmap | TESTED | `src/tests/fault_injection_test.zig` (2 теста) |
| Фаззинг 1 000 000 мутаций | MEASURED | 362 мс, **0 паник** |
| C-ABI (`libkern.so` + `kern.h`) | MEASURED | вызов из Python (`ctypes`) и C (`cc -lkern`) |
| Герметичная сборка (musl, static) | MEASURED | sha256 **бит-в-бит** совпал при 2 сборках |
| Tool Qualification Package | DONE | `formal/certification/`: 53 требования трассированы |
| Proof Checker (структурный + MUS) | TESTED | `src/verifier/proof_check.zig` |

**Ограничение (честно):** покрытие собрано **своими счётчиками**, а не LLVM
source-based coverage — Zig 0.13 не поддерживает `--coverage`, `llvm-cov`/`kcov`
в системе отсутствуют. Proof Checker — **структурный** (не полный Alethe/LFSC).

### Внешние бенчмарки (без локальных моделей)

| Бенчмарк | Результат |
|:--|:--|
| QuixBugs (реальное исполнение) | **31/31 (100%)** |
| CHC-бенчмарк циклов (SV-COMP стиль) | **11/11**, 424 мс |
| SMT (Alive2 / Hacker's Delight) | **8/8** |
| Кросс-чек Z3 ↔ cvc5 | **9/9 согласие, 0 расхождений** |
| SWE-bench Lite (Docker, официальный) | **3/3 resolved** |
| Refactory (differential) | 1438/1782 (80.7%) |
| HumanEval / HumanEval+ (официальный EvalPlus) | 0.524 / 0.500 |
| MBPP+ | ⚠️ **заблокирован**: API отдаёт HTTP 429 (лимит исчерпан) |

**Найдено и исправлено в генераторе MBPP:** у MBPP промпт — только docstring
(без `def`), и старый экстрактор срезал сигнатуру → сэмпл становился невалидным
кодом, `pass@1` падал в **0.000**. Это был дефект ИНСТРУМЕНТА, а не модели.

---

## 2. Что ИЗМЕРЕНО (KERN-Next, `kernx`)

| Возможность | Уровень | Доказательство |
|:--|:--|:--|
| Парсер языка .kern | TESTED | 3 теста |
| Валидатор (§8, 10 правил) | TESTED | 2 теста |
| SQLite-каталог .kdb | MEASURED | `sqlite3 project.kdb "SELECT ..."` |
| Snapshot + diff | MEASURED | `kernx diff` → `+2/-2` |
| Agent packet (§17) | MEASURED | `agent_packet.json` |
| Human report (§14.1) | MEASURED | `report.md` |
| Инкрементальный кэш (пропуск неизменённых) | MEASURED | повторный build → «пропущено» |
| Стабильные ID | TESTED | повторный разбор → тот же id |

**Числа:** `zig build test-next` → **37/37 OK** (в `docs/TEST_CATALOG.md` — 24 именованных теста + 1 агрегирующий; каталог генерируется из исходников).

---

## 3. НАПИСАНО, НО НЕ ИЗМЕРЕНО (оболочки)

| Артефакт | Уровень | Почему не измерено |
|:--|:--|:--|
| `Dockerfile` | FRAMEWORK | в окружении нет `docker` |
| `Makefile` | SMOKE | цели написаны; требуют `zig`/`docker` в PATH |
| `src/sdk/kern_sdk.py` | MEASURED | обёртка над CLI: вызов реального `kernc` успешен |

---

## 4. НЕ РЕАЛИЗОВАНО (заявлено в спецификации, кода нет)

| Заявлено | Статус |
|:--|:--|
| HTTP/REST демон (`kern_daemon.zig`) | NOT IMPL |
| WASM/WASI песочница (`kern-core-wasm`, Rust) | NOT IMPL |
| Lean 4 транспилятор (KERN-D → Lean) | NOT IMPL (но сами инварианты доказаны и компилируются — см. §1b) |
| C-ABI плагины (`include/kern_plugin.h`, `plugin_loader.zig`) | NOT IMPL |
| Формат `.kern.bundle` (Markdown+Binary+ZIP) | NOT IMPL |
| PQC-подписи (Dilithium) / `attest` (break-glass) | NOT IMPL |
| Дифференциальный Datalog (Δ) в графе | NOT IMPL |
| SIMD-реализация Белнапа | NOT IMPL |
| `vacuum`/GC, `merge` веток .kbin | NOT IMPL |
| ECC-RAM scrubbing / Rowhammer-митигация | NOT IMPL (физика вне софта) |
| Token-ROI дашборд, Prometheus/Grafana | NOT IMPL |
| LLM-оркестратор (`SwarmOrchestrator`) | NOT IMPL (честный `NotImplementedError`) |

---

## 5. Что НЕ проверено ПО-НАСТОЯЩЕМУ (риски)

1. ~~**Z3-мост**~~ — **ЗАКРЫТО 2026-10-11**: установлен `z3-solver`, Врата
   реально дают `e=1` (ДОКАЗАНО) и `e=0` (контрпример). Осталось: на машинах
   БЕЗ z3 поведение прежнее (graceful e=0).
2. ~~**Таймаут решателя**~~ — **ЗАКРЫТО**: жёсткий таймаут с потоком-убийцей
   (`Z3Bridge`); крах решателя ловится (`z3_crash_test`), KERN жив.
3. **Docker**: `Dockerfile` — рабочая оболочка. **Docker daemon ДОСТУПЕН**
   (проверено: Engine 29.8.1; официальный SWE-bench Lite прогнан в контейнерах
   → **3/3 resolved**, 0 infra-failures). `docker-compose.yml`,
   `kern-cluster.yaml` и `vscode-kern/` УДАЛЕНЫ из репозитория как
   непроверенные оболочки.
4. **BLAKE3 vs SHA-256**: спецификация называет BLAKE3, реализация — SHA-256
   (зафиксирован ОДИН алгоритм, иначе рвётся сквозная сверка). Теперь
   `hash_algo` **валидируется** (1=BLAKE3, 2=SHA-256), но вычисления идут SHA-256.
5. **`libsqlite3`** — единственная системная зависимость KERN-Next.
6. **Скорость чтения**: «76 ГБ/с» — это RAW-адресация; безопасное чтение
   (со сверкой SHA-256) — **231 МБ/с** (330× медленнее). См. METRICS §4.
7. **Compression**: `compression_codec` зарезервирован, но сжатие не
   реализовано (ветка `!= 0` недостижима — это и объясняет один «выживший»
   мутант).
8. **Тест покрытия** читает глобальные счётчики: при `--test-filter` даёт
   ложные 0%. `make coverage` запускает полный сьют (корректно).

---

## 6. Журнал дефектов, найденных аудитом 2026-10-11

| # | Дефект | Класс |
|:--:|:--|:--|
| 1 | `KimgHeader.parse` не проверял `major` и `hash_algo` (требует спека) | корректность |
| 2 | Маска `checker_id`: `@truncate` заворачивал 32→0 (**баг есть и в спеке**) | безопасность |
| 3 | Поле 20..24 называлось `schema_version` вместо `hash_algo` | сверка со спекой |
| 4 | `Eq2.encode(p,n)` отсутствовал (публичный API спеки) | полнота API |
| 5 | 2 Lean-теоремы были **тавтологиями** (`∃ res, f = res`) | честность доказательств |
| 6 | «51 ГБ/с» выдавалось за скорость чтения (это RAW-адресация) | честность метрик |
| 7 | Мутатор правил исходники **на месте** (затирал правки, ломал параллель) | инструмент |
| 8 | Мутатор мутировал **внутри комментариев** → ложные «выжившие» | инструмент |
| 9 | C-ABI `kern_localize` был **невызываем** (одна строка = и объявления, и формула) | интерфейс |
| 10 | `kernx build` падал **сырым traceback** вместо понятной ошибки | UX |

---

## 7. Итог

**MEASURED/TESTED:** ядро KIMG (парсер, сборщик, Merkle, KERNFS, Врата,
KERN-X, кэш, 5 теорий SMT, C-ABI) и KERN-Next (парсер, валидатор, SQLite,
snapshot, diff, packet, report, кэш) — **191 + 37 тестов, все зелёные**.

**FRAMEWORK/NOT IMPL:** облако, WASM, Lean-транспилятор, плагины, bundle,
PQC, дашборд — это следующий слой; он НЕ заявлен как работающий.
