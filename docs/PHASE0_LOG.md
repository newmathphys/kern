# PHASE 0 — локальный runbook (чтобы не теряться)

> **Базовая точка:** `v2.5.0` = `54439ee` (тег опубликован, НЕ двигаем).
> **Правило:** все правки — в ветке `fix/phase0-honesty`, релиз — `v2.5.1`.
> **Статус:** шаг **A** выполнен (C1 + C2). Шаги **B** и **C** — впереди.

## 0. Зачем этот файл

История проекта — 301 коммит от `v2.4.0` до `v2.5.0`, 484 файла в индексе,
660-КБ `docs/METRICS.md`. Держать в голове «что уже исправлено, а что нет»
нельзя. Поэтому каждый шаг фиксируется здесь: **команда → результат → вывод**.

## 1. Исходные факты (проверены, не «по памяти»)

| Факт | Значение |
|:--|:--|
| `v2.5.0` | `54439ee` = HEAD (lightweight tag) |
| `v2.4.0` | `28e6bb9`, −301 коммит, 81/81 CHECK, QuixBugs 31/31 (тавтология) |
| Незакоммичено до старта | `docs/METRICS.md` +30, `docs/METRICS.en.md` +19 (§151) |
| Страж чисел до правки | **слеп** к `125/125`, `141`, `151`, `12 tasks` (0 совпадений) |
| `kernx` / `capi` до правки | `v2.4.0` при теге `v2.5.0` |
| `version_check.sh` | RC=1, **не подключён** к `tools/ci.sh` |
| Аттестат | `gitCommit = a64c3ca`, HEAD = `54439ee` (см. шаг C) |

## 2. Шаг A — C1 + C2 (ВЫПОЛНЕНО)

### C1. Страж чисел: слепые зоны + мета-тест

**Файлы:** `tools/check_metrics_consistency.py`, `Makefile`, `tools/ci.sh`, `tools/registry.py`.

Что добавлено:

* правила под табличные формы: `CHECK … | **N/N`, `can-fail кейсов | N`,
  `N (не-вакуумных N`, `Целей всего | N`, `(CHECK N`, `реестр N целей`;
* `fact_quixbugs_explored()` — берёт **итоговое** `EXPLORED 7` из
  `docs/evidence/quixbugs_full.log` (а не `EXPLORED 5 lines=…` из строки задачи);
* `fact_canfail_anchors()` — берёт **реальное** число якорей из
  `canfail.py --check-anchors` (119), а не из текста;
* `violations_in_line()` — единая логика для CI и мета-теста;
* `--selftest` — 5 подсадок / 5 чистых / 3 исторических;
* `--json` — машиночитаемые факты;
* цель `make metrics-guard-selftest` (классифицирована как `META`).

**Доказательство (red → green):**

```
до:  23 расхождения (16 реальных + ложные на 9/9, 33/40, check.py)
после сужения правил: 16 реальных, 0 ложных
после правки чисел: 0 расхождений
selftest: [OK] 5 подсадок, 5 чистых, 3 исторических; ошибок 0
```

Исправлены реальные числа:

| Где | Было | Стало |
|:--|--:|--:|
| `README.md` (якоря) | 108 | **119** |
| `README.ru.md` (якоря) | 74 | **119** |
| `README.ru.md` (реестр) | 103 / 151 (CHECK 126) | **154 (CHECK 128)** |
| `README.ru.md` (CHECK) | 125/125 | **128/128** |
| `README.ru.md` (кейсы) | 141 | **144** |
| `docs/index.html` | 12 tasks | **7 tasks** |
| `docs/ATTESTATION_PASSPORT.md` | реестр 125 | **154** |
| `docs/PROJECT_SPECIFICATION.md` | реестр 75 (×2) | **154** |
| `docs/ROADMAP.md` | реестр 151, якоря 117, Lean 82 | **154, 119, 137** |
| `docs/METRICS.md` | 12 задач `STAGE2-CLEAN` | **7** |

История **не тронута**: `#125`, `#141`, `1441`, строки `| **N** |` — без изменений
(проверяется `--selftest`).

### C2. Версии и подключение стража к CI

**Файлы:** `src/next/main.zig`, `src/capi.zig`, `tools/version_check.sh`, `tools/ci.sh`.

* `kernx` и `capi` → `v2.5.0` (было `v2.4.0`);
* `version_check.sh` проверяет **исходники** (`src/main.zig`, `src/next/main.zig`,
  `src/capi.zig`, `server.json`), а не только бинарники;
* стадия `версии согласованы (kernc/kernx/C-ABI/README)` — в `tools/ci.sh`
  сразу после `build`;
* стадия `мета-тест стража чисел (#239)` — в `ci.sh` после `metrics-guard`.

**Доказательство:**

```
kernc --version : v2.5.0
kernx --version : v2.5.0
src/main.zig    : v2.5.0
src/next/main   : v2.5.0
src/capi.zig    : v2.5.0
server.json     : v2.5.0
ВЕРСИИ СОГЛАСОВАНЫ во всех местах (v2.5.0)   RC=0
```

`python3 tools/registry.py` → 156 целей · CHECK 128/128 · кейсов 144 · META 18 · OK.

## 3. Шаг B — честная витрина + архив (ПЛАН)

* `6/40` SMT + `33/40` дифференциальный (24 value + 8 crash + 1 hang) + `7 EXPLORED`
  в `README.md`, `README.ru.md`, `docs/index.html`, `audits/QUIXBUGS_BASELINE.md`;
* `tools/quixbugs_check.py --stage1-only` — чтобы `6/40` было воспроизводимо;
* шапка `docs/METRICS.md`: `CURRENT STATE: v2.5.0 @ 54439ee`, история — `HISTORICAL`;
* `docs/ATTESTATION_PASSPORT.md` §0.4: убрать «SHA-256» и «main на Zig 0.13»;
* `docs/ROADMAP.md`: убрать «черновик v2.5-dev / main заморожен на 28e6bb9»;
* `docs/archive/` — плашка `HISTORICAL ARCHIVE` старым отчётам.

## 4. Шаг C — якоря, sync, аттестат (ПЛАН)

* `docs/facts.json` + `{{fact:...}}` в 6 поверхностях;
* `make sync --check` / `--write` (идемпотентно, история не трогается);
* `make seal` + `attests_commit = HEAD~1`;
* `.vscode/tasks.json` + `make status`;
* перегенерировать `registry.log` / `canfail.log` (154/128/144).

## 5. Harness² — решение

`google-research/harness2` (Apache-2.0, 14.8k★) — это **оптимизатор агентного
харнеса** (Propose–Probe–Compose, 8 компонентов: system prompt, guardrails,
memory, tool guidance, subagents, skills, scripts, plugins). У него **нет
grader'а** и нет бенчмарка QuixBugs; реальный прогон требует сети, Vertex/API
ключей и денег (`R=4k` rollouts + `P=3k` improver-сессий).

**Решение:** НЕ добавляем как зависимость и НЕ ставим в CI. Берём **идею**:

1. Propose → Probe → Compose = «предложил правку → прогнал `make ci-fast` →
   зафиксировал только зелёное»;
2. lessons = этот файл + `CAPABILITY_STATUS.md` (дефект → причина → эффект);
3. хеширование 8 компонентов → поля 13-польного `ProofCache` — только в Фазе 3,
   когда появится сам `CacheKey` (иначе адаптер будет заглушкой).

Локальная профилактика «чтобы не повторялось»: `pre-commit` → `make ci-fast`
(или `make metrics-guard metrics-guard-selftest version-check`), `make sync --check`
перед коммитом, `make status` для разделения generated/ручное.

## 6. Следующее действие

- [x] C1: страж + мета-тест
- [x] C2: версии + CI
- [ ] `make ci-fast` (полный прогон)
- [ ] коммит A в ветку `fix/phase0-honesty`
- [ ] шаг B
- [ ] шаг C

## 7. Прогресс шага B (в работе)

- [x] `make ci-fast` — 10/10 зелёных, 16 с (шаг A).
- [x] Коммит A: `4e6f5ab` в ветке `fix/phase0-honesty`.
- [x] `docs/evidence/core_tests.log` перегенерирован: **All 402 tests passed**
      (было 401 — лог от 2026-10-19 отставал от кода).
- [x] Текущие упоминания 401 → 402 в README/README.ru/index/PROJECT/
      PROJECT_SPECIFICATION/TEST_CATALOG/CYBERNETIC_VISION/CONTRIBUTING/
      ATTESTATION_PASSPORT/CAPABILITIES/CAPABILITY_STATUS.
      **Исторические** разделы METRICS, журнал дефектов #220/#224 и
      RELEASE_NOTES_v2.5.0 (там «было 299 → стало 401») НЕ тронуты.
- [ ] `docs/evidence/cross_arch.log` — идёт QEMU ARM64 (нужно 394+8=402).
- [x] `tools/quixbugs_check.py --stage1-only` — флаг добавлен, чтобы `6/40`
      было воспроизводимо (раньше fallback Ступени 2 включался всегда).
- [ ] `docs/evidence/quixbugs_stage1.log` — прогон после cross_arch (общий
      evidence_guard-снимок нельзя запускать параллельно).
- [ ] Честная формулировка `6/40 + 33/40` в README/README.ru/index/BASELINE.
- [ ] Чистка docs: METRICS header, SHA-256, ATTESTATION §0.4, ROADMAP status.

## 8. Шаг B — ВЫПОЛНЕНО

- [x] `docs/evidence/core_tests.log` → **All 402 tests passed**.
- [x] Текущие 401 → 402 в публичных поверхностях.
- [x] `docs/evidence/cross_arch.log` → **394 passed + 8 skipped = 402**
      на ARM64 и POWERPC64 (big-endian), `RC=0`.
- [x] `docs/evidence/quixbugs_stage1.log` → **6/40** (`--stage1-only`, `RC=0`).
- [x] Честная формулировка `6/40 SMT + 33/40 differential` в `README.md`,
      `README.ru.md`, `docs/index.html`, `audits/QUIXBUGS_BASELINE.md`,
      `docs/CAPABILITIES.md`.
- [x] `docs/METRICS.md`/`.en`: блок `CURRENT STATE`, `v1.3` помечен как история,
      `hash_algo` → BLAKE3 (дефект #66).
- [x] `docs/ATTESTATION_PASSPORT.md` §0.4: Zig 0.17 / v2.5.0 (не «0.13, черновик PR»).
- [x] `docs/ROADMAP.md`: v2.5.0 опубликован, 40/40 пунктов, 137 теорем.
- [x] Плашки `HISTORICAL` на `KERN_FIXES_v1_3`, `VERIFICATION_0_17`,
      `MIGRATION_REPORT_0_17`, `KERN_TERMINOLOGY_v0.1`, `docs/archive/*`.
- [x] `.gitattributes`: `docs/evidence/*.log -whitespace` (логи — дословный вывод).

### Урок (важный)

Первый прогон `cross_arch` был **аннулирован**: во время него я правил
`README.md`/`PROJECT.md`, и `evidence_guard` честно написал
«Прогон НЕДЕЙСТВИТЕЛЕН». Правило: **во время снятия свидетельств файлы
не трогать**. Перезапущено на замороженном дереве — 394+8, `RC=0`.
