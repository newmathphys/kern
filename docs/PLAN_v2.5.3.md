# План работ: `v2.5.3` → `v2.6.0`

> **СТАТУС: ВЫПОЛНЕН.** Все шаги `0K`, `0J`, `Ф1`, `Ф2`, `Ф3`, `Ф4`, `Ф4B`,
> `Ф5`, `Ф6.1`, `Ф6.3` закрыты и проверены гейтами; `Ф6.2` перенесена в §15
> Backlog (причина ниже, §10). Релиз `v2.6.0`.

> **Базовая точка плана: `main = e27ec54` (v2.5.2), дерево чистое.**

**English summary.** This document is the agreed work plan for KERN after `v2.5.2`:
trust and reproducibility hardening (0K), a machine-checked bibliography (0J), seven
separate state axes with a request-kind binding (Ф1), an evidence ledger with
`add`/`retract` and three provenance graphs (Ф2), KIMG/KERNFS/cache/KERN-X policy (Ф3),
the remaining QuixBugs tasks (Ф4), a code-checking corpus with a zero-false-positive gate
(Ф4B), a 12-requirement conformance harness (Ф5), and three deferred features
(Ф6.1 advisory contracts, Ф6.2 bounded intuitionistic mode, Ф6.3 read-only hypotheses).
Nothing here is implemented yet.

---

## §0 Снимок состояния на момент записи

| Параметр | Значение |
|:--|:--|
| Коммит / тег | `e27ec54` / `v2.5.2` |
| Реестр целей | **162** (CHECK 128 · MEASURE 1 · BUILD 8 · EXTERNAL 3 · META 22) |
| can-fail кейсов | **144** (не-вакуумных 144, вакуумных 0, ошибок 0) |
| Ядро / next | 402 / 53 теста |
| Lean | 143 теорем / 8 файлов, `sorry = 0` |
| Кросс-арх | 394 passed / 8 skipped / 0 failed (aarch64, ppc64 big-endian) |
| QuixBugs | SMT 6/40 · дифференциальный 33/40 · EXPLORED 7 |
| Закрыто в Фазе 0 | дефекты **#239–#250** |

Фаза 0 (A–H) закрыта: честная формулировка QuixBugs, `make sync` + якоря фактов,
`make seal` + `attests_commit`, EN/RU parity, `ai-traces-check`, витрина, релизный конвейер.

---

## §1 Принципы (действуют на каждом шаге)

1. **Новая CHECK-цель — только со своим canfail-кейсом.** Иначе счётчик растёт без доказательства.
2. **Ложное `F` хуже пропуска.** В корпусе проверки кода `FP = 0` — врата, а не метрика.
3. **`verified` в библиографии — только со снимком Crossref** (DOI + страницы + том + авторы).
4. **Второй агент — read-only ревьюер** в отдельном `worktree`; каждый вывод проверяется кодом.
5. **Теги `v2.5.0–v2.5.2` неизменяемы**; force-push запрещён; каждый релиз — новый тег.
6. **Секреты не попадают в репозиторий и в чат.** Ключи из переписки считаются скомпрометированными.
7. После каждого шага: `ci-fast` · `sync` · `metrics-guard` · `docs-parity` · `showcase-check` · `evidence-gate` · `version-check` · `make seal`.

---

## §2 Шаг 0K — Доверие и воспроизводимость (P0, ~2 сессии)

Приоритет P0: без этого аттестат нельзя проверить извне, а вердикты невоспроизводимы.

| # | Проблема (доказательство в коде) | Исправление | Acceptance |
|:--|:--|:--|:--|
| 0K.1 | **Публичный ключ не опубликован.** `tools/slsa_provenance.py:65` берёт `~/kern_owner_public.pem`; в репозитории ключа нет, инструкции по проверке нет | `docs/keys/kern-owner.pub`; поле `kid` (SHA-256 отпечаток) в аттестате; отпечаток в `README.md` и на сайте | Ключ в репо; `kid` в `kern.intoto.jsonl` совпадает с отпечатком файла |
| 0K.2 | **Проверка возможна только на машине владельца** | `tools/verify_attestation.py`: только публичный ключ из репозитория, проверка подписи, `subject.sha256`, `attests_commit`; ничего не пишет | `make verify-attestation` проходит без `$HOME`-ключей |
| 0K.3 | **Отсутствие подписи считается нормой.** `slsa_provenance.py:268`: `.sig` нет → «это НЕ ошибка» → печатается «АТТЕСТАТ ВАЛИДЕН» | в релизном гейте `None` → **FAIL**; в dev — WARN | Удалили `.sig` → `make release-check` краснеет |
| 0K.4 | **Секреты не сканируются** (`gitleaks`/`secrets-check` → 0 совпадений) | `tools/secrets_check.py`: `nvapi-…`, `sk-or-v1-…`, `AKIA…`, `ghp_…`, `BEGIN … PRIVATE KEY`; tracked-файлы; фикстуры исключены; selftest | Подсаженный фейковый ключ → красный; реальных находок 0 |
| 0K.5 | **Z3 не запинен.** `requirements.txt`: `z3-solver>=5.1.0.0`; CI ставит `pip install z3-solver` (не из requirements); `solver_version` в коде отсутствует | `z3-solver==5.1.0.0`; CI `pip install -r requirements.txt`; `solver_version` + `seed` + `timeout_ms` в JSON вердикта и в шапку свидетельств | `kernc prove --json` содержит блок `solver`; два прогона дают одинаковый `solver_version` |
| 0K.6 | **Детерминизм вердикта не проверяется** (wall-clock таймаут) | тест: один вход, два прогона → одинаковый вердикт и контрпример | `make determinism-check` в `ci-fast` |

| 0K.7 | **Lean/mathlib не запинены** (`lean-toolchain` отсутствует) | `lean-toolchain` + `lake-manifest.json` с фиксированными ревизиями | `check_lean_counter.py`: 143 теорем / 8 файлов на двух чистых сборках |
| 0K.8 | **CHANGELOG отстал** (записи `2.5.2` нет) | `tools/changelog_check.py`: версия из `src/main.zig` обязана иметь раздел `## [x.y.z]` | Подсадили версию без раздела → красный |
| 0K.9 | **Нет документов доверия** | `docs/THREAT_MODEL.md` (активы, противники, границы), `docs/KEY_MANAGEMENT.md` (генерация, бэкап, ротация, отзыв, `kid`), `docs/INCIDENT_RESPONSE.md` (найден ложный `T` → advisory + список отзыва в репо) | Документы существуют; страж проверяет обязательные разделы |
| 0K.10 | **C-ABI зависит от LP64** (`unsigned long` в `include/kern.h`) | `unsigned long` → `size_t`; `long` → `int64_t` для счётчика объектов | `make c-abi-test`, `make c-abi-threads` зелёные; в заголовке нет `unsigned long` |
| 0K.11 | **CI только Ubuntu** (все workflow — `ubuntu-*`) | cross-compile job: `x86_64-windows-gnu`, `aarch64-macos` (сборка, без запуска тестов) | Job зелёный; артефакты не публикуются |
| 0K.12 | **Нет порога производительности** (13-польный ключ и новые проверки могут замедлить кэш) | `docs/evidence/bench_baseline.json` + `make bench-check` (медиана 5 прогонов, порог 1.5×) | Искусственное замедление горячего пути → красный |

**Kill criteria 0K:** если `openssl pkeyutl -verify` не работает без приватного ключа на чистой
машине — публикуем `cosign`-совместимый вариант либо признаём, что аттестат не проверяем,
и снимаем заявление «attestation ✓» с витрины.

---

## §3 Шаг 0J — Литература как данные (~0.5 сессии)

| Пункт | Что делаем |
|:--|:--|
| 0J.1 | `docs/references.bib` — 20 записей с ключами; обязательные поля: `doi`/`isbn`/`eprint`, `status = {verified\|secondary\|unverified}`, для статей-оснований — `read = {true\|false}` |
| 0J.2 | `docs/references.lock.json` — снимок Crossref для каждого `verified`: `doi, title, container, volume, issue, pages, issued, authors[]` |
| 0J.3 | `docs/BELNAP_SOURCES.md` + `.en.md`: §1 первоисточники · §2 бирешётки · §3 обобщённые значения · §4 русская школа · §5 **сверка «теория → код»** (таблица `файл:строка`) · §6 чего в KERN нет · §7 расхождения черновика · §8 как воспроизвести поиск |
| 0J.4 | `tools/citations_check.py`: ключи `§REF:` существуют; ссылки `src/…:NNN` и `formal/…lean:<theorem>` реальны; запись без DOI/ISBN/arXiv — ошибка; `unverified` запрещён в §1–§6; EN/RU одинаковый набор ключей; `bib == lock` |
| 0J.5 | Selftest на **5 диверсий**: неизвестный ключ · строка за EOF · запись без идентификатора · сдвиг страниц на 1 · DOI с изменённой последней цифрой |
| 0J.6 | `make citations-check` + CHECK-цель в реестре + canfail-кейс `citations` |

**Kill criteria 0J:** если 5 диверсий не дают 5 красных — подход не внедряем, оставляем только
`references.bib` и ручную сверку.

---

## §4 Фаза 1 — Семь осей состояния и `QueryKind` (~1 сессия)

| Пункт | Что делаем | Acceptance |
|:--|:--|:--|
| Ф1.1 | `src/next/state_axes.zig`: `BelnapValue {N,T,F,B}`, `CoverageState {none,bounded,full}`, `VerificationVerdict {proved,refuted,unknown,timeout,out_of_fuel,invalid_certificate,tool_error}`, `Lifecycle`, `IntegrityState`, `TrustState`, `ExecutionOutcome` + таблица отображения в Белнапа | `timeout ≠ F`, `out_of_fuel ≠ B`, `invalid_certificate ≠ F`, `tool_error ≠ F`; `B` только при `(p ∧ n)` |
| Ф1.2 | `conflate()` в `src/core/eq2.zig` (`~(t,f) = (1−f, 1−t)`) + Lean-леммы: `~N=B`, `~B=N`, `~T=T`, `~F=F`, инволюция | Полный набор связок B4: `⟨∧,∨,⊗,⊕,¬,~⟩`; `zig build test-next` и Lean зелёные |
| Ф1.3 | `QueryKind {refutation, satisfiability, equivalence}` в `ProofCertificate` (поле с дефолтом, чтобы старые конструкторы компилировались) + отказ при несовпадении | Сертификат от функции A к функции B → `InvalidCertificate`; `.proof` для `refutation` подан как `equivalence` → отказ |
| Ф1.4 | Замок контрактов на весь репозиторий: glob `examples/**/*.py`, `src/**/*.zig`, `tools/**/*.py` с `@kern:` | Сейчас запечатан 1 файл; `make contracts-lock` печатает число; canfail «ослабили `ensures`» становится невакуумным |
| Ф1.5 | Новые CHECK-цели: `axes-laws`, `cert-query-kind`, `contracts-lock-repo` — каждая со своим canfail | Реестр растёт только вместе с кейсами |

**Риск:** новое поле в `ProofCertificate` затрагивает `z3_bridge`, `proof_cache`, фикстуры.
**Kill criteria:** ломается больше 3 фикстур → поле вводится с дефолтом `refutation` и отдельным тестом, фикстуры не переписываются.

---

## §5 Фаза 2 — Динамика знаний и три графа (~1.5 сессии)

| Пункт | Что делаем | Acceptance |
|:--|:--|:--|
| Ф2.1 | `src/next/evidence_ledger.zig`: `contributions: evidence_id → Bit`; `add` идемпотентен; `retract` удаляет вклад и **полностью пересчитывает** `(p,n)` из активного набора; `epoch: u64`; публикация снапшота только после пересчёта | `T+F→B`; `retract(F)→T`; повторный `add` не меняет; `retract` неизвестного id — no-op + диагностика; порядок вкладов не влияет на результат |
| Ф2.2 | `src/next/provenance.zig`: `G_src` (импорты, циклы разрешены), `G_build` (артефакты/шаги), `G_prov` (append-only); Tarjan SCC (итеративный, ограниченный стек); отказ `NegativeRecursiveCycle` | `f→g→f` с отрицанием на ребре → отказ; положительный цикл → допустим |
| Ф2.3 | `kernx graph --json` со схемой `showcase-graph.json`; `tools/gen_showcase_graph.py` читает вывод ядра | CHECK `graph-parity`: число узлов/рёбер Zig == Python |
| Ф2.4 | Связать `truth.zig` с ledger: `resolve()` берёт `(p,n)` из активного набора | Тест «отозвали свидетельство → статус изменился» |
| Ф2.5 | Новые CHECK: `ledger-retract`, `scc-negative`, `graph-parity` + canfail каждого | — |

**Замечание о честности:** отзыв свидетельства — **расширение** сверх Белнапа–Фиттинга:
у монотонного `⊔` нет обратной операции. Так и формулируется в документации.

**Kill criteria:** если результат зависит от порядка вкладов — фиксируется канонический
порядок (сортировка по `evidence_id`) с тестом, а не «подкрутка» ожиданий.

---

## §6 Фаза 3 — Контейнер, ФС, кэш, песочница (~2 сессии)

| Пункт | Что делаем | Acceptance |
|:--|:--|:--|
| Ф3.1 | KIMG: `flags` → `OPTIONAL_MASK` (неизвестный бит — пропустить) и `REQUIRED_MASK` (неизвестный — `UnsupportedRequiredFeature`); `WrongEndianness` (magic совпал, `version_major` прочитан как `0x0100`); CLI `fsck`, `inspect`, `diff` | 3 golden-фикстуры: unknown-optional, unknown-required, big-endian; формат `.kimg` **не меняется** |
| Ф3.2 | KERNFS: явный `mountFromBytesOwned` (копия, режим `no-mmap`) + тест «мутация исходного буфера после mount не меняет ответы»; документировать, что симлинков в формате нет (N/A) | Тест мутации буфера; `AccessDenied` на запись сохраняется |
| Ф3.3 | `ProofCache.CacheKey` из 13 полей: `task_kind, semantic_slice, body_hashes, contract, dependency_hashes, model_fingerprint, prompt_hash, params_hash, tools_hash, retrieval_hash, schema_hash, policy_hash, checker_version` + префикс `v2` | Изменили любое одно поле → промах; старые тесты не переписываются |
| Ф3.4 | KERN-X: `CALL`/`RET`; `Budget { fuel: *u32, arena, output, depth, host_calls }`; квоты → `OutOfQuota` | Рекурсивный байткод с двумя ветками исчерпывает **один** общий `fuel`, а не копию на ветку |
| Ф3.5 | `solver_version` входит в `checker_version` ключа (связь с 0K.5) | Два разных Z3 → разные ключи |
| Ф3.6 | Новые CHECK: `kimg-unknown-required`, `kimg-endianness`, `kernfs-no-mmap`, `cache-13`, `kernx-shared-fuel` + canfail | — |

**Kill criteria:** если 13-польный ключ рушит кэш-тесты — вводится префикс `v2` (уже в плане),
тесты не «подкручиваются».

---

## §7 Фаза 4 — QuixBugs: 7 задач `EXPLORED` (~1.5 сессии)

| Пункт | Что делаем |
|:--|:--|
| Ф4.1 | `trace_explorer.py --explain-task <name>`: печатает построенный домен, отфильтрованные `Precondition:`, результат каждого вызова (`ok/exception/timeout`), причину `_MISSING` |
| Ф4.2 | Домены под конкретный баг: `depth_first_search` (цикл + недостижимая цель) · `detect_cycle` (список из 2 узлов) · `longest_common_subsequence` (равные строки длиной ≥2) · `next_palindrome` (палиндромы из девяток) · `shortest_path_length` (проверить типы ключей `Node` vs id) · `shortest_path_lengths` (несимметричный граф) · `shortest_paths` (≥2 релаксации + отрицательное ребро) |
| Ф4.3 | **Правило честности:** каждый новый `DIVERGED` воспроизводится **дважды** живым вызовом и классифицируется (`value`/`crash`/`hang`). Если задача осталась `EXPLORED` — так и написано |
| Ф4.4 | CHECK `quixbugs-replay`: перепроверяет все `DIVERGED` из лога; canfail: подменили вердикт в логе → красный |

**Kill criteria:** если задача не даёт воспроизводимого расхождения — цифра не двигается,
статус остаётся `EXPLORED` с объяснением.

---

## §8 Фаза 4B — Корпус проверки кода: `FP = 0` (~1.5 сессии)

Цель: измерять **качество вердиктов KERN на реальном коде**, а не только «поймали ли баг».
Ложное `F` — худший дефект верификатора.

| Пункт | Что делаем | Acceptance |
|:--|:--|:--|
| Ф4B.1 | `audits/codecheck/` — 12 файлов на старте (4 Zig, 4 Python, 2 C, 2 граничных) + `<file>.expect.json`: ожидаемый вердикт, **класс** контрпримера, класс дефекта | Вердикт **вычисляется** `kernc`, а не читается из ожиданий |
| Ф4B.2 | `make codecheck`: матрица `TP / FP / FN / UNKNOWN` | **`FP = 0`** — жёсткие врата; `UNKNOWN` печатается, но не штрафуется |
| Ф4B.3 | Разметка через существующий `@kern:expect-violations` (не изобретаем третий способ) | Совместимо с текущим `kern_contracts.py` |
| Ф4B.4 | canfail: подмена ожидания `T→F` → красный; вписанное руками «доказано» → красный | — |

**Kill criteria:** появился хоть один `FP` — фаза не закрывается; сначала чинится верификатор.

---

## §9 Фаза 5 — Обязательный конформанс-пакет (~1.5 сессии)

`tools/conformance_check.py` — 12 разделов, каждый печатает `PASS/FAIL`, ненулевой RC при провале:

1. все 4 значения Белнапа достижимы и различимы;
2. все 16 пар `joinK`;
3. обе решётки: `≤K` (информация) и `≤T` (истина);
4. 7 осей + законы `timeout≠F`, `out_of_fuel≠B`, `invalid_certificate≠F`;
5. `add`/`retract`: идемпотентность, пересчёт `(p,n)`, порядконезависимость;
6. негативный SCC в `G_src` отвергается;
7. `certificate reuse rejection` (другая функция / другой `QueryKind`);
8. квоты KERN-X (общий `fuel`, `arena`, `output`, `depth`, `host_calls`);
9. инвалидация 13-польного кэша по каждому полю;
10. битые `.kimg`: overflow, unknown-required, wrong endianness, `fsck`, `diff`;
11. атаки на KERNFS: `../`, NUL, `//`, запись, `no-mmap`;
12. детерминизм: два прогона → одинаковый вердикт.

Плюс `make conformance-check`, стадия в `ci.sh`, CHECK-цель и **мета-кейс canfail**:
сломали одно требование → harness обязан покраснеть (иначе он не доказательство).

---

## §10 Фаза 6 — Отложенные возможности

> **ИТОГ:** `Ф6.1` и `Ф6.3` выполнены. **`Ф6.2` перенесена в §15 Backlog.**
> Причина: полный текст Kamide & Niki 2026 (`10.1093/jigpal/jzag024`,
> *Logic Journal of the IGPL*) локально недоступен (`read = {false}`), а
> статья исследует **секвенциальное исчисление Генцена `sQBDi`**, а не
> конечное развёртывание миров Крипке в SMT-LIB. Писать семантику по
> абстракту запрещено §1 (принцип «нет атрибуции без прочитанного текста»).

### Ф6.1 Классы контрактов `hard` / `advisory` (~1 сессия)

- Грамматика: `@kern:requires|ensures` получает класс; **класс входит в отпечаток замка**
  (`<fn>:ensures:hard`), по умолчанию — `hard`.
- `advisory` допустим **только** если человек вписал его в `docs/contracts.lock.json`;
  агент, переклеивший `hard` → `advisory`, валит `contracts-lock-check`.
- Вывод различает `T` (чисто) и `T_advisory`; счётчик `T` не смешивает их.
- **Почему не «strict/tolerant Фиттинга»:** у Фиттинга это про следование
  (истинность посылок → нефальсифицируемость заключения), а не про severity.
  Ссылка на источник идеи — да, переименование понятия — нет.
- Acceptance: переклейка класса → замок краснеет; `T_advisory` виден в JSON и в CI.

### Ф6.2 Интуиционистский режим с ограниченными мирами (~2 сессии)

- `kernc prove --intuitionistic --worlds N`: миры и достижимость кодируются в SMT-LIB,
  замыкание разворачивается явно до глубины `N`.
- Результат — `CoverageState.bounded`, **никогда не `T`**. `T` возможен только при отдельном
  доказательстве достаточности `N` (finite model property для конкретного фрагмента).
- `--worlds 0` → отказ. В выводе печатается `bound = N`.
- Перед реализацией: прочитать статью целиком, поставить `read = {true}` в `references.bib`.
- **Почему отложено:** рефлексивно-транзитивное замыкание не выражается в логике первого
  порядка; для сегодняшних QF_LIA-контрактов интуиционистская версия не добавляет ничего.

### Ф6.3 `explain --hypotheses` — только отчёт (~1 сессия)

```bash
python3 tools/kern_contracts.py explain --hypotheses FILE [--fn NAME] [--json]
```

- Вход: файл с `@kern:` — тот же путь, что у `make contracts`.
- Выход: падающая функция, контрпример, **кандидаты-гипотезы только по `requires`**
  (перепроверены повторным прогоном Z3), для каждой — что отсекает и что **не** отсекает,
  флаг `fragile`; баннер «ГИПОТЕЗА, не доказательство. Файл не изменён».
- **Никогда** не предлагает ослабить `ensures`; **никогда** не пишет в файлы
  (`sha256` до/после равны); детерминированный порядок; лимиты `--max-hypotheses`, таймаут;
  в JSON `"kind":"hypothesis"`.
- **Почему не автоправка:** автодописывание `requires` — это ослабление спецификации под
  реализацию, ровно тот чит, против которого стоит `contract_fingerprints`.
  Абдуктивные гипотезы не единственны и не гарантированно корректны.

---

## §11 Рассмотрено и отклонено (с причиной)

| Отклонено | Причина |
|:--|:--|
| `@kern:necessary` / `@kern:possible` (модальности Петрухина) | Нет добавленной выразительности: это `∀ inputs` / `∃ inputs`, уже выразимые в текущей грамматике. Плюс ложная атрибуция: у Петрухина модальности существенности/случайности над B4, а не темпоральные □/◇ над запусками |
| Автозапись `@kern:requires` по абдукции | Ослабление спецификации под реализацию — ровно тот чит, против которого стоит `contract_fingerprints`. Абдуктивные гипотезы не единственны и не гарантированно корректны |
| Трирешётка 16₃ (Шрамко–Ванзинг) | Вне области: KERN работает с B4; расширение не даёт ничего для контрактов |
| First-order intuitionistic BD (Ники) как ядро | KERN — пропозициональный SMT-контур; первопорядковый вариант не нужен |
| `harness2` как зависимость | Нет grader’а, бенчмарки JobBench/LAB/WorkBuddy (не QuixBugs), нужны сеть/ключи/деньги |
| Sigstore/cosign, Z3 proof production | Отдельный трек (backlog), не в этом плане |
| Windows/macOS **runtime** | Только cross-compile в 0K.11 |
| EN-перевод глубоких доков | Внутренняя спецификация; витрина уже двуязычна |
| Переписывание git-истории, PDF в репозитории | Необратимо / копирайт |

---

## §12 Литература: что подтверждено, что нет

Полный список — в `docs/references.bib` (0J.1). Здесь — статусы на момент записи плана.

| Ключ | Цитата | Статус |
|:--|:--|:--|
| `belnap1977useful` | Belnap, *A Useful Four-Valued Logic*, in Dunn & Epstein (eds.), Modern Uses of Multiple-Valued Logic, Springer, pp. 5–37, DOI 10.1007/978-94-010-1161-7_2 | verified |
| `dunn1976intuitive` | Dunn, *Intuitive semantics for first-degree entailments and «coupled trees»*, Philos. Studies 29(3): 149–168, DOI 10.1007/BF00373152 | verified |
| `ginsberg1988` | *Computational Intelligence* 4(3), 1988 | verified (страницы 265–315/316 — вариант) |
| `fitting1991` | *J. Logic Programming* 11(2): 91–116, DOI 10.1016/0743-1066(91)90014-G | verified |
| `arieli1996` | *J. Logic, Language and Information* 5(1): 25–63 | verified |
| `font1997` | *Logic J. of the IGPL* 5(3): 413–440 | verified |
| `omori2017forty` | *Studia Logica* 105(6): 1021–1049, DOI 10.1007/s11225-017-9748-6 | verified |
| `shramko2005sixteen` | *J. Philosophical Logic* 34: 121–153, DOI 10.1007/s10992-005-0556-5 | verified |
| `shramko2011truth` | *Truth and Falsehood*, Trends in Logic 36, Springer | verified |
| `omori2019newessays` | *New Essays on Belnap-Dunn Logic*, Synthese Library 418 | verified |
| `karpenko2017four` | *Bulletin of the Section of Logic* 46(1/2): 33–45, DOI 10.18778/0138-0680.46.1.2.04 | verified |
| `pavlov2005` | Логические исследования 12: 243–248, DOI 10.21146/2074-1472-2005-12-0-243-248 | verified |
| `shramko2017relatives` | Shramko, Zaitsev, Belikov, *Studia Logica* 105: 1291–1317 | verified |
| `jakl2025four` | arXiv:2503.20679 (единственный автор — Jakl) | verified (препринт) |
| `bienvenu2026abductive` | *JAIR* 85, DOI 10.1613/jair.1.18874 | verified |
| `niki2026firstorder` | *Logic J. of the IGPL*, DOI 10.1093/jigpal/jzag024 | verified |
| `petrukhin2026essence` | *Studia Logica*, DOI 10.1007/s11225-026-10250-z | verified |
| `rivieccio2010residuated` | *Soft Computing* 14(5): 493–504 | verified (DOI требует сверки) |
| `casari2025abelian` | *Logic and Logical Philosophy* 34(2): 225–252 | verified |
| `middelburg2025interdefinability` | arXiv:2403.04641 v4 (16 Sep 2025) | verified (препринт) |
| `karpenko2010` | «Логики Белнапа и ДМ4: расширения», ЛИ Вып. 16 | **unverified** (в содержании выпуска другая статья) |
| `belikov2017` | Рацио.ru № 18(1), с. 36–48 | **unverified** |
| `fitting2026strict` | «Strict/Tolerant Intuitionistic Analogs…» | **unverified** (не найдено) |
| `jago2026talk` | «Metaphysical Structure and Bilattices», доклад | **unverified** (доклады не индексируются) |

**Найденные расхождения черновика** (в `BELNAP_SOURCES.md` §7): несуществующий выпуск JANCL 2020 →
реально `omori2017forty`; «Jung et al., Studia Logica 2026» → реально `jakl2025four` (arXiv, один автор);
«Aoyama» → реально `niki2026firstorder`; «Badura» → реально `bienvenu2026abductive`;
Rivieccio «2024» → 2010; DOI Омори с иной последней цифрой; страницы Павлова; сборник и страницы
Belnap 1977 (DOI ведёт к Dunn & Epstein, pp. 5–37).

**Правило:** `unverified` не цитируется в §1–§6 `BELNAP_SOURCES.md` и не используется как основание
для решений. `citations-check` это проверяет машинно.

---

## §13 Оценка объёма и карта релизов

| Шаг | Сессий | Релиз |
|:--|--:|:--|
| 0K Доверие и воспроизводимость | 2.0 | `v2.5.3` |
| 0J Литература как данные | 0.5 | `v2.5.3` |
| Ф1 Семь осей + `QueryKind` | 1.0 | `v2.5.4` |
| Ф2 Ledger + три графа | 1.5 | `v2.5.5` |
| Ф3 KIMG · KERNFS · CacheKey · KERN-X | 2.0 | `v2.5.6` |
| Ф4 QuixBugs (7 задач) | 1.5 | `v2.5.7` |
| Ф4B Корпус проверки кода | 1.5 | `v2.5.7` |
| Ф5 Конформанс-пакет | 1.5 | `v2.5.8` |
| Ф6.1 Классы контрактов | 1.0 | `v2.6.0` |
| Ф6.2 Интуиционистский bounded | 2.0 | `v2.6.0` |
| Ф6.3 `explain --hypotheses` | 1.0 | `v2.6.0` |
| **Итого** | **15.5** | |

**Политика версий** (`docs/SEMVER.md`, создаётся в 0K): patch может добавлять внутренние модули
и CLI-команды; **minor** — при изменении C-ABI или формата `.kimg`. Поэтому Ф1–Ф5 идут как
patch-релизы, а Ф6 (новые классы контрактов = пользовательская семантика) — как `v2.6.0`.

---

## §14 Definition of Done (для всего плана)

1. `make ci` (Lean + canfail) зелёный на **чистом** дереве.
2. `make verify-attestation` проходит **на чужой машине**, имея только `docs/keys/kern-owner.pub`.
3. `make conformance-check` → RC=0 **и** краснеет при подсаженном дефекте.
4. `make codecheck` → **`FP = 0`** на корпусе.
5. `make citations-check` → 5/5 диверсий краснеют.
6. `make sync` идемпотентен; `docs-parity` 9/9.
7. `make secrets-check` → 0 находок.
8. Детерминизм: два прогона одного входа → один вердикт.
9. Тег подписан; CHANGELOG содержит версию; аттестат с `attests_commit` + `kid`.
10. `docs/` без устаревших версий и чисел (guard + stale-check).

---

## §15 Backlog (вне этого плана)

### `--intuitionistic --worlds N` (бывшая Ф6.2) — перенесено 2026-10-21

Причина переноса, дословно: **полный текст не прочитан** (`read = {false}` в
`docs/references.bib` для `niki2026firstorder`). Доступны только метаданные
и абстракт: Kamide & Niki, *First-order intuitionistic Belnap–Dunn logic:
proof-theoretic analysis of the American path*, IGPL, DOI
`10.1093/jigpal/jzag024` — работа о **секвенциальном исчислении `sQBDi`**,
а не о развёртывании миров Крипке до границы `N`.

Чтобы возобновить, нужно: (1) получить полный текст; (2) отметить
`read = {true}`; (3) зафиксировать в `BELNAP_SOURCES.md` §5, какую именно
семантику берём и почему; (4) только затем реализовать
`CoverageState.bounded` (никогда не `T`) с `--worlds 0 -> отказ`.

- **Z3 proof production** — снять Z3 с доверенной базы (сейчас `trusted: 0` относится к proof-checker, Z3 доверяется).
- **Sigstore/cosign + Rekor** — сторонний аттестат, путь к SLSA L3.
- **CHC/Horn для неограниченных циклов** — расширение `src/verifier/chc.zig` на реальные программы.
- **Windows/macOS runtime** — после cross-compile.
- **EN-перевод глубоких доков** (`PROJECT_SPECIFICATION`, `TEST_CATALOG`, `RULE_THEOREM_MATRIX`).
- **harness2-эксперимент** (Propose–Probe–Compose) как R&D, без зависимости и без CI.
- **Производительность**: SIMD-хэш, кэш-хиты, профиль горячих путей.

---

## §16 Как возобновить работу (для человека и для агента)

```bash
cd "/home/mrbritneyxxx/Рабочий стол/kern"
git status --porcelain            # должно быть пусто
python3 tools/registry.py         # 162 цели: CHECK 128 · BUILD 8 · META 22
make ci-fast                      # 10 стадий, зелёные
python3 tools/slsa_provenance.py --check
```

Порядок старта: **0K → 0J → Ф1 → Ф2 → Ф3 → Ф4 → Ф4B → Ф5 → Ф6.1 → Ф6.2 → Ф6.3.**
Внутри шага: сначала падающий тест (или selftest стража), затем реализация, затем canfail-кейс,
затем `make sync`, `ci-fast`, `make seal`, новый тег.

Ссылки: `docs/CAPABILITY_STATUS.md` (журнал дефектов, последний — #250),
`docs/ROADMAP.md`, `docs/ATTESTATION_PASSPORT.md`, `docs/RELEASE_NOTES_v2.5.2.md`.
