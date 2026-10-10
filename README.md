# KERN — ядро проверки истины для ИИ-агентов

> **Отдельный проект.** Не часть `nyuui-core`. `nyuui` может им пользоваться,
> но живёт и развивается самостоятельно.

**Статус:** исследовательский прототип. Физика (mmap, zero-copy) работает и
измерена. Эпистемическая часть (Врата Истины) **исправлена в v1.3** — обход
«одним байтом» закрыт, вердикт приходит только от внешнего чекера
(см. `docs/KERN_FIXES_v1_3.md`).

---

## 1. Зачем это

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

## 2. Состав

```
kern/
├── build.zig                       сборка (Zig 0.13): kernc, kern-attack, kernx, test, test-next
├── docs/                           аудиты и отчёты — читать до кода
│   ├── KERN_AUDIT.md               Фаза 1-2: Zig-компилятор
│   ├── KERNFS_AUDIT.md             Фаза 3: виртуальная ФС, ZIP SLIP, память
│   ├── KERN12_AUDIT.md             v1.2: BLAKE3 vs SHA-256, payload_offset
│   ├── KERN34_AUDIT.md             Фазы 3-4 + CLI: АТАКА на шлюз
│   ├── KERN9_SUITE_AUDIT.md        security-сьют: offset bomb
│   ├── KERN_FIXES_v1_3.md          v1.3: доказательства устранения дефектов
│   ├── VERIFICATION_GOLD_STANDARDS.md  бенчмарки (SWE-bench, SMT, QuixBugs, мутации)
│   ├── METRICS.md                  ЖУРНАЛ ПОКАЗАТЕЛЕЙ (все цифры из прогонов)
│   └── EXECUTION_RUNNER.md         переход N→T через машинные свидетельства
├── src/
│   ├── main.zig                    CLI kernc (читает образ .kimg)
│   ├── attack.zig                  демонстрация: обе атаки закрыты
│   ├── test_root.zig               корень тестов ядра
│   ├── core/
│   │   ├── eq2.zig                 KERN-EQ2: Белнап, joinK/meetK, andT/orT/notB
│   │   ├── object_entry.zig        96-байтный дескриптор + Merkle-корень
│   │   ├── kimg_reader.zig         128-байтный заголовок + безопасная арифметика + Merkle
│   │   └── kernfs_router.zig       VFS: валидация путей, монтирование, AccessDenied
│   ├── verifier/
│   │   ├── admission_gate.zig      Врата Истины (e=1): вердикт ТОЛЬКО от внешнего чекера
│   │   └── z3_bridge.zig           Z3 SMT-LIB2 мост (дочерний процесс, graceful)
│   ├── runtime/
│   │   └── kern_x.zig              KERN-X: fuel-bounded VM (без зависаний)
│   ├── proof_cache.zig             кэш доказательств (AST → вердикт)
│   ├── sdk/kern_sdk.py             Python SDK (тонкая обёртка над CLI)
│   ├── tests/
│   │   └── exhaustive_suite.zig    security-сьют (SEC/MATH/AI/RES)
│   └── next/                       KERN-Next (движок проекта `kernx`)
│       ├── ast.zig                 модель: Status/Kind/Claim/Evidence/...
│       ├── parser.zig              лексер + парсер языка .kern
│       ├── validate.zig            валидатор (§8: 10 правил)
│       ├── catalog.zig             SQLite-каталог .kdb (§9)
│       ├── snapshot.zig            snapshot + diff (§10)
│       ├── export.zig              agent packet (§17) + human report (§14.1)
│       ├── cache.zig               хэш содержимого, инкрементальность (§11)
│       ├── engine.zig              конвейер (§6.1)
│       ├── main.zig                CLI kernx (§13)
│       └── test_root.zig           корень тестов KERN-Next
├── tools/golden_v1_3.py            сборка эталонного образа .kimg v1.3
├── examples/project.kern           демонстрационный проект KERN-Next
├── examples/hello_world.kern       минимальный проект
├── tests/fixtures/valid_v1_3.kimg  эталонный образ (410 байт)
├── Makefile                        единая точка входа (build/test/demo/docker/lean)
├── formal/                         ФОРМАЛЬНЫЕ ДОКАЗАТЕЛЬСТВА Lean 4 (0 ошибок, 0 sorry)
│   ├── KernAllMath.lean            Белнап B₄: де Морган, JOIN_K, анти-вакуум, fuel-DFS
│   ├── KernDfsTermination.lean     завершимость обхода (фундированность)
│   ├── KernTalk.lean               unify: human.max < ai.min ⇒ конфликт B
│   ├── KernTalkND.lean             N-мерная унификация ⇒ глобальный B
│   ├── KernConvergence.lean        сходимость RLAIF-цикла за конечное число шагов
│   └── check.sh                    компиляция всех + проверка отсутствия sorry
├── Dockerfile · docker-compose.yml оболочки упаковки (не измерены — нет docker)
├── kern-cluster.yaml               K8s Deployment + HPA (оболочка)
├── vscode-kern/                    расширение KERN Lens (каркас)
└── REVISION/HONEST_CAPABILITY_STATUS.md  ЧЕСТНЫЙ статус: что измерено, что нет
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
| **Z3-мост** | graceful: без `z3` → `ToolError`→`e=0` (реальный прогон не выполнялся) |

> ⚠️ Полный честный статус «что измерено / что нет» — в
> `REVISION/HONEST_CAPABILITY_STATUS.md`. Он обязателен к прочтению: часть
> спецификации (облако, WASM, Lean, плагины) — **не реализована**.

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

- **Внешний прувер (Z3/Lean) не сконфигурирован.** Врата безопасны по умолчанию
  (`e=0`), но для реального допуска нужен внешний процесс-решатель. Это
  сознательный выбор: лучше `e=0`, чем `e=1` без доказательства.
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

* **mrbritneyxxx** — создатель и главный архитектор KERN.

## Лицензия

Этот проект распространяется под лицензией **MIT** — подробности в файле
[LICENSE](LICENSE).

```
Copyright (c) 2026 mrbritneyxxx
```

Каждый исходный файл (`src/**/*.zig`, `formal/*.lean`) содержит заголовок
Copyright — даже при копировании отдельного файла авторство сохраняется.

## Аттестация вердиктов

Вердикт `e=1` можно криптографически подписать (`src/attest.zig`, Ed25519) —
получается **сертификат удалённой аттестации**: клиент проверяет, что вердикт
выдан неизменённым ядром. В проде корень доверия — аппаратный (TPM/SGX/Nitro);
крипто-конвейер реализован и покрыт тестами.
