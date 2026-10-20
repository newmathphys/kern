# KERN — карта документации

Навигация по проекту. **Читать в этом порядке.**

---

## С чего начать

| Хочу… | Открыть |
|:--|:--|
| **Понять проект ЦЕЛИКОМ (максимально подробно)** | **[`PROJECT_SPECIFICATION.md`](PROJECT_SPECIFICATION.md)** — 18 разделов: проблема, математика, архитектура L0–L5, формат байт-в-байт, Врата, SMT, KERN-Next, CLI, аттестация, дефекты, ограничения |
| Понять, что такое KERN (5 мин) | [`../README.md`](../README.md) — раздел «Быстрый старт» |
| Увидеть все цифры и замеры | [`METRICS.md`](METRICS.md) |
| Увидеть все тесты (339) | [`TEST_CATALOG.md`](TEST_CATALOG.md) |
| Узнать, что **не** сделано | [`../docs/CAPABILITY_STATUS.md`](../docs/CAPABILITY_STATUS.md) |
| Узнать, какие дефекты исправлены | [`KERN_FIXES_v1_3.md`](KERN_FIXES_v1_3.md) + [`METRICS.md`](METRICS.md) §39–§40 |
| **Убедиться, что проверки не вакуумны** | [`../README.md`](../README.md) §5b + `make canfail` |
| **Миграция на Zig 0.17.0** | [`VERIFICATION_0_17.md`](VERIFICATION_0_17.md) + [`MIGRATION_REPORT_0_17.md`](MIGRATION_REPORT_0_17.md) |

---

## Документы

### Показатели и проверки

| Документ | Что внутри |
|:--|:--|
| **[PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md)** | **ПОЛНОЕ ТЕХНИЧЕСКОЕ ОПИСАНИЕ** (18 разделов, ~1200 строк): математика Белнапа, архитектура L0–L5, формат `.kimg` байт-в-байт, Врата Истины, SMT-теории, KERN-X, KERN-Next, CLI, контур доверия, Lean 4, бенчмарки, аттестация, дефекты, ограничения, карта исходников |
| **[ATTESTATION_PASSPORT.md](ATTESTATION_PASSPORT.md)** | **Аттестационный паспорт**: все показатели проверены прогонами + сводка 11 поправок |
| **[CAPABILITIES.md](CAPABILITIES.md)** | **11 возможностей с доказательствами**: что подтверждено, что с оговоркой, что неверно |
| **[METRICS.en.md](METRICS.en.md)** · **[CAPABILITIES.en.md](CAPABILITIES.en.md)** · **[ATTESTATION_PASSPORT.en.md](ATTESTATION_PASSPORT.en.md)** · **[CAPABILITY_STATUS.en.md](CAPABILITY_STATUS.en.md)** | **English mirrors** ключевых документов (для внешнего читателя): витрина `README.md` уже полностью английская |
| **[METRICS.en.md](METRICS.en.md)** | **English mirror** of the metrics journal (§1–§53) + **§22 Build-runner notes (Zig 0.17)**: why `failed command: … --listen=-` appears on a GREEN run, and why `rm -rf .zig-cache/o` breaks the build (`addTranslateC`-generated `sqlite3_bridge.zig`) |
| **[bench/index.html](bench/index.html)** | **Детерминированный бенчмарк** (график на сайте): лавина, цепочка коллизий, χ². Генерируется `python3 tools/bench_json.py --html docs/bench/index.html`; цель `make bench-json` (can-fail доказана) |
| **[FIELD_AUDIT_REPORT.md](FIELD_AUDIT_REPORT.md)** | **Полевой аудит 14 реальных репозиториев** (Zig, C, Rust, TypeScript, Go, Python, Lean 4): Scorecard и `--xray` **ДО/ПОСЛЕ** исправлений (`[CRASH PATH]` **469 -> 8**; `cmark-gfm` 40 D -> 78 B, `tigerbeetle` 54 D -> 84 B, `aesop` 42 D -> 73 B) + семь дефектов, которые вскрыл сам прогон (#178–#184) |
| **[../audits/README.md](../audits/README.md)** | **Тень-контракты на чужом коде**: рукописные SMT-модели реальных выражений из сторонних проектов (например `isAligned` из `andrewrk/zig-general-purpose-allocator` — ДОКАЗАНО, и контрольная ломаная версия — КОНТРПРИМЕР) + замер, почему «прогон KERN по 50 репозиториям» даёт нули |
| **[TEST_CATALOG.md](TEST_CATALOG.md)** | Полный каталог: **424 теста** по модулям + 15 внешних бенчмарков. **Генерируется** из исходников (`tools/gen_test_catalog.py`); `--check` в CI ловит отставание |
| **[CYBERNETIC_VISION.en.md](CYBERNETIC_VISION.en.md)** | **English mirror** of the cybernetic vision essay (Anokhin · Glushkov · Belnap · Victor) |
| **[ROADMAP.en.md](ROADMAP.en.md)** | **English mirror** of the roadmap: final v2.5 status (8/8 echelons), closed debts, defects #155–#157 |
| **[TESTING_AND_SPEED_GUIDE.en.md](TESTING_AND_SPEED_GUIDE.en.md)** | **English mirror** of the testing guide (33 methods, speed-ups, defect→test map) |
| **[TESTING_AND_SPEED_GUIDE.md](TESTING_AND_SPEED_GUIDE.md)** | **Канонический гид по тестированию**: 8 разделов / 33 метода, таблица ускорений (`/dev/shm`, Fail-Fast, `--jobs`), хронология дефектов #123–#157 (какой тест поймал какой) |
| **[METRICS.md](METRICS.md)** | Журнал всех измерений по итерациям (§1–§128): тесты, бенчмарки, мутации, производительность, **реестр дефектов #1–#206**, разбор «почему просела скорость», предрелизная ревизия витрины (§75), закрытие K1/K2 |
| **[ROADMAP.md](ROADMAP.md)** | **План v2.5** (40 пунктов, 8 эшелонов) + **ИЗМЕРЕННАЯ инвентаризация**: какие пункты уже реализованы (5 теорий SMT, песочница Z3, guardrail-прокси), какие частично, какие новые — с доказательствами прогонами |
| **[VERIFICATION_GOLD_STANDARDS.md](VERIFICATION_GOLD_STANDARDS.md)** | Мировые бенчмарки: SWE-bench, HumanEval+, QuixBugs, Refactory, CyberSecEval, мутации |
| **[VERIFICATION_0_17.md](VERIFICATION_0_17.md)** | **Верификация на Zig 0.17.0**: сборка, 308 тестов, ARM64/PPC64 (QEMU), SLSA, полная карта ~300 API-правок |
| **[MIGRATION_REPORT_0_17.md](MIGRATION_REPORT_0_17.md)** | Отчёт о миграции 0.13→0.17: точная карта изменений, стратегия двух треков |

### Устройство и исправления

| Документ | Что внутри |
|:--|:--|
| **[KERN_FIXES_v1_3.md](KERN_FIXES_v1_3.md)** | 16 устранённых дефектов с доказательствами («было → стало») |
| **[EXECUTION_RUNNER.md](EXECUTION_RUNNER.md)** | Как заявление `N` становится `T`: авто-дискавери тестов, анти-вакуум, маскирование секретов |
| **[SPEC_ANCHORS_DEMO.md](SPEC_ANCHORS_DEMO.md)** | Мост «текст → контракт»: якоря `@kern:spec` превращают фразу из Markdown в `e=1` |
| **[KERN_TERMINOLOGY_v0.1.md](KERN_TERMINOLOGY_v0.1.md)** | Нормативная терминология (что такое квант, Врата, свидетельство) |

### Формальные методы

| Документ | Что внутри |
|:--|:--|
| [`../formal/README.md`](../formal/README.md) | 7 файлов Lean 4, 32 теоремы, 0 `sorry` |
| [`../formal/certification/TOR.md`](../formal/certification/TOR.md) | **TOR**: назначение инструмента + 53 требования (DO-330 TQL-1) |
| [`../formal/certification/TAS.md`](../formal/certification/TAS.md) | **TAS**: итоговый отчёт о выполнении для сертификационного офицера |
| [`../formal/certification/TRACEABILITY_MATRIX.md`](../formal/certification/TRACEABILITY_MATRIX.md) | требования → тесты (человекочитаемо) + [`.csv`](../formal/certification/TRACEABILITY_MATRIX.csv) |
| [`../formal/certification/SOUNDNESS_ARGUMENT.md`](../formal/certification/SOUNDNESS_ARGUMENT.md) | обоснование отсутствия ложных допусков |
| [`../formal/certification/SECURITY_TARGET.md`](../formal/certification/SECURITY_TARGET.md) | формальная модель безопасности (Common Criteria) |
| [`../formal/certification/KNOWN_LIMITATIONS.md`](../formal/certification/KNOWN_LIMITATIONS.md) | **реестр 25 ограничений** (все fail-closed) |

### Свидетельства (сырые данные)

| Путь | Что внутри |
|:--|:--|
| [`evidence/`](evidence/) | Логи прогонов: сэмплы HumanEval (164), результаты EvalPlus, отчёт SWE-bench |
| [`archive/`](archive/) | Исторические аудиты по фазам (KERN_AUDIT, KERNFS_AUDIT, KERN12/34, KERN9_SUITE) |

---

## Быстрые ссылки на команды

```bash
make help          # все цели (75)
make test-all      # полный контур проверок
make audit-manifest # сводный аттестационный статус (все строки — прогоны)
make sim           # детерминированный симулятор (VOPR-стиль)
make coverage      # покрытие решений (порог 100%)
make mutate        # мутационное тестирование
make bridge        # мост «текст → контракт»
make audit         # 5 теорий SMT на реальном Z3
make perf          # производительность (RAW vs безопасное чтение)
./formal/check.sh  # Lean-доказательства (0 errors, 0 sorry)

# --- Доказательство, что проверки СПОСОБНЫ упасть (K1–K5) ---
make canfail           # 60 кейсов: ломаем инвариант -> цель обязана покраснеть
make canfail-selftest  # кто проверит проверяющего: мета-проверка харнесса
make registry          # реестр 75 целей + предохранитель от «молчаливых» новых
make ci                # единый контур (12+ стадий); make ci-fast — быстрый
python3 tools/gen_test_catalog.py --check   # каталог тестов не отстал от кода
```

---

## Принцип проекта

> **Заявление считается доказанным (`e=1`) только при машинной опоре.**
> Всё остальное — честный `e=0`, а не «наверное работает».

Поэтому в документации везде различаются:
- **измерено** (есть команда + код возврата + число),
- **написано** (каркас, не проверено),
- **отсутствует** (честно помечено).

Разница между «написано» и «доказано» — это и есть предмет проекта.

## Language coverage (mirrors)

| Document | RU | EN |
|:--|:--|:--|
| README | `README.ru.md` | `README.md` |
| METRICS (measured journal) | `METRICS.md` | `METRICS.en.md` |
| ATTESTATION_PASSPORT | yes | `ATTESTATION_PASSPORT.en.md` |
| CAPABILITIES | yes | `CAPABILITIES.en.md` |
| CAPABILITY_STATUS (defect registry) | yes | `CAPABILITY_STATUS.en.md` |
| TESTING_AND_SPEED_GUIDE | yes | `TESTING_AND_SPEED_GUIDE.en.md` |
| CYBERNETIC_VISION | yes | `CYBERNETIC_VISION.en.md` |
| ROADMAP | `ROADMAP.md` (full) | `ROADMAP.en.md` (condensed) |

Other docs (`PROJECT*.md`, `TEST_CATALOG.md`, `VERIFICATION*.md`, `MIGRATION_REPORT_0_17.md`, `KERN_FIXES_v1_3.md`, `OWNERSHIP.md`, `EXECUTION_RUNNER.md`, `SPEC_ANCHORS_DEMO.md`) are Russian-only; they are internal engineering records, not the public showcase.

## Authorship hygiene (.mailmap)

The first commits of this repository were made under service identities left over from project initialisation. Rewriting history would change the SHA of every later commit and break tags and the SLSA attestate, so the standard `.mailmap` mechanism is used instead: it affects only **display** (`git log --use-mailmap`, GitHub) and never the objects. Check: `git log --use-mailmap --format='%aN' | sort -u` — one line.
