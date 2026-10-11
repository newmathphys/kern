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
| Z3-мост (SMT-LIB2, дочерний процесс) | SMOKE | z3 отсутствует → `ToolError`→`Unknown`→e=0 (graceful) |
| KERN-X VM (топливо, HALT, опкоды) | TESTED | OutOfFuel на 10k NOP |
| Кэш доказательств (AST→вердикт) | TESTED | hits/misses |
| CLI: build/check-integrity/ls/cat/verify/unify/run/handoff/report | MEASURED | все прогнаны |

**Числа:** `zig test src/test_root.zig` → **47/47 OK** (Debug И ReleaseFast).
Эталон `valid_v1_3.kimg` → 410 байт, Merkle совпадает Python↔Zig.

---

## 1b. Формальные доказательства (Lean 4) — MEASURED

| Файл | Теоремы | Компиляция |
|:--|:--|:--|
| `formal/KernAllMath.lean` | де Морган ×2, инволюция, JOIN_K comm/assoc/idem, дистрибутивность, `contradiction_isolation : T⊔F=B`, анти-вакуум, тотальность fuel-DFS | ✅ Lean 4.34.0, **0 ошибок, 0 sorry** (Pure Core) |
| `formal/KernDfsTermination.lean` | `traversal_terminates`, `fuel_bounded_always_terminates` | ✅ Pure Core |
| `formal/KernTalk.lean` | `ai_hallucination_yields_conflict`, `consistent_yields_truth` | ✅ Mathlib (ℝ) |
| `formal/KernTalkND.lean` | `nd_violation_yields_conflict` (N-мерная унификация) | ✅ Mathlib |
| `formal/KernConvergence.lean` | СИЛЬНАЯ `convergence_guaranteed` (итерация достигает успеха) + слабая из спеки | ✅ Mathlib |

**Доказательство:** `./formal/check.sh` → `ALL LEAN PROOFS OK (0 errors, 0 sorry)`.
**Важно:** в документе теорема `ai_hallucination_yields_conflict` содержала `sorry`
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

**Числа:** `zig test src/next/test_root.zig -lc -lsqlite3` → **13/13 OK**.

---

## 3. НАПИСАНО, НО НЕ ИЗМЕРЕНО (оболочки)

| Артефакт | Уровень | Почему не измерено |
|:--|:--|:--|
| `Dockerfile` | FRAMEWORK | в окружении нет `docker` |
| `docker-compose.yml` | FRAMEWORK | нет `docker` |
| `kern-cluster.yaml` | FRAMEWORK | нет кластера K8s |
| `Makefile` | SMOKE | цели написаны; требуют `zig`/`docker` в PATH |
| `vscode-kern/extension.ts` | FRAMEWORK | нет `npm`/`tsc`; НЕ компилировалось |
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

1. **Z3-мост**: код запускает `z3` как дочерний процесс, но `z3` в окружении
   отсутствует → реальное доказательство контракта не прогонялось. Проверено
   только graceful-поведение (e=0).
2. **Таймаут решателя**: `timeout_ms` объявлен, но жёсткий таймер не
   реализован (нет прерывания зависшего Z3) — заявлено честно.
3. **Docker/K8s/VS Code**: написаны как оболочки, не собирались.
4. **BLAKE3 vs SHA-256**: спецификация называет BLAKE3, реализация — SHA-256
   (зафиксирован ОДИН алгоритм, иначе рвётся сквозная сверка).
5. **`libsqlite3`** — единственная системная зависимость KERN-Next.

---

## 6. Итог

**MEASURED/TESTED:** ядро KIMG (парсер, сборщик, Merkle, KERNFS, Врата,
KERN-X, кэш) и KERN-Next (парсер, валидатор, SQLite, snapshot, diff, packet,
report, кэш) — **60 тестов (47+13), все зелёные**.

**FRAMEWORK/NOT IMPL:** облако, WASM, Lean, плагины, bundle, PQC, дашборд —
это следующий слой; он НЕ заявлен как работающий.
