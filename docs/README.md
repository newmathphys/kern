# KERN — карта документации

Навигация по проекту. **Читать в этом порядке.**

---

## С чего начать

| Хочу… | Открыть |
|:--|:--|
| Понять, что такое KERN (5 мин) | [`../README.md`](../README.md) — раздел «Быстрый старт» |
| Увидеть все цифры и замеры | [`METRICS.md`](METRICS.md) |
| Увидеть все тесты (213) | [`TEST_CATALOG.md`](TEST_CATALOG.md) |
| Узнать, что **не** сделано | [`../REVISION/HONEST_CAPABILITY_STATUS.md`](../REVISION/HONEST_CAPABILITY_STATUS.md) |
| Узнать, какие дефекты исправлены | [`KERN_FIXES_v1_3.md`](KERN_FIXES_v1_3.md) |

---

## Документы

### Показатели и проверки

| Документ | Что внутри |
|:--|:--|
| **[CAPABILITIES.md](CAPABILITIES.md)** | **11 возможностей с доказательствами**: что подтверждено, что с оговоркой, что неверно |
| **[TEST_CATALOG.md](TEST_CATALOG.md)** | Полный каталог: 213 тестов по модулям + 15 внешних бенчмарков |
| **[METRICS.md](METRICS.md)** | Журнал всех измерений по итерациям (§1–§20): тесты, бенчмарки, мутации, производительность, найденные баги |
| **[VERIFICATION_GOLD_STANDARDS.md](VERIFICATION_GOLD_STANDARDS.md)** | Мировые бенчмарки: SWE-bench, HumanEval+, QuixBugs, Refactory, CyberSecEval, мутации |

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
| [`../formal/certification/TRACEABILITY_MATRIX.md`](../formal/certification/TRACEABILITY_MATRIX.md) | Матрица трассируемости TOR → тест (DO-330) |
| [`../formal/certification/SOUNDNESS_ARGUMENT.md`](../formal/certification/SOUNDNESS_ARGUMENT.md) | Обоснование отсутствия ложных допусков |
| [`../formal/certification/SECURITY_TARGET.md`](../formal/certification/SECURITY_TARGET.md) | Формальная модель безопасности |

### Свидетельства (сырые данные)

| Путь | Что внутри |
|:--|:--|
| [`evidence/`](evidence/) | Логи прогонов: сэмплы HumanEval (164), результаты EvalPlus, отчёт SWE-bench |
| [`archive/`](archive/) | Исторические аудиты по фазам (KERN_AUDIT, KERNFS_AUDIT, KERN12/34, KERN9_SUITE) |

---

## Быстрые ссылки на команды

```bash
make help          # все 62 цели
make test-all      # полный контур проверок
make coverage      # покрытие решений (100%)
make mutate        # мутационное тестирование
make bridge        # мост «текст → контракт»
make audit         # 5 теорий SMT на реальном Z3
make perf          # производительность (RAW vs безопасное чтение)
./formal/check.sh  # Lean-доказательства
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
