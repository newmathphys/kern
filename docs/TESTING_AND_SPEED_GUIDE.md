# KERN — Testing & Speed Guide (v2.5)

> **Факты (EN/RU, синхронизируются `make sync`):** core <!-- fact:core_tests -->402 · next <!-- fact:next_tests -->53 · catalog <!-- fact:catalog -->465 · CHECK <!-- fact:check_targets -->152 · cases <!-- fact:canfail_cases -->174 · anchors <!-- fact:anchors -->137 · registry <!-- fact:registry_targets -->191 · META <!-- fact:meta_targets -->25 · Lean <!-- fact:lean_theorems -->143 · QuixBugs <!-- fact:quixbugs.smt -->6/40 SMT + <!-- fact:quixbugs.differential -->40/40 diff.

> Канонический документ: **что** мы тестируем, **как** измеряем и **чем** ускоряем.
> Каждое число получено прогоном; где выигрыш не измерен — так и написано.

## 1. Матрица методов верификации (8 разделов)

### Раздел 1 — Статический анализ (до запуска)
| Метод | Инструмент | Факт |
|:--|:--|:--|
| AST-разбор и типы | `tools/kern_contracts.py` | 7 языков: `.py .zig .c .rs .ts .js .go` |
| Цикломатическая сложность Маккейба | `--xray` | `CC = branches + 1`, порог Code Smell > 15 |
| Code Smells | `--xray` | Deep Nesting > 3, Long Parameter List > 5 |
| Мёртвые ветки | `[DEAD BRANCH]` (Z3 `UNSAT`) | `xray_demo.py`: 3/3 находки |
| Избыточные проверки | `[REDUNDANT GUARD]` | условие всегда истинно |
| Границы массивов | `[BOUNDS PATH]` | длина из **литерала** или `len(arr)` — **без аннотаций** |
| SAST / anti-cheat | `--anti-cheat`, `--import-lock` | 5 классов читов + slopsquatting |
| MCP-безопасность | `--audit-mcp`, `--mcp-lock` | инъекции, zero-width Unicode, rug-pull |
| Защита парсера | `make parser-security-check` | Comment-in-String, Type-Alias Spoofing |

### Раздел 2 — Классическое тестирование
| Метод | Факт |
|:--|:--|
| Unit / boundary | **400** тестов ядра (393 passed + 8 skipped) + **53** next |
| Property-Based Testing | `truth.zig`: 500 случайных входов × 2 закона (решётка Белнапа, Хэмминг) |
| Min-Shrinking | каскад окон `10 → 5 → 2 → 1 → 0` (только добавление ограничений — звучимо) |
| Метаморфное | `builtin_lia`: 20 систем × 3 трансформации = **60/60** |
| Границы/крайние случаи | `make edge-cases` — 10 проверок |

### Раздел 3 — Формальная верификация
| Метод | Факт |
|:--|:--|
| Lean 4 | **8 файлов, 143 теорем, 0 errors, 0 sorry** |
| Proof-DAG checker | `trusted: 0 \| holes: 0` на QF_LIA, QF_S, IEEE-754, циклах, массивах, автоматах, RLS |
| Белнап B₄ | `JOIN_K(T,F)=B`, поглощение противоречием, Evidence Decay, Scoped Epoch |
| Флойд–Хоар | `--loops`: Init + Consecution + Post + Termination |

### Раздел 4 — Самоверификация и эволюция
| Метод | Факт |
|:--|:--|
| Can-fail дисциплина | **152 CHECK-целей / 126 с доказательством**, **174 кейса, 0 вакуумных** |
| Мутации | **1345/1345 = 100.0 %** по ВСЕЙ популяции (21 файл, без сэмплинга, 23 мин) |
| SBST | `--gen-tests`: 100 % достижимых веток (мёртвые помечены) |
| Genetic Improvement | `--simplify` + доказательство эквивалентности через `--diff-equiv` |
| Авторемонт | `--heal`: F → синтез гарда → **T**, `.bak` + атомарная замена |

### Раздел 5 — Динамика и исследование
| Метод | Факт |
|:--|:--|
| Символьное исполнение | `kernc prove` + SMT-LIB2 |
| Конколическое | `--concolic`: 9 живых запусков, **6/6 ветвей**, dead 0 |
| Дифференциальное | `lia-diff`: 100 систем vs Z3, **0 расхождений**; `opt-diff`: Debug == ReleaseSafe == ReleaseSmall |
| Эволюционный фаззер | `evo_fuzzer.py`: 100 особей, **0 паник, 0 ложных допусков** (нашёл #155) |
| Адверсариальный фаззинг | `proof-tamper`: **40/40** подделок отвергнуто |
| Корпус фаззинга | `fuzz-corpus`: 8 файлов, 0 паник, детерминизм |

### Раздел 6 — Покрытие и трассируемость (DO-178C / ISO 26262)
| Метод | Факт |
|:--|:--|
| MC/DC | **30/30 = 100.0 %** |
| Трассируемость | `formal/certification/TOR.md` + `TRACEABILITY_MATRIX.csv` |

### Раздел 7 — Низкоуровневая и аппаратная проверка
| Метод | Факт |
|:--|:--|
| Sanitizers / OOM | ReleaseSafe, `checkAllAllocationFailures`, **0 утечек** |
| Бинарный аудит | **29 694** регистра `%ymm` (AVX2), `GNU_STACK RW` без `E` |
| Пропускная способность | `bench-simd8`: **2.42 GB/s** (BLAKE3, 64 МБ) |
| Сторонние каналы | `timing_safe.eql` ×6; Welch **\|t\| = 0.11** |
| 2-Safety | `@kern:secret`: `PROVEN NON-INTERFERENT, trusted: 0` |
| DST (TigerBeetle-style) | `kern-dst`: 10 seeds × 50 шагов = **500**, 567 перехватов, 100 % детерминизм |
| Кросс-архитектура | QEMU **ARM64** + **PowerPC64 BE**: **393 passed / 8 skipped / 0 failed** |

### Раздел 8 — Следующий горизонт
| Метод | Факт |
|:--|:--|
| Translation Validation (CompCert-style) | `-O2` `objdump -d -M intel` → эквивалентность: **PROVEN, trusted: 0**; искажение → REFUTED |
| RLVR Oracle | `R ∈ {-2, -1, 0, +1}`; читерский/опровергнутый **никогда** не получает `R > 0` |
| Action / FinOps Firewall | HTTP **200 / 422 / 409** по решётке B₄ |
| RAG Conflict Engine | `CONFLICT B(1,1)` + минимальное ядро конфликта |
| Матрицы Адамара | N=2,4 → SAT + `H·Hᵀ = N·I`; N=3 → **UNSAT** |
| WebAssembly | `kernc.wasm` **85 526 байт**, 5 экспортов, включая `verify_proof` |

---

## 2. Ускорения под 32 ГБ DDR4 + i7-7700 (8 потоков)

| Ускорение | Как | Замер |
|:--|:--|:--|
| **Кэш `opt-diff`** | 3 профиля привязаны к `sha256(src/)` в `/dev/shm/kern_opt_diff_cache` | **90 000 мс → 47 мс** (×1900) |
| **Слоты мутатора в `/dev/shm`** | копии дерева + тёплый `.zig-cache` в ОЗУ, переиспользуется между мутантами | 0 обращений к SSD |
| **Двухступенчатый Fail-Fast** | Ступень 1: `zig test --test-filter <модуль>` → Ступень 2 (полный сьют) только если выжил | Stage1 **2 с** vs Full **10 с** = ×5 на убитых |
| **Параллельные воркеры** | `--jobs 6` (у каждого свой слот и кэш) | ×2.15 (59.6 с → 27.7 с) |
| **`KERN_MUTATE_FAST=1`** | уменьшение числа итераций стресс-циклов (без отключения тестов) | 11 390 → 5 811 мс (×1.96) |
| **SIMD-8 BLAKE3** | `@Vector(8, u32)`, `align(32)` | 2.42 GB/s |
| **`/dev/shm` для `.smt2`** | `lia_diff.py`, `kern_contracts.py` | убраны fsync-задержки |

**Честно про `align(32)`:** замер дал **2.42 против 2.41 GB/s** — выигрыша нет
(правка безвредна, но «ускорением» не называется).

---

## 3. Хронология дефектов, пойманых тестами (#123–#157)

| # | Что было сломано | Чем поймано |
|:--|:--|:--|
| **#123** | `unit-resolution` над невесовой `th-lemma` не проверялся | `--full-file` + дамп `get-proof` |
| **#124** | сквозной ГПСЧ в `sample_stratified` → «движущаяся мишень» | повторные прогоны |
| **#125** | пустой `ProofVerdict{}` проходил `checksPass()` | `--full-file` |
| **#126** | гонка экземпляров, патчащих дерево | `tree_lock.py` |
| **#127** | `check-integrity` не пересчитывал дайджест по данным | **`bitrot-chaos`** (11/20 проходили) |
| **#128** | имена объектов не входили в Merkle-корень | `bitrot-chaos` (30/30 после фикса) |
| **#129** | `kernc verify` давал `rc=0` при опровергнутом контракте | `pcc-check` |
| **#130** | вакуумный кейс `pcc-check` | `canfail --only` |
| **#131** | `src/next/*` не компилировались мутатором (51 сайт — фикция) | приёмка: `grep 'next' test_root.zig` |
| **#132** | вакуумный `gen-tests-check` | `canfail --only` |
| **#133** | `_smt_verdict` отсутствовал у пресетов | `--full-file` |
| **#134** | `--xray` ложно обвинял функции с guard-clauses | `make bounds-check` |
| **#135** | `@kern:len` читался из чужой функции | `make bounds-check` |
| **#136** | CHECK-цель без собственной цели в Makefile | `registry.py` |
| **#137–#139** | ошибка разбора SMT выдавалась за **доказано** | `make loop-check` (3 исхода) |
| **#140** | устаревший якорь canfail после рефакторинга | `--check-anchors` |
| **#141** | `--xray` требовал аннотацию в Zero-Annotation режиме | ревизия |
| **#142** | вакуумный `state-inv-check` | `canfail --only` |
| **#143** | чекер **отвергал корректный** вывод Z3 (вес `-1`) | дамп `[dbg-farkas-bad]` |
| **#144** | вакуумный `ffi-bridge-check` | `canfail --only` |
| **#145** | RLS: инвариант одной формулой → 4 доверенных шага | дамп + покомпонентная проверка |
| **#146** | валидатор модели звал `SPURIOUS` то, что не умел вычислить | `@kern:secret` |
| **#147** | вакуумные `action-firewall` / `rag-conflict` | `canfail --only` |
| **#148** | вакуумный `fuzz-corpus-check` | `canfail --only` |
| **#149** | `--xray`: `if …: return` не сужал путь | тест MCP |
| **#150** | `wasm-check` не откатывал патч | `canfail --only` |
| **#151** | вакуумный `kimg-grep-check` (гейт не пересобирал бинарник) | `canfail --only` |
| **#152** | тест ожидал `spurious` вместо `unsupported` | `zig build test` |
| **#153** | 256 КБ буфера не хватало для 51-шагового доказательства | нативный тест WASM |
| **#154** | `mcp_selftest` падал без `z3` в PATH (класс #110) | `env -i` прогон |
| **#155** | нерезолвленная `@xN` → испорченное доказательство **принималось** | **`evo-fuzzer`** |
| **#156** | SIGTERM не откатывал патчи мутатора → диверсия в дереве | прерванный прогон |
| **#157** | `write_atomic` терял `+x` (29 скриптов) | **полный прогон `canfail`** |

**Закономерность:** 35 из 40 дефектов найдены **проверкой самих проверяющих инструментов**
(`canfail --only`, мутации, дампы, полный прогон), а не проверяемого кода.

---

## 4. Полный популяционный обстрел мутации

```bash
python3 tools/mutate_zig.py --max 5000 --jobs 6 --require-solver   # все 1361 сайтов
```
Результат фиксируется в `docs/METRICS.md §109` (точное число убитых + выжившие по классам).

---

## 5. Воспроизведение

```bash
make zig test test-next formal-ci proof-tamper evo-fuzz-check lia-diff \
     opt-diff-check bitrot-chaos pcc-check dst-check xray-check gen-tests-check \
     concolic-check homeostatic-heal-check bounds-check loop-check float-nan-check \
     string-contracts-check state-inv-check polyglot-7-check presets-check \
     arbitrage-check double-spend-check ffi-bridge-check sql-policy-check \
     pricing-matrix-check anti-cheat-check mcp-audit-check noninterference-check \
     belnap-swarm-check parser-security-check action-firewall-check rag-conflict-check \
     rlvr-oracle-check bug-hunt-check translation-val-check hadamard-check \
     wasm-check html-canvas-check kimg-grep-check mcp-selftest fuzz-corpus-check \
     binary-audit tree-lock mutate canfail-anchors registry evidence-gate svg-check
```

Полный сквозной прогон `canfail`: **174 не-вакуумных / 0 вакуумных / 0 ошибок**.
