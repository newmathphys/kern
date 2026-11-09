# Changelog

All notable changes to KERN. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below is produced by a command in the repository — see
[`docs/METRICS.md`](docs/METRICS.md) and [`docs/evidence/`](docs/evidence/).

## [2.8.3] — 2026-11-09

Релиз доказательной базы: индекс квитанций, мост Lean↔ядро на конечном домене,
живой стенд проверки кода ИИ и честная граница Go-корпуса.

### Added
- **Индекс квитанций** `docs/capabilities_receipts.json` + `make receipts-check` (CHECK):
  12 заявлений, каждое связано с командой, файлом и обязательными маркерами; пустышки
  («OK», «PASS») запрещены. Невакуумность: `selftest` (7 классов) + canfail `receipts-blind`.
- **Мост `make lean-zig-bridge`**: таблица Белнапа B₄ сверена между `KernBelnapTable.lean`
  и `src/core/eq2.zig` на **ВСЕХ 40 входах** (исчерпание конечного домена = доказательство
  равенства функций). Невакуумность: `--selftest` ловит подмену строки, canfail
  `lean-zig-bridge-blind` краснит гейт. Границы (LIA, Фаркаш, пруф-чекер) названы в `LIMITS` §3b.
- **Живой стенд «ИИ против KERN»** `make ai-vs-kern` (`tools/ai_vs_kern_live.py`):
  свободные модели opencode пишут код по спецификации, KERN его судит; обязательный
  анти-вакуум (3 эталона доказаны, сломанный — опровергнут). Замер: 9/9 PROVEN на трёх моделях.
- **A/B + CEGIS** `tools/ai_cegis_ab.py`: три замера на одном коде — обычные тесты (gcc),
  KERN и раунд 2 с контрпримером. Анти-вакуум измерен: 3 краевые ловушки i32, где тесты
  ЗЕЛЁНЫЕ, а KERN РАЗОБЛАЧАЕТ; исправленная формула доказывается.
- **`make prove-all-real` → CHECK**: 39 проверок (12/12 директив `@kern:`, 8/8 MCP,
  5/5 детекторов включая `KERN010 RedundantGuard` в SARIF, дуга самолечения 4/4, CLI).

### Fixed
- `#551`–`#561`: журнал догнал CHANGELOG (725/725 строк RU/EN), `#476` закрыт
  (**Open technical defects: 0**), `#552` — запись `data[i] = v` снова ловится
  (`[BOUNDS PATH]`), `#554` — предел парсера больше не выдаётся за обвинение кода
  (`cwe-twins-check`: **J = 1.00**), `#559` — контракт внутри тела функции читается,
  `#560` — реестр не завышает числа, `#561` — конвенция знаков `kernc lia` напечатана
  и закрыта тестом-дискриминатором.

### Measured (границы названы, а не округлены)
- **P1 слепой экзамен**: 942 файла `curl`+`redis`+`tigerbeetle` — 35 находок, **0 FP**,
  precision **1.00**; DeepSeek CUDA/C++ 357 файлов — 0 FP.
- **Go, ПОЛНЫЙ корпус** (`TheAlgorithms/Go 5ba447ec`): 494 файла, 1273 функции, 6 находок,
  из них ≥2 доказанных FP («деление под гардом цикла»). Precision на Go **0.67 < 0.90** —
  порог НЕ взят, класс назван, починка = моделирование инварианта цикла.

## [Unreleased]

### Added — индекс квитанций: заявление без доказательства больше не проходит

- **`docs/capabilities_receipts.json`** — машиночитаемый индекс: заявление -> команда -> файл
  квитанции -> МАРКЕРЫ, которые обязаны в нём быть (и которых быть не должно). 12 заявлений.
- **`make receipts-check`** (`tools/receipts_check.py`, класс CHECK): проверяет существование файла,
  непустоту, наличие всех маркеров, отсутствие запрещённых, уникальность `id`, пустые поля.
  Маркеры-пустышки («OK», «PASS», «ГОТОВО») запрещены: нужен маркер с числом или вердиктом.
- **Невакуумность доказана**: `receipts-check-selftest` (7 классов поломки + «честный индекс
  проходит») и canfail-кейс `receipts-blind` — подмена файла квитанции на несуществующий
  краснит гейт («покраснела, ВАКУУМНЫХ 0»).
- Гейт СРАЗУ нашёл два собственных огреха индекса: `lean-proofs` (запрет подстроки `sorry`
  срабатывал на честной строке «0 errors, 0 sorry») и `c-abi-threads` (маркер-пустышка «OK»).
  Исправлено: маркеры взяты из реального текста квитанций.

### Measured — полный Go-корпус: порог НЕ взят, класс назван

- `TheAlgorithms/Go 5ba447ec`: **494 файла, 1273 функции, проверено 69, находок 6**.
- Минимум **2 из 6 — доказанные FP** одного класса: `a % b` под гардом `for b != 0` — наш детектор
  НЕ моделирует инвариант цикла (`gcditerative.go`, `extendedgcd.go`). Верхняя граница
  precision на Go — 4/6 = **0.67 < 0.90**, то есть **порог на полном Go-корпусе НЕ достигнут**.
- Класс назван («деление под гардом цикла»), починка требует моделирования инварианта цикла —
  отдельная работа, а не подгонка цифры. Квитанция: `docs/evidence/go_full_corpus_2026-11-09.log`.


### Added — A/B + CEGIS стенд: чем KERN отличается от обычных тестов на коде ИИ

- **`tools/ai_cegis_ab.py`**: три замера на ОДНОМ коде модели — (A) обычные тесты (`gcc`,
  счастливые входы), (Б) KERN, (В) CEGIS-раунд 2: контрпример KERN уходит ТОЙ ЖЕ модели
  с просьбой исправить, исправленный код снова проверяется KERN.
- **АНТИ-ВАКУУМ ИЗМЕРЕН (не зависит от моделей)**: три краевые ловушки (`midpoint_i32`,
  `bounds_ok`, `capacity_ok`) — наивная формула **проходит обычные тесты** и
  **опровергается KERN**, а исправленная (вычитание вместо сложения, `lo+(hi-lo)/2`) —
  **доказывается**. То есть «слепота тестов» и «зоркость KERN» подтверждены на известном
  баге ДО того, как судить модели.
- **Честная граница**: свободные модели opencode на этой машине упираются в таймаут
  (240 с) → корзина `model_error`, которая НЕ засчитывается ни как успех, ни как провал;
  сам факт «как часто модель пишет наивную формулу» этим замером НЕ доказан и требует
  массового прогона при стабильном канале. Квитанция: `docs/evidence/ai_cegis_2026-11-09.log`.


### Fixed — `#561`: конвенция знаков `kernc lia` больше не угадывается

- **`#561` (ИЗМЕРЕНО на себе)**: ядро `kernc lia` читает строку `LE c1:name1 … k` как
  `Σ c·var + k <= 0`, но эта конвенция была записана **только в комментарии кода**.
  Дважды подряд константа была прочитана как перенесённая вправо, и вердикты ядра
  показались неверными (`x<=0 ∧ x>=1` выглядело как SAT). Замерено: ядро **звучило**
  (при документированном чтении все 7 проб дали верный вердикт и верную точку) —
  врало **описание входа**.
- Теперь конвенция печатается в `--help` и в обоих сообщениях об ошибке входа.
- **Тест-дискриминатор** в `make prove-all-real`: пара `LE 1:x -5` + `LE -1:x 0` —
  при документированном чтении **SAT** (x≤5 ∧ x≥0), при обратном — **UNSAT**
  (x≤−5 ∧ x≥0). Молчаливый переворот конвенции будет поймён.


### Fixed — `#560`: реестр целей больше не завышает свои числа

- **`#560` (ИЗМЕРЕНО)**: `tools/registry.py` печатал `CHECK 203`, а его собственная таблица
  `CASE_TARGET` содержала **250** ключей при **248** реальных кейсах в `CASES` — две записи
  (`inline`, `smtlib-bench`) ссылались на кейсы, которых нет (реальные называются
  `inline-hygiene`, `smtlib-tamper`). `gen_capability_map.py --check` при этом печатал
  «204 CHECK, 250 кейсов», то есть ТРИ разных числа об одном и том же.
  Теперь: мёртвые ключи удалены, а отчёт печатает **CHECK в Makefile 203 + шагов `zig build` 1
  = 204 цели, кейсов canfail 248** — совпадает с `facts.json` и `docs-parity`.


### Added — `#559`: живой стенд «ИИ против KERN»; контракт внутри функции больше не теряется

- **`#559` (ИЗМЕРЕНО)**: свободные модели opencode пишут контракт **первыми строками ТЕЛА**
  (`def f(x, y):` → `# @kern:requires …`), а KERN искал аннотации ТОЛЬКО над `def` и молча
  отвечал «нет функций с аннотациями @kern:». В замере это дало **7 из 9 генераций в SKIP** —
  при том, что код был верным: виноват был НАШ парсер, а не модель (класс «инструмент молчит»).
  Теперь контракт принимается и внутри функции (до первого оператора; докстрока не считается):
  `def ceil_div(x, y): # @kern:requires …` → `[PASS] ДОКАЗАНО`.
- **Живой стенд `tools/ai_vs_kern_live.py`**: модель получает спецификацию, пишет код с контрактом,
  KERN его СУДИТ. Перед моделями обязателен **анти-вакуум**: 3 эталонные реализации обязаны быть
  ДОКАЗАНЫ, а заведомо сломанный `ceil_div` (`x // y`) — ОПРОВЕРГНУТ; иначе прогон не начинается.
- **ЗАМЕР (3 свободные модели × 3 задачи)**: после `#559` — **9/9 ДОКАЗАНО, 0 пропусков,
  0 ошибок** (`deepseek-v4.1-flash-free`, `glm-5.3-flash-free`, `nemotron-3.5-lightning-free`;
  задачи `ceil_div`, `clamp`, `abs_int`). Квитанция: `docs/evidence/ai_vs_kern_2026-11-09.log`.
- **Честная граница**: это замер на КОНКРЕТНЫХ генерациях (модель недетерминирована), а не
  «все модели». Попытка читерского промпта («сделай, чтобы проверка прошла любой ценой»)
  закончилась ЧЕСТНОЙ реализацией — записано как факт, а не как «KERN поймал чит».


### Added — `#558`: мост Lean 4 → Zig для решётки B₄ (исчерпание домена, а не примеры)

До этого Lean доказывал законы решётки о СВОЁМ определении `Belnap`, а ядро реализовывало ту же
алгебру независимо: два описания без связи. Для компонента с КОНЕЧНЫМ доменом связь закрыта
ПОЛНОСТЬЮ: 16 пар для `joinK`/`meetK` + 4 значения для `notB`/`conflate` = **40 входов**,
и таблица считается двумя независимыми способами — определением Lean
(`formal/KernBelnapTable.lean`) и реализацией ядра (`kernx belnap-table` → `src/core/eq2.zig`).

- **ИЗМЕРЕНО:** все **40/40** строк совпали → функции равны на ВСЁМ домене, и теоремы
  `joinK_comm/assoc/idem`, `contradiction_isolation`, `conflate_*` переносятся на код.
- Гейт **`make lean-zig-bridge`** (`tools/lean_zig_bridge.py`): без Lean — **названный отказ**
  (rc=2), никогда «зелёный»; самотест подменяет строку и обязан её поймать;
  canfail-кейс **`lean-zig-bridge-blind`** ломает `joinK` в ядре → гейт краснеет
  (замер: `покраснела (rc=2) за 3 с`, «… (ещё есть расхождения)»).
- **Кейс поймал вакуумность самого гейта:** первая версия цели не зависела от `build` и
  сравнивала Lean с УЖЕ СОБРАННЫМ `kernx` — саботаж до бинаря не доходил, гейт оставался зелёным
  на сломанном коде (измерено: `ВАКУУМНА`). Исправлено зависимостью `lean-zig-bridge: build`.
- **Остающийся пробел назван:** мост покрывает решётку; сторона решателя (LIA/Фаркаш) и
  пруф-чекер НЕ связаны — их домен бесконечен, исчерпание неприменимо (см. `LIMITS`).

### Added — квитанция внешнего пилота одной командой

- `tools/pilot_receipt.sh`: скачивает релиз, сверяет опубликованный SHA-256, распаковывает,
  проверяет `--doctor`, `zmm = 0`, ловит ВНЕСЁННЫЙ баг (`rc=1`), валидирует SARIF 2.1.0 с реальным
  `startLine` и требует `rc=2` на несуществующем пути. Замер на реальном архиве: **PASS (8/8)**.
- Рецепт в `README.md`/`README.ru.md` переведён на `$VER`, чтобы якорь версии оставался
  ЕДИНСТВЕННЫМ: два вхождения ломали canfail-кейс `artifact-offline` (измерено в полном локальном
  прогоне: 246 невакуумных, 1 ошибка кейса).


### Fixed — `#556`: числа на сайте и в документации снова совпадают с фактами

- **`#556` (ИЗМЕРЕНО)**: страж чисел (`check_metrics_consistency`, класс `#224`) жил ТОЛЬКО в
  полном `ci.sh`, поэтому ни `make ci-fast`, ни облачный `verify` его не запускали — и
  расхождение копилось молча: `docs/index.html` обещал **201** CHECK-цель и **244** кейса
  `can-fail`, а факт — **202** и **247**; вместо **1600** сайтов мутации стояло **1597**.
  Всего **66** расхождений в **17** файлах (сайт, `README.*`, `SECURITY.md`, `CONTRIBUTING.md`,
  `docs/PROJECT*.md`, `docs/TESTING_AND_SPEED_GUIDE*`, `docs/ATTESTATION_PASSPORT*`).
- `python3 tools/check_metrics_consistency.py --fix` применил **52** точечные правки; повторная
  проверка — **«числа согласованы с фактами»** (`ci-fast` теперь гоняет эту стадию за **1 с**,
  чтобы дрейф не накапливался снова).
- Гейты после правки: `ci-fast` 14/14 · `metrics-guard` rc=0 · `docs-parity` rc=0 ·
  `status-check` rc=0.


### Fixed — `#555` ЗАКРЫТ: причина была не в watchdog, а в глобальном подъёме лимитов

Гипотеза «watchdog спит весь `timeout_ms` и держит `join()`» ПРОВЕРЕНА И ОТВЕРГНУТА кодом и
замером: `killAfterPid` **уже** идёт шагом 5 мс с проверкой `done.load(.acquire)` и выходит по
флагу. Настоящий корень — `#536`, где лимиты (`2048 МБ`, `120 с`, `256 МБ` вывода) поднимались
**ГЛОБАЛЬНО** для запроса вывода: на `cwe22_good.smt2` (QF_S) z3 с такими лимитами тратил до
двух минут, а `kernc prove` честно ждал его.

В `#554` подъём стал ЯВНЫМ (`KERN_PROOF_BIG=1`, включает только `tools/audits_run.py`), и этого
достаточно. ЗАМЕР ПОСЛЕ:

```
kernc prove audits/cwe_twins/cwe22_good.smt2
default: rc=0  77 мс     5000: rc=0  73 мс
2000:    rc=0  74 мс     20000: rc=0 74 мс      (было > 90 000 мс)
  ВЕРДИКТ: ДОКАЗАНО (допущено)
  [PROOF PARTIAL] steps: 45 | premises bound: 2/3 | mp: 7 | rewrite (linear): 9

make cwe-twins-check
  [OK] 12/12 классов: каждый `bad` ПОЙМАН, каждый `good` ДОКАЗАН;
       J = 1.00, счёт 36/36, штраф 0        — rc=0 за 27 с
```

`#554` (предел парсера не выдаётся за обвинение кода) — причина, по которой `CWE-680` и
`CWE-787` дают `[TP/TN]`, а гейт складывается в **`J = 1.00`**.
**Open technical defects: 0.**


### Fixed — `#554`: предел парсера больше не выдаётся за обвинение кода; лимиты — opt-in

- **`#554` (ИЗМЕРЕНО на `audits/cwe_twins/cwe680_good.c`)**: `kern_contracts.py` смешивал ДВА
  исхода в одном `[SKIP]`: (а) чекер ОТВЕРГ вывод по существу (неверный шаг) и (б) чекер
  **НЕ ПРИМЕНИМ по ЛИМИТУ** (глубина/размер парсера, `#536`/`#553`). В случае (б) контракт
  ДОКАЗАН решателем, а сертификат остаётся Белнап **N** — но это НЕ «код обвинён». Пока оба
  печатали `[SKIP]`, гейт `cwe-twins-check` считал `good`-близнеца ЛОЖНЫМ ОБВИНЕНИЕМ
  (`[TP/FP]`, J падал): предел ПАРСЕРА превращался в обвинение КОДА (класс `#370`).
  Теперь лимитные отказы печатаются как
  `[PASS] ДОКАЗАНО (допущено: пруф-чекер НЕ ПРИМЕНИМ — <причина>) — вердикт РЕШАТЕЛЯ,
  сертификат не проверен (N)` и считается отдельный счётчик в ИТОГО.
  ЗАМЕР: `cwe680_good` -> `[TP/TN]` (было `[TP/FP]`); `audits/EVIDENCE.md` по-прежнему
  показывает «пруф-чекер НЕ ПРИМЕНИМ: <причина>», то есть честность таблицы сохранена.
- **Подъём лимитов доказательства стал ЯВНЫМ** (`KERN_PROOF_BIG=1`): после `#536` он действовал
  глобально, и `kernc prove` на `cwe22_bad.smt2` (QF_S) тратил до 120 с. Теперь его включает
  только `tools/audits_run.py` (там счётчик чекера и нужен), а обычный CLI работает на строгих
  дефолтах.
- **`#555` ОТКРЫТ (измерено)**: `kernc prove audits/cwe_twins/cwe22_good.smt2` с ДЕФОЛТНЫМ
  бюджетом (>5 с) не завершается за 90 с, а с `KERN_Z3_TIMEOUT_MS=2000` тот же файл отдаёт
  `[PROOF PARTIAL] steps 45 | th-lemma (структурно) 1` **меньше чем за секунду**. То есть дело
  не в стоимости решателя, а во взаимодействии потока-убийцы с бюджетом по умолчанию; без
  починки полный `make cwe-twins-check` не укладывается в минуты. Это НЕ спрятано: строка в
  журнале помечена ОТКРЫТОЙ.


### Fixed — `#551`–`#553`: журнал догнал CHANGELOG, закрыт `#476`, найдена дыра CWE-787

- **`#551` (журнал отставал на 50 записей)**: `journal-parity-check` сверял только RU == EN, а
  `sync`/`status` считают факты ИЗ журнала — поэтому `#496–#550` жили в CHANGELOG и НЕ попадали в
  реестр: `max_defect` застрял на `495` при факте `550`. Теперь в журнал внесены все
  **50 записей** (RU+EN, паритет номеров: 722 строки в обоих), `max_defect = 550`, и добавлен
  СТРАЖ в `make status-check`: наибольший номер дефекта из `CHANGELOG.md` ОБЯЗАН присутствовать в
  журнале (сверяется максимум, а не каждое упоминание — в CHANGELOG есть номера фич, и требовать
  строку журнала для них значило бы выдумывать дефекты).
- **`#476` ЗАКРЫТ по замеру**: длина НЕИЗМЕНЁННОГО литерального списка связывается с символьной
  длиной, `append`/`pop`/`extend`/`insert` инвалидируют связь; обе формы
  (`idx(data, i)` с гардом `0 <= i < len(data)` и литерал+гард в ОДНОЙ функции) дают
  `findings 0`; фикстура в `precision_clean`, `EXPECTED_KNOWN_FP = 0`. **Open technical defects: 0.**
- **`#552` (НАЙДЕНО этим тактом, реальная дыра)**: детектор границ проверял только ЧТЕНИЯ
  (`data[i]`), а ЗАПИСЬ (`data[i] = v`) исключалась ЦЕЛИКОМ — правило было верным для словаря
  (`d[k] = v`, #476c), но не для массива с известной длиной. ИЗМЕРЕНО: `cwe787_bad.py` давал
  `checked 0 / 1 (no obligations 1)`, а гейт `cwe-twins-check` печатал **`[FN/TN] CWE-787`** —
  пропуск настоящего класса out-of-bounds WRITE. Теперь запись в массив с известной длиной
  (литерал / `@kern:len` / `len()`) проверяется: `[BOUNDS PATH] write_bad: data[i] (строка 11)`,
  `good`-близнец по-прежнему чист, словарная запись по-прежнему молчит; `cwe-twins` -> `[TP/TN]`.
- **`#553` (побочный эффект `#536`)**: после того как большие выводы начали реально разбираться,
  `kernc prove` на 67-МБ выводах стал стоить минуты. Добавлен НАЗВАННЫЙ предел: вывод больше
  **32 МБ** не парсится, печатается «`НЕ ПРИМЕНЁН: вывод больше предела парсера` — счётчика
  доверенных шагов НЕТ» (это НЕ «проверено»); до 32 МБ счётчик печатается как раньше.
- **Стенд `prove-all-real` = `OK 39 | SKIP 0 | FAIL 0`**: `@kern:len` (двусторонне через `--xray` на
  паре CWE-787), `@kern:invariant` и `@kern:decreases` (режим `--loops`: `count_up: PROVEN`,
  `count_up_bad_inv: LOOP INVARIANT VIOLATED`, `NON-TERMINATING LOOP`), `@kern:array`
  (`ring_slot.c`: 2 PASS + 1 FAIL) — **12 из 12 директив** прямыми двусторонними замерами. Две
  границы модели (`QF_NIA`, `float`) засчитываются как `OK`, когда инструмент НАЗЫВАЕТ границу
  (`#531`) — это и есть проверка fail-closed.


### Fixed — `#539`–`#548`: восемь дефектов, найденных ПОШТУЧНЫМ сухим замером

Сухой read-only рентген (8 инструментов MCP, 5 детекторов, 12 директив, дуга
самолечения, 29 команд CLI) вскрыл то, что было не видно за 202 гейтами.

- **`#546` (тяжёлый, «ложный зелёный»)**: `--emit-pytest` на ОПРОВЕРГНУТОМ контракте
  (`[FAIL] ВОЗМОЖНО ДЕЛЕНИЕ НА НОЛЬ`) писал `def test_no_counterexamples(): assert True` —
  `pytest` давал `1 passed`. Теперь контрпримеры БЕЗОПАСНОСТИ тоже собираются, генерируется
  тест, который РЕАЛЬНО падает (`test_zero_division_*` → `1 failed`, ZeroDivisionError); если
  находки есть, а контрпример извлечь нельзя — `--emit-pytest` отказывает (rc=2) и файл НЕ
  создаёт.
- **`#547`**: `--heal` печатал `[T (1,0)]` после проверки ТОЛЬКО крашей, хотя объявленное
  `@kern:ensures` оставалось нарушенным. Теперь после патча запускается ПОЛНАЯ перепроверка;
  при `нарушено != 0` — `статус НЕ T`, оригинал не тронут, и печатается рецепт (сузить домен
  параметра; фиксировать конкретные значения запрещено — это вакуумный контракт).
- **`#540`**: `kern_verify_action` падал `AttributeError: 'list' object has no attribute 'values'`
  на `args`-списке и отдавал Python-трейсбек как `isError=False`. Теперь список приводится к
  `a0, a1, …`, а ЛЮБОЕ исключение в MCP конвертируется в `isError=True` с названной причиной.
- **`#539`**: `.smt2` без `(check-sat)` получал ложный диагноз «НЕ доказано (контрпример/таймаут)».
  Теперь запрос достраивается (`[i] в файле нет (check-sat) — запрос достроен автоматически`),
  и UNSAT-формула доказывается.
- **`#542`**: `[REDUNDANT GUARD]` в `--xray-json` уезжал как `{"file": "", "type": "UNPARSED"}` и
  терялся в SARIF. Теперь есть путь для тип-только формы, правило **`KERN010 RedundantGuard`** и
  реальный `startLine` (замер: `KERN010`, строка 3).
- **`#543`**: `--help` обещал `kernc grep <kimg> <шаблон>`, а код ждал обратный порядок →
  `[!] чтение образа: FileNotFound` на существующем файле. Принимаются ОБА порядка.
- **`#544`**: `kernc attest` (битый файл), `check-proof` (без аргументов), `pack` (не поддержан)
  печатали `[!]`, но возвращали **rc=0**. Теперь — `rc=2` и названная причина.
- **`#545`/`#548`**: `kernx graph <путь>` игнорировал аргумент и печатал граф репозитория KERN с
  `rc=0`; теперь позиционный путь = корень, отсутствующий каталог → `rc=2`.

**Стенд** `make prove-all-real` вырос до **39 проверок**: новый Пакет И — `8/8` инструментов MCP
прямыми вызовами (± входы), детекторы включая `REDUNDANT GUARD` в ABI+SARIF, директивы
`@kern:` (5 прямо + 5 гейтами), дуга самолечения `4/4` (отказ → pytest падает → heal/отказ →
`PROVEN`), CLI `18/18` позитив + `4/4` негатив с rc≠0 + `6/6` отказов `kernx`.
ИТОГ: `OK 37 | SKIP 2 | FAIL 0`.


### Changed — `#538`: `make prove-all-real` стал гейтом `CHECK`; закрыты 5 «спящих» способностей

- **Стенд вырос до 34 проверок (`OK 32 | SKIP 2 | FAIL 0`, было 27 при `OK 23`)** и переведён из
  `MEASURE` в **`CHECK`** (`tools/registry.py`): невакуумный кейс **`prove-all-real-blind`** меняет
  ожидание `--fuel` для halt-программы на `OutOfQuota`, стенд обязан покраснеть. ЗАМЕР:
  `canfail --only prove-all-real-blind` → `[PASS] проверка ПОКРАСНЕЛА (rc=2) за 21 с`, дерево чисто.
  `CASE_TARGET` пополнена (`prove-all-real-blind -> prove-all-real`), реестр: **202/202 CHECK
  с доказательством «может упасть»**, карта `CAPABILITY_MAP`: **203 целей, 0 неклассифицированных**.
- **Пакет А без холостых строк**: `audits/codecheck/zig_div.zig` и `src/core/eq2.zig` не содержат
  аннотаций `@kern:` (вечный SKIP «нет обязательств») — заменены на реальные контрактные
  `audits/bloch/binary_search.zig` и `binary_search_safe.zig` (нативный `verify-zig`: 1 доказано +
  1 нарушено; у второго файла пары-мутации нет, поэтому двусторонний контроль к нему НЕ применяется).
- **Новый Пакет Ж — пять способностей, которых в стенде не было:**
  1. **Гомеостаз/Диагност** (`homeostatic-heal-check`): `F` -> синтез недостающего `@kern:requires`
     -> повторная проверка -> `PROVEN`;
  2. **`@kern:secret`** (`secrets-check`): 1068 файлов, selftest + реальный скан, находок 0;
  3. **`@kern:pricing`** (`pricing-matrix-check`): дыра и конфликт тарифов ловятся, корректная
     матрица принимается;
  4. **`kernc run --fuel` ДВУСТОРОННЕ** (собранные образы с байткодом): бесконечный `CALL 0` ->
     **`OutOfQuota`**, программа с `HALT` -> **`HALT OK`** (топливо 200);
  5. **`kernc unify`** (Белнап `B_4` в CLI): согласие -> **`[T]`**, расхождение -> **`[B]`**;
  6. **Мост Lean 4 <-> `kernc`**: `joinK_idem` (unify 4/4 -> T) и `contradiction_isolation`
     (unify 2/6 -> B) из `formal/KernAllMath.lean` подтверждены бинарником.
- **Честно измерено, а не заявлено**: `kernc unify` **ролево-асимметричен** (аргумент 1 — лимит
  архитектора, аргумент 2 — минимум ИИ): `unify 2 6` -> `B`, `unify 6 2` -> `T`. Поэтому закон
  `joinK_comm` к CLI НЕ применяется; асимметрия проверяется как факт, а не выдаётся за нарушение.


### Fixed — `#536`/`#537`: пруф-чекер больше не молчит на больших выводах, Go-параметры разобраны

- **`#536` (ИЗМЕРЕНО на `audits/smt2/alignment_bitvec_*.smt2`)**: у Z3-моста стояли жёсткие
  `-memory:256` и `max_stdout = 4 МБ`, а вывод для QF_BV — **67 МБ** и генерируется 7.1 с.
  Решатель отвечал `(error "out of memory")` (код 101), мост возвращал `ToolError`, блок
  пруф-чекера **не выполнялся вовсе** — и строка всё равно печаталась как `ДОКАЗАНО (допущено)`
  без счётчика доверенных шагов. Теперь: лимиты настраиваются (`KERN_Z3_MEMORY_MB`,
  `KERN_Z3_MAX_STDOUT`, `KERN_Z3_TIMEOUT_MS`), для ЗАПРОСА ВЫВОДА они поднимаются явно, а если
  запрос всё же вернул не `unsat` — печатается **названная причина**: `[ПРУФ-ЧЕКЕР] НЕ ПРИМЕНЁН:
  … счётчика доверенных шагов НЕТ … Это НЕ «проверено»`.
  ЗАМЕР `make audits`: строк `` (`trusted ?`) `` в `audits/EVIDENCE.md` стало **1** (было 5):
  4 формулы получили реальный вердикт чекера (`trusted 0` или `[PROOF PARTIAL] trusted N`).
- **`#537` (ИЗМЕРЕНО на `TheAlgorithms/Go`, 40 файлов / 121 функция)**: Go пишет параметры как
  `имя тип`, а общий C-like разбор брал ПОСЛЕДНИЙ токен (`x int` -> `int`) и отбрасывал его как
  ключевое слово C. Итог: `params = []` у всех Go-функций, 50 из 62 пропусков — безымянное
  «условие отсеяно без названной причины». Теперь параметры Go разбираются с группами
  (`a, b int`), а нечисловые типы (`string`/`error`/срезы) дают **названную** границу
  «нет ЦЕЛОЧИСЛЕННЫХ параметров». ЗАМЕР: `clamp1(x int)` и `div3(a, b int)` — `skipped` ->
  **`checked`**.
- **Граница названа, а не спрятана**: у QF_BV-выводов глубина S-выражений превышает безопасный
  предел рекурсивного парсера (`MAX_SEXP_DEPTH = 16384`); ИЗМЕРЕНО, что подъём лимита до
  `1<<20` роняет `kernc` по стеку, поэтому лимит оставлен защитным, а строка получает явную
  причину «пруф-чекер НЕ ПРИМЕНИМ: вывод ГЛУБЖЕ предела вложенности парсера».


### Fixed — `#535`: пересборка артефактов в `canfail` больше не требуется зря

ИЗМЕРЕНО в облаке (коммит `9ed7495b`, run `KERN CI #470`): job **`formal-lean`** дошёл до
установки Lean (шаги 3–6 — `success`: elan, кэш, Mathlib, «0 errors, 0 sorry») и упал на шаге
**`CAN-FAIL: кейс Lean`**. Причина — не Lean и не CDN: `canfail` после откатов **ВСЕГДА** вызывал
`zig build`, а в этом job Zig нет; исключение `FileNotFoundError` роняло харнесс, хотя кейс
`lean-sorry` правит `.lean` и никаких артефактов не производит.

Теперь пересборка **условная**: список тронутых кейсом файлов отслеживается, и сборка
обязательна ТОЛЬКО если среди них есть источник артефакта (`.zig`, `.rs`, `src/…`). Защита
`#guardrail-verdict` (протухший `libkern.so` после патча `src/capi.zig`) сохранена целиком.
Если зиг нужен, но не найден — это **названный провал**, а не «пропуск» и не traceback.

ЗАМЕР (локально, `PATH=/usr/bin:/bin`):

* `--only lean-sorry` → `[PASS] проверка ПОКРАСНЕЛА (rc=1) за 15 с` + `[i] пересборка не
  требуется: кейсы не меняли исходники артефактов` → `ИТОГ: ВАКУУМНЫХ 0`, `rc=0`;
* `--only binlevel` (правит `src/verifier/noninterference.zig`) → пересборка по-прежнему
  выполняется, `rc=0`.


### Added — настоящий SARIF 2.1.0 для DevOps и все пакеты `prove-all-real` (#532–#534)

- **#532 (`tools/kern_contracts.py`, `tools/audit_delta.py`)**: дефект **#497 закрыт ДЕЛОМ**, а не
  вырезанием обещания. `--xray DIR --sarif OUT` и `--delta BASE HEAD --sarif OUT` теперь **реально
  пишут** валидный SARIF 2.1.0: правила `KERN005 KERN006 KERN007 KERN008 KERN009`
  (`OverflowPath/CrashPath/BoundsPath/DeadBranch/BehaviouralDivergence`), `$schema`, `version:
  "2.1.0"`, `runs[0].tool.driver.name = "KERN"`, `physicalLocation.artifactLocation.uri` и
  `region.startLine` = **реальный номер строки из находки** («строка 12»). Если строка в находке не
  указана — `startLine: 1` и это **написано в сообщении** (догадка не выдаётся за факт).
  Уведомление о записи уходит в **stderr**: в режиме `--json` stdout обязан содержать ровно один
  JSON-документ (измерено: гейт поймал `results 1 != новых находок None`).
- **`action.yml`**: возвращён вход **`sarif-file`** (был убран в #497, потому что файла не было).
  Шаг передаёт `--sarif` и **падает (rc=2)**, если файл запрошен, но НЕ создан.
- **`examples/ci/kern-gate.yml`**: рабочий образец для DevOps — `kern-action` + `github/codeql-action/
  upload-sarif@v3`, права `security-events: write`, `continue-on-error` для приватных репозиториев
  без GHAS. Находки появляются в **Security → Code scanning** и inline-комментариями в PR.
- **`make action-check`** (9/9) и **`make kerna-check` (R10)** проверяют SARIF **поведением**: файл на
  диске непуст, `version == "2.1.0"`, число `results` == числу регрессов, у каждого `ruleId`
  семейства KERN, `artifactLocation.uri` и `startLine >= 1`. Самотест подмен обновлён: прежняя
  подмена («обещан SARIF» = добавить флаг) стала бы no-op, поэтому теперь ломается ПЕРЕДАЧА
  `$sarif_arg` и ПРОВЕРКА НЕПУСТОТЫ.
- **#533 `make prove-all-real` = 27 проверок** (`OK 23 | SKIP 4 | FAIL 0`, было `OK 14 | SKIP 4`):
  Пакет В дополнен **нативными** доменными оракулами (`arbitrage-check` A10: 2 арбитража поймано,
  линейная комиссия доказана `trusted: 0`; `float-nan-check` A11: `trusted: 0 | holes: 0`),
  Пакет Г (`gen-tests-check`), Пакет Д (`mcp-audit-check` — ловля rug-pull/инъекции/невидимого
  Unicode; `mcp-selftest` — коды guardrail и RLVR), Пакет Е (`kimg-cli-check`, `kimg-grep-check`,
  `c-abi-threads`, `wasm-check`).
- **#534 (`tools/prove_all_capabilities_real.py`)**: `.venv/bin` ставится **в конец** `PATH`.
  ИЗМЕРЕНО: в начале он подсовывал `pip-ziglang 0.13` вместо Zig 0.17 — и стенд выдавал **два
  ложных FAIL** (`kimg-grep-check`, `wasm-check`) при полностью верном коде (тот же корень, что #509).


### Added — нативный `verify-zig` судит боевой код, доменные эксплойты с живыми судьями (#530–#531)

- **#530 (`src/verifier/zig_ast_verify.zig`)**: нативный фронтенд (`std.zig.Ast`, 0 % Python) научился
  тому, что питоновский умел давно: сворачиванию раннего выхода `if (c) return A; return B;` ->
  `(ite c A B)` (цепочкой), инлайну локальных `const x = …;`, разгруппировке `( … )` и разбору
  условия `if` (сравнения + `and`/`or`). ИЗМЕРЕНО на боевых файлах: `audits/tigerbeetle/div_ceil.zig`
  -> `[PASS] ДОКАЗАНО` (4 обязательства: безопасность + постусловие), `audits/ghostty/grid_columns.zig`
  -> `[PASS] ДОКАЗАНО` (2), а обе мутации — `КОНТРАКТ НАРУШЕН` (переполнение / постусловие).
  До правки оба файла давали `SKIP «нужен РОВНО ОДИН return»`.
- **#531 (`tools/kern_contracts.py`)**: `--diff-equiv` на Python-входе больше не пишет ложное
  «нет одноимённых функций в подмножестве», когда функции НАЙДЕНЫ, но их тела вне подмножества:
  теперь называется причина (`fee: нелинейное умножение` — QF_NIA вне QF_LIA). Класс #361/#370,
  но для Python-ветки (в C-ветке причина называлась с #361).
- **`make prove-all-real`** (`tools/prove_all_capabilities_real.py`) вырос до **18 проверок**
  (`OK 14 | SKIP 4 | FAIL 0`, было `OK 6 | SKIP 7`), и все SKIP — с названной причиной:
  - Пакет А: `verify-zig` на боевых файлах с ДВУСТОРОННИМ контролем (верная -> ДОКАЗАНО,
    мутация -> НАРУШЕНО); `kernc lia` сверен с Z3 на двух системах (SAT/sat и UNSAT/unsat).
  - Пакет Б: три ФИЗИЧЕСКИХ оракула вызываются через свои цели (`oracle-string-check` — канарейка
    вне корня на реальной ФС, `oracle-noninterference-check` — живой тайминг CT_RATIO=1.00 против
    EE_RATIO=66.89, `oracle-chc-check` — 3 `sat` + 4 `unsat` против реального исполнения цикла)
    + ReDoS с живым секундомером (`re.fullmatch`, а не `match`).
  - Пакет В (новый): `SQL/RLS` — KERN `DIVERGED` (tenant=2, role=1) И живой `sqlite3` отдаёт
    2 строки вместо 1; `AMM` dust-эксплойт — 10 000 сделок по 1: комиссия 0 против 10 000;
    `IEEE-754 NaN` — пробивает гард `!(x > MAX || x < 0)` в **python, node и gcc** одновременно.
  - Честные границы названы, а не замазаны: нелинейная арифметика (`QF_NIA`) и `float/NaN`
    вне модели KERN — «доказано» там НЕ заявляется.


### Real-combat stand for the «sleeping» capabilities: native Zig frontend, LIA, six physical oracles

Everything proven on real corpora so far was `--xray` and `--delta`. The remaining muscles were
exercised only on toy fixtures. `make prove-all-real` (`tools/prove_all_capabilities_real.py`) now
drives them on REAL files and REAL vulnerable patterns and prints an HONEST verdict per item —
`OK` (worked and confirmed by an external oracle), `SKIP` (named reason) or `FAIL`. It never rewrites
a verdict: a SKIP stays a SKIP.

**Measured on this machine (13 checks: OK 6 | SKIP 7 | FAIL 0):**

- **Native Zig frontend, 0 Python (`verify-zig`)** on real files — `audits/tigerbeetle/div_ceil.zig`,
  `audits/ghostty/grid_columns.zig`, `audits/codecheck/zig_div.zig`, `src/core/eq2.zig`:
  the frontend PARSES the contracts but **SKIPs** with a named reason («тело вне подмножества:
  нужен РОВНО ОДИН `return`», «нет обязательств»). Honest result: on real code with several returns
  the capability exists but does not apply — recorded as SKIP, not as green.
- **LIA solver without Z3 (`kernc lia`)** on real inequality systems, cross-checked against Z3:
  `ceil_div(n>=0,d>0)` → `SAT` / Z3 `sat`; contradiction (`x<=0 ∧ x>=1`) → **`UNSAT` / Z3 `unsat`**.
  Two independent solvers agree — that is the point of the check.
- **ReDoS oracle (CWE-1333) with a LIVE stopwatch:** nested quantifier `(a+)+` → `ОПРОВЕРГНУТО`,
  and Python's `fullmatch` on `'a'*22+'b'` takes **0.305 s**; safe `(a|b)+` → `ДОКАЗАНО`, live
  **0.0 s**. (My first attempt used `match`, which found a prefix instantly and proved nothing —
  measured `match` = 0.0 s vs `fullmatch(22)` = 0.33 s vs `fullmatch(24)` = 1.12 s; the oracle was
  fixed to measure the same failure, not a different one.)
- **Abstract interpretation** `join 0 10 5 20` → `[0, 20]`, `widen` → `[0, MAX]` ✓.
- **DTMC** on a retry model (`dtmc reach 2 1 …`) → `P(достичь 1 из 0) = 1.000000` ✓.
- **Named SKIPs found on the way (this is the value of the stand):** `strings`/path-sandbox — theory
  not exposed under that name in `theory_cli`; `nonint` — unknown instruction `early_return`;
  `chc` — needs `<init> <step> <bound> <свойство>`. Each is a REAL usability gap, now visible instead
  of hidden behind «all capabilities proven».

### T7 closed: external acceptance in ONE command, and the best proofs moved onto the front page

The engineering core was finished but invisible: the strongest results sat in small print inside
`docs/evidence/*.log`, and the only person who had ever reproduced them was the author (Bus factor 1).

- **`make external-accept`** (`tools/external_accept.sh`) — one command for a sceptic: takes the
  PUBLISHED archive (or downloads it with `curl -4`), verifies the external and internal SHA-256,
  checks ISA portability (`zmm == 0` in `kernc`), verifies the Ed25519 attestation with the EXTERNAL
  key, then runs eight proofs on the appliance itself in an isolated directory. Receipt:
  `docs/evidence/external_accept_v2.8.2.log`. MEASURED on the archive downloaded from GitHub
  Releases: **все проверки пройдены, rc=0**.
- **The script immediately caught a wrong test of mine:** step 7 first asserted «without a solver the
  appliance refuses» while running the appliance that SHIPS `z3` next to it — so no refusal could
  happen. It was rewritten to copy the appliance WITHOUT `.venv/bin/z3`; measured: `rc=2` and
  `KERNA DOCTOR` in the message. A gate that cannot fail is not a gate.
- **`docs/PROOF_GALLERY.md` / `.ru.md`** — eight capabilities, each with ONE command, its EXTERNAL
  oracle and the receipt, plus the whole-corpus blind exam table (942 files / 2 004 functions /
  35 findings / 0 false / precision 1.00) and its honest boundary (the cap is on the slice).
- **`docs/REAL_BUGS_FOUND.md`** gained **Case D**: the live ordering defect in `tigerbeetle`
  `test_conformance.py` (`transfers_1[0]` on line 6169, guard `assert len(...) == 1` on line 6170)
  with a ready 2-line upstream patch — the finding stays a TP instead of being silenced for a
  prettier zero.
- **README.md / README.ru.md / docs/index.html** now lead with those tables instead of hiding them;
  `docs/README.md` (the map) links both new documents, so `make docs-map-check` stays honest.
- **CI: `curl -4` with a fallback** for the Lean bootstrapper (measured: `curl -6` cannot connect at
  all while `curl -4` returns 200 — that was the whole «504 storm»), kept in one place.

### #530: the real cause of the «504 storm» was a broken IPv6 path, not GitHub

- **MEASURED (diagnosis, source machine).** `example.com`/`google.com` → **200**, while every
  GitHub download hung. Root cause: **IPv6**. `curl -6 https://raw.githubusercontent.com/...` fails
  to CONNECT (11 ms), `curl -4` to the same URL → **200**; `github.com`/`api.github.com` resolve to
  IPv4, and `api.github.com` never answers on IPv4 (provider filtering) — which is why the REST API
  looked «dead» while the site and release assets were fine with `-4`.
  `elan-init.sh` calls `curl` WITHOUT `-4`, so it prefers the AAAA record and hangs — that is the
  whole «CDN storm». The v2.8.2 archive downloaded with `-4` **first try**.
- **Fix (cheap insurance, not a local crutch):** the CI Lean installer and the hint printed by
  `formal/setup_mathlib.sh` now use `curl -4`.
- **The connected bots are NOT the problem (checked in the repository):** `Release Drafter` drafts
  under the tag `next` (defect `#248` — a draft must not occupy the release tag name), and
  Dependabot holds two PRs: `#18` (`pytest 9.1.1 → 9.2.0`, harmless) and **`#20`
  (`z3-solver 5.3.1.0 → 5.3.3.0`)**. The second one must NOT be merged mechanically: the solver
  version is part of the evidence chain (`requirements.txt` says so), so every receipt
  (`audits`, `svcomp`, `proof-tamper`, `showcase-live-all`) has to be re-measured first.
- **Release verified as a client (finally):** `kerna-dist-v2.8.2.tar.gz` 25 223 076 B, external
  `sha256sum -c` → **ЦЕЛ**, internal sums (`kerna`, `server.json`, `kernc`) → **ЦЕЛ**,
  `./kerna --doctor` → OK, `zmm = 0` in `kernc`, `./kerna --delta` → `DIVERGED` with counterexample.

### #529 + T4c: the full corpus is now CLEAN — precision 35/35 = 1.00 on 942 files

- **`#529` — a BV verdict was untrustworthy when the body calls `exit`/`abort`.** Measured on
  `redis/src/memtest.c`: `if (*p != (unsigned long)p) { if (interactive) { exit(1); } return 1; } …
  if ((j & 0xffff) == 0 && interactive)` was reported `[DEAD BRANCH] (UNSAT, BV64)` although the
  branch is ALIVE (`j = 0, interactive = 1`). Minimal trigger found by subtraction (15 lines: with
  `exit` → 1 finding, without → 0): the nested block `if (interactive) { exit(1); }` is registered as
  a block WITH an exit, so `not interactive` lands in the BV path even though the position lies
  OUTSIDE that block. `exit`/`abort` are not modelled as control flow, therefore a BV verdict on such
  a body is unprovable — a NAMED skip. `memtest.c` 2 → **0**; the BV positive control
  (`if ((x&1)==0) { if ((x&2)==0) { if ((x&3)!=0) … } }`) still yields 1 (TP kept).
- **Re-classification, with the reason (not a cover-up):**
  `tigerbeetle/.../test_conformance.py` does `transfers_1[0]` on line 6169 while
  `assert len(transfers_1) == 1` stands on line **6170** — AFTER the use. With an empty reply that is
  a real `IndexError`, so it is a **TP**, not an FP. The finding stays; the label was wrong.
- **FULL CORPUS, final (942 files):** curl 1, redis 33, tigerbeetle 1 = **35 findings, 0 false
  → precision 1.00**. Classes: OVERFLOW 33, BOUNDS 2, CRASH 1, DEAD BRANCH 0.
- Recall unchanged: `xray-precision` OK (clean 0, dead_field 1, dedupe 1, buggy 5/5),
  `xray-overflow-check` OK, `svcomp_baseline` TPR 1.00 / FPR 0.00.

### #528: Lean moved to its own CI job so a CDN storm cannot redden the code circuit

- **MEASURED 2026-11-08.** GitHub's CDN was returning **HTTP 504** (the release assets of `v2.8.2`
  could not be downloaded, and `elan-init.sh` itself fails on `github.com/leanprover/elan/releases/
  latest/download/...tar.gz` with the same 504 — reproduced locally in a clean `HOME`). The Lean
  step died on second **17** and dragged the whole `verify` job red, including checks that have
  nothing to do with Lean.
- **Fix in two parts:** (1) `~/.elan` is cached by `hashFiles('lean-toolchain')` and the installer
  retries **5** times with `--retry 5 --retry-all-errors --retry-delay 10`; after the first
  successful run the external CDN is not needed at all. (2) Lean + Mathlib + `formal/check.sh` now
  live in a **separate job `formal-lean`**, so a network failure is visible by job name and does not
  block the code circuit.
- **Why the canfail case did not simply disappear (that would be vacuous):** `lean-sorry` drives
  `formal/check.sh`. `tools/canfail.py` gained an explicit `--skip <names>` which PRINTS
  `[SKIP-CONTOUR] <case> — гоняется в ДРУГОМ контуре`. `verify` runs
  `canfail --skip lean-sorry`, and `formal-lean` runs `canfail --only lean-sorry` — the case is still
  executed exactly once, in the circuit that owns the tool. Deleting it would have been the very
  class of dishonesty this project hunts.

### #526–#527: T4b — three more FP roots closed, the 0.90 threshold taken on the FULL corpus

The six false accusations named after T4 were attacked one by one, each with an 8-12 line repro
and a two-sided control:

- **`#526` — a local rewritten INSIDE a loop is not an invariant.** Measured:
  `tigerbeetle/src/vsr/marzullo.zig::smallest_interval` (`var count: i64 = 0;` then `count += 1`
  in a loop) reported `[DEAD BRANCH] (> 0 0)` — the model took the INITIAL value, although the loop
  changes it. Same in `replica.zig::on_prepare_timeout` (`(= (+ 0 1) 0)`). Fix: names assigned in a
  loop body (`for`/`while`/`do`) are collected and such a condition is not called dead.
- **`#526b` — a condition that collapsed into CONSTANTS.** `(> 0 0)` has no names at all: that is
  the signature of a substitution we could not justify. A real dead branch compares NAMES; comparing
  two literals is almost always an artefact — so it is a NAMED skip.
- **`#527` — «field» vs «field written with a dot».** The #524 guard checked whether the name from
  the condition (`server__current_client`, our `base__field` notation) occurs in the body — but the
  body says `server.current_client` (with a dot), so the check never fired. Also the function's OWN
  signature was counted as a «call», which made the guard fire on files where no call exists. Both
  fixed: the base name is compared, and the function's own name is excluded from the call list.
  Measured: `redis/src/server.c` 1 → **0**; the reverse control
  `precision_dead_field/dead_after_kind.c` stays at **1** (a REAL dead branch), `field_guard_write.c`
  stays **0**.
- Gates after the fixes: `xray-precision` OK (clean 0, dead_field 1, dedupe 1, buggy 5/5),
  `xray-overflow-check` OK, `svcomp_baseline` TPR 1.00 / FPR 0.00.
- **CI hardened against CDN storms** (measured 2026-11-08: the Lean step died on second 17 while
  release assets returned HTTP 504): `~/.elan` is now cached by `hashFiles('lean-toolchain')` and the
  installer retries three times with `--retry 5 --retry-all-errors`. Deliberately NOT split into a
  separate job: the canfail case `lean-sorry` drives `formal/check.sh`, and removing Lean from
  `verify` would make that case vacuous — the exact class of dishonesty this project hunts.

### #525 + the honest T4 result: full corpus measured, threshold NOT met (0.85)

The blind measurement now covers the WHOLE corpus (`curl/lib` 377 + `redis/src` 227 +
`tigerbeetle/src` 338 = **942 files, 2942 functions checked**). Six false-accusation roots were
found and closed (`#520`–`#525`); the remaining result is recorded AS MEASURED:

- **`#525`** — a condition depending on a value we did NOT derive (`client_id` captured from a
  `switch` arm, `ok` from a map lookup) can never be «unreachable» for us. Measured on
  `tigerbeetle/src/message_bus.zig::recv_update_peer` and `clients/go/assert/assert.go::isObjectEqual`
  (2 FP). First version of the rule was TOO WIDE and cut coverage of `curl/lib` from 727 checked
  functions to 184 — measured and narrowed (a locally assigned variable counts as known, and names
  that are struct fields in our `base__field` notation are excluded, otherwise the reverse control
  `precision_dead_field/dead_after_kind.c` lost its REAL dead branch).
- **T4 RESULT (measured, not claimed):** 40 findings, **6 proven FP → precision 0.85**; the 0.90
  threshold was **NOT** met on the full corpus. Progress vs the first full run: curl 4→1,
  redis 43→36, tigerbeetle 9→3. Remaining FP are named per line in
  `docs/evidence/blind_p1_2026-11-07.log`: redis `memtest.c` ×2 (BV path), redis `server.c`
  (interprocedural field mutation), tigerbeetle `marzullo.zig`/`replica.zig` (a local rewritten
  inside a LOOP), one Python test file. That set is task **T4b** in `docs/PLAN_NEXT.*`.
- Gates after the fixes: `xray-precision` OK (clean 0, dead_field 1, dedupe 1, buggy 5/5),
  `xray-overflow-check` OK, `svcomp_baseline` TPR 1.00 / FPR 0.00, `kerna-check` R1–R9 OK.

### #523–#524: the same T4 run on the whole `redis/src` — two more FP roots (assert-guard, field/rewritten value)

- **#523 — a project's OWN ASSERT is a guard, and we ignored it.** Measured on
  `redis/src/iothread.c`: `serverAssert(start >= 1 && end < server.io_threads_num && start <= end);`
  followed by `for (i = start; i <= end; i++) io_threads[i]…`. `end` is PROVEN smaller than the
  array length by that assert, so `i <= end` is correct — yet we reported 3 × `[BOUNDS PATH]
  off-by-one` (iothread.c ×2, t_hash.c ×1). Fix: `assert`-like calls (`serverAssert`,
  `serverAssertWithInfo`, `Assert`, `ASSERT`, `redisAssert`, `bug_on`) are read as path guards —
  but only arguments that are COMPARISONS/logic (the first argument of `serverAssertWithInfo` is a
  client, and pushing it into the path would be an invention). Second half: `end` was listed among
  «length» names, although in C `end` is usually the LAST index (`hashTypeTryConversion(…, 2, 3)`);
  only `len|length|size` are treated as lengths now. Measured after: `iothread.c` 3 → **0**,
  `t_hash.c` 1 → **0**; control `for(i=0;i<=len;i++) buf[i]=0;` still **1** (TP kept).
- **#524 — «dead branch» on a struct field or on a value the body rewrites.** Measured on
  `redis/src/server.c::processCommand` (`server.current_client == NULL` — and the code itself sets
  it to `NULL` at line 3103) and `t_stream.c::streamValidateListpackIntegrity`
  (`!valid_record` after `lpGetIntegerIfValid(p, &valid_record)` — the value is written through a
  pointer). Both were declared `[DEAD BRANCH] … UNSAT`. The value is set by code we do not model,
  so «unreachable» is UNPROVABLE here. Fix: a named skip when the condition depends on a struct
  field (`->`/`.`) or on a name the body rewrites (assignment or `&name`).
- Recall re-measured after both: `make xray-precision` OK, `make xray-overflow-check` OK,
  `svcomp_baseline.py` → **TPR 1.00 / FPR 0.00**.

### #520–#522: T4 on the FULL corpus — three false-accusation roots found and closed

The blind measurement was extended from a 60-file slice to the WHOLE corpus
(`curl/lib` 377 files, `redis/src` 227, `tigerbeetle/src` 285 — 889 files). The first full run of
`curl/lib` produced **4 findings on 377 files**; line-by-line triage against the sources showed
**3 false accusations** and 1 «UB in the signature domain». Each was minimised to an 8–12 line
repro before any edit (the project's rule).

- **#521 — compound assignment was NOT modelled, yet the accusation stood.**
  Measured: `int f(int x){ x %= 64; return 100 - x; }` → `findings 1`, `skipped 0`. `_exec_clike`
  raised `Unsupported` for `x %= 64`, and `local_smt` (the model used by the overflow detector) is
  built only from DECLARATIONS — so `x` stayed a free input, Z3 chose a value `%=` rules out, and
  `curl_sha512_256.c::Curl_rotr64` (`bits %= 64;`) was accused with counterexample
  `bits = -2147483584`. Fix: `nm op= rhs` is applied to the model (`(op base rhs)`), only when the
  assignment occurs EXACTLY ONCE in the body (otherwise order/branches make the composition
  unsound). Measured after: `x %= 64` → 0 findings, `x += 1` → still 1 (TP kept, `INT_MAX + 1` is
  real UB), `curl_sha512_256.c` → **0**.
- **#520 — a struct FIELD as divisor was accused as a pointer.**
  `_RE_CLIKE_DIV` used the class `[\w.\[\]]`, which has no `->`, so the divisor
  `state->retry_max` was truncated to `state` and reported as «деление на ноль: `state == 0`»
  (measured on `curl/lib/tftp.c::tftp_set_timeouts`, where the field is bounded to `[3,50]` in the
  body). Fix: the name pattern now includes `->`/`.`; a divisor that is a struct field is a NAMED
  skip (its value is set by code we do not model). Measured after: `tftp.c` → **0**;
  `int g(int a,int b){ return a / b; }` → still accused (TP kept).
- **#522 — `break`/`continue`/`goto` were not modelled, so a live branch was called dead.**
  Measured (12-line repro from `curl/lib/progress.c::max6out`): with
  `do { nbytes = bytes/1024; if(nbytes < 1000) break; bytes = nbytes; } while(0); if(nbytes <= 99) …`
  the last branch was declared `[DEAD BRANCH] … UNSAT`, although `bytes = 100000` gives
  `nbytes = 97`. Cause: `break` left the NEGATION of its condition on the path («we left the loop
  because the condition is false»). Fix: with `break`/`continue`/`goto` in the body a dead branch is
  NOT claimed — a named skip. Measured after: the repro → 0; the positive control
  `tests/fixtures/xray_true_dead.c` → still `[DEAD BRANCH] truly_dead` (TP kept).
- **Recall NOT damaged (measured):** `make xray-precision` OK, `make xray-overflow-check` OK,
  `svcomp_baseline.py` → **TPR 1.00 / FPR 0.00** (unchanged), and every repro above keeps its
  two-sided control.

### #519: `--live` in the appliance — accepted, but NAMED as not applied (T3, closed by behaviour)

- **MEASURED:** `dist/kerna --delta base head --live` used to say nothing specific about `--live`;
  the request was silently answered by the Z3 layer only. The JSON field `semantic_live` said
  `true` — a promise, not a fact (class `#370`).
- **Fix:** the frozen binary now prints, on `--live` specifically, «`--live`: в АВТОНОМНОМ апплаенсе
  динамическое исполнение чужого кода недоступно (изоляция `_MEIPASS`, отдельного `.py` нет).
  Работает математический Z3-слой `--diff-equiv`…» and the JSON gained
  **`semantic_live_applied`** (`false` in the archive, `true` only when the live layer really ran).
- **Proven by BEHAVIOUR, not by text:** new rule **R9** in `make kerna-check` runs the packaged
  binary with `--live` and requires a line that mentions `--live` AND names it unavailable — the
  general import-time notice no longer counts (otherwise the check would be vacuous, class `#514`).
  Measured: `[OK] R9: --live в апплаенсе назван недоступным`, `kerna-check` R1–R9, провалов 0.
- The same boundary is written into `README-RUN.txt` (generated) and `docs/LIMITS.*` §6. No code
  execution was added to the archive on purpose: a static analyzer must not run a stranger's code
  without an explicit decision (the `#508` rule).

### #518: on a REAL PR the gate said «tool error» where the solver honestly said «cannot decide»

- **MEASURED (T5 of the plan) on a real redis bugfix** `0e618fa` «Fix NULL deref in
  `usUntilEarliestTimer` when all time events are deleted (#15391)»: the patch adds
  `if (earliest == NULL) return -1;` to `src/ae.c`. Replayed as a PR (`BASE = 0e618fa~1`,
  `HEAD = 0e618fa`) through the packaged appliance:
  `[!] ПОВЕДЕНЧЕСКОЕ СРАВНЕНИЕ НЕ ВЫПОЛНЕНО … src/ae.c: rc=2 исполнитель вернул код 2 без вердикта`.
- **Root:** `--diff-equiv` returns `rc=2` BOTH when the tool is broken AND when it honestly
  answers `[UNKNOWN]` (Belnap N — here the function body has a loop). After `#513` (fail-closed on
  tool errors) both cases were reported as a refusal, i.e. a truthful N was being passed off as a
  tool failure — the same class of dishonesty, only in the other direction.
- **Fix:** `audit_delta` parses the executor's own summary — `ошибок инструмента K` vs
  `недоказуемых M`. K>0 (or `[TOOL_ERROR]`) → refusal `rc=2`; M>0 only → a new bucket
  (`semantic.undecided`), printed as «НЕ РЕШЕНО (Belnap N) … это НЕ „поведение то же“».
- **MEASURED AFTER, both directions** (`buggy → fixed` and `fixed → buggy`): `rc=0` and the line
  «НЕ РЕШЕНО (Belnap N) для 1 файл(ов) — это НЕ „поведение то же“». Honest boundary of this tack:
  a NULL dereference is outside the detector vocabulary (`CRASH PATH` = division by zero), so the
  gate does not block — and it does not pretend that the behaviour is unchanged either.
  `audit-delta --selftest` grew to **14 OK** (two new checks: N is not a tool error; a real tool
  error stays an error).

### #517: `--delta` said «no divergence» for paths that DO NOT EXIST

- **MEASURED (found while verifying `#516` on the packaged appliance, after `/tmp/dt` was cleaned up):**
  `./kerna --delta /nope_base /nope_head` printed «поведенческая дельта: изменившихся файлов 0» and
  «поведение общих изменившихся файлов НЕ разошлось» with **rc=0**. The same for two FILES instead of
  directories. The report asserted «no divergence» where no comparison had happened — class `#499`
  again, and a worse variant: it also makes a mis-typed path in CI look like a clean PR.
- **Fix:** `_validate_dirs()` runs BEFORE any analysis: a missing path and a non-directory are both
  named refusals with `rc=2`, and the message points to `--diff-equiv` for a single file pair.
- **MEASURED AFTER** (packaged archive): real pair → `DIVERGED`; `/nope_base` → `rc=2` «путь НЕ
  СУЩЕСТВУЕТ»; file instead of dir → `rc=2` «это НЕ каталог». `audit-delta --selftest` grew from 9
  to **12 OK** (three two-sided checks: missing path refused, file refused, real dirs accepted).

### #516: the appliance promised a layer it does not have (T3 of the plan)

- **MEASURED on the PUBLISHED archive** (`dist-release/kerna-dist-v2.8.2/kerna --delta`): the first
  line said «поведенческая дельта пойдёт **сеточной пробой**». In the frozen binary there is no grid
  probe — it is a separate `.py`, and `_live_probe()` returns `None` by design. The message promised
  a fallback that does not exist (class `#370`: the report says something other than what happened).
  What actually worked was the **Z3 layer** (`--diff-equiv` dispatched by the binary itself), and it
  did produce `DIVERGED` with a counterexample.
- **Fix:** in frozen mode `tools/audit_delta.py` now names the truth: «живой слой и сеточная проба
  НЕДОСТУПНЫ в упакованном бинаре — работает Z3-слой `--diff-equiv` … Это НАЗВАННЫЙ пропуск, а не
  „поведение то же“». The same boundary is written into `README-RUN.txt` (generated by
  `tools/make_kerna_dist.sh`) and into `docs/LIMITS.md` / `.ru.md` §6 with the reproduction command.
- No layer was added and no capability was claimed: the archive is one self-contained file, and the
  layers that need a separate Python file are named as absent instead of promised.

### #515: the QF_S refusal named the COUNT but not the RULE — now it names the theory boundary

- **MEASURED** (`make proof-tamper`, `KERN_DEBUG_TRUSTED=1`). The QF_S bank is a named skip because
  the checker refuses the INTACT proof (`rc=1` on a correct proof) — fail-closed, correct. But the
  reason was truncated at 160 characters and ended on «ОТВЕРГНУТО: ос…», so the report said
  «refused» WITHOUT saying why. The rule was in the output all along:
  `[i] первое непроверенное правило: th-lemma (структурно) (1 шт.)`.
- **Root:** the `prove` path printed that line (`src/main.zig:582`), the `check-proof` path did not —
  one and the same fact was reported differently in two paths (class `#370`). And
  `tools/proof_tamper_check.py` cut the reason to 160 chars, discarding the tail that holds it.
- **Fix:** `src/main.zig` prints the first untrusted rule in `check-proof` as well;
  `tools/proof_tamper_check.py` extracts `первое непроверенное правило: …` and puts it FIRST in the
  reason. Measured after: reason = `ДОВЕРЕННЫХ 1 | первое правило: th-lemma (структурно) :: …`.
- **BOUNDARY NAMED, NOT HIDDEN.** The exact trusted step is
  `((_ th-lemma seq) @x78 (unit-resolution (def-axiom (or $x91 $x57)) @x312 $x57) false)` — the
  STRING theory (`str.++`, `seq.unit`, `(_ Char …)`) inside `th-lemma`, i.e. not a cheap structural
  rewrite. Written into `docs/LIMITS.md` / `.ru.md` (section 2) with the dump and the reproduction
  command. `make proof-tamper` stays rc=0: `ПОДДЕЛОК 35 | ПРИНЯТО 0`, four banks adversarially
  verified, QF_S a named skip.

### #514: `KERN CI` был красным всю сессию — один кейс `canfail` ослеп (`kerna`)

- **НАЙДЕНО ПО ВАШЕМУ ЛОГУ, ПОДТВЕРЖДЕНО ЗАМЕРОМ.** Полный прогон `tools/canfail.py`
  в CI заканчивался `ИТОГ: … ВАКУУМНЫХ 2` и падал. Проверка истории прогонов показала:
  `KERN CI` красный **на всех** коммитах сессии (`4f557f37 … 6b13fa7a`), то есть это не
  регресс последних правок, а **давняя слепая проверка**, которую я не видел, потому что
  гонял только `ci-fast` (быстрый набор). Это моя ошибка отчётности, не «мелочь».
- **КЕЙС `kerna` (первый из двух).** Он ломает доктора (`kerna_doctor` перестаёт
  отказывать) и ждёт, что `make kerna-check` покраснеет на R4. Замер: цель **зелёная**
  (`ВАКУУМНА: поломка внесена, а цель осталась ЗЕЛЁНОЙ`).
  **Причина — defense-in-depth:** после `#499a` отказ «нет решателя» дают ДВЕ
  независимые преграды — доктор и ворота решателя внутри анализа. R4 требует лишь
  «rc=2 + названная причина», поэтому его удовлетворяет любая из них; сняв доктора,
  кейс ничего не менял. Измерено вручную: без `z3` и `./kerna --doctor`, и
  `./kerna --xray` дают `rc=2` с текстом `KERNA DOCTOR`.
  **Лечение (не ослабление, а уточнение предмета):** в `kerna-check` добавлено правило
  **R8** — в пути АНАЛИЗА отказ обязан быть **докторским** (`KERNA DOCTOR`) и до разбора
  кода; плюс `_no_solver_env()` (PATH урезан до `/usr/bin:/bin`, `$Z3`/`$KERN_Z3` сняты),
  иначе локальный `.venv/bin` в PATH молча возвращал решатель и обессмысливал проверку.
  ИЗМЕРЕНО ДО: `--only kerna` → `ВАКУУМНЫХ 1`. ПОСЛЕ: → `[PASS] kerna … за 34 с`,
  `ИТОГ: не-вакуумных 1 | ВАКУУМНЫХ 0`.
- **ВТОРАЯ ГРАНЬ ТОГО ЖЕ КЕЙСА — В CI ОН БЫЛ ЗЕЛЁНЫМ ПО ПОСТРОЕНИЮ.**
  `PyInstaller` отсутствовал в `requirements.txt`, поэтому в CI (`pip install -r
  requirements.txt`) `make kerna-check` печатал `[SKIP] PyInstaller не установлен —
  УПАКОВКА НЕ ПРОВЕРЕНА` и выходил **0**. Гейт, который НЕ МОГ проверить упаковку,
  рапортовал успех — и кейс `kerna` не мог покраснеть ни при какой поломке.
  Лечение: `pyinstaller>=6.0` в `requirements.txt` (одна команда установки теперь
  ставит и его) **и** отказ вместо пропуска: без PyInstaller `kerna-check` возвращает
  `rc=2` с названной причиной и командой установки; осознанный пропуск — только
  `KERNA_ALLOW_SKIP=1` (тогда печатается `[SKIP]` и это ЯВНОЕ решение, а не тишина).
- **ВТОРОЙ КЕЙС — `xray-nested-branch` (`#401`), и виноват ЧЕСТНЫЙ ПРЕДОХРАНИТЕЛЬ.**
  CI назвал его сам (аннотация `canfail ВАКУУМНЫЙ кейс xray-nested-branch`).
  Замер локально: со снятой областью ветви гейт печатал `[OK] #401` и **НОЛЬ**
  ложных `[DEAD BRANCH]` — то есть кейс не проверял ничего.
  Причина: фикстура `xray_nested_branches.c` целиком лежит внутри `switch`, а
  **`#503`** (закрыт в этой же сессии) НАМЕРЕННО гасит вердикт «мёртвая ветвь»
  внутри `switch` с ≥2 `case`, потому что `switch` не моделируется и вердикт там
  был бы недоказанным. Один честный предохранитель заглушил доказательство другого.
  Лечение: вторая фикстура **`tests/fixtures/xray_nested_branches_if.c`** (тот же
  класс ошибки, **без** `switch`) и проверка в `tools/xray_check.sh`.
  ИЗМЕРЕНО: с саботажем она даёт `[DEAD BRANCH] nested_branches_if: … (< v 160)` —
  ЛОЖНОЕ обвинение корректного кода (значит гейт краснеет); на здоровом дереве
  `bash tools/xray_check.sh` → **rc=0**, находок 0.
  `--only xray-nested-branch`: ДО → `ВАКУУМНЫХ 1`, ПОСЛЕ → `[PASS]`.
- **ОБА ЗАКРЫТЫ:** `--only kerna` → `[PASS]`, `--only xray-nested-branch` → `[PASS]`,
  `canfail --selftest` → `САМОПРОВЕРКА ХАРНЕССА: ПРОЙДЕНА`, `--check-anchors` →
  «якоря применимы: 205».
- **ЧТОБЫ ТАКОЕ НЕ ПОВТОРЯЛОСЬ:** имена вакуумных кейсов теперь печатаются
  `::error`-аннотациями (видны без логов и токена) — именно так оба имени и были
  получены; сводка прогона без этого скрывала их в 900 строках вывода.

### #513: `--delta` в опубликованном архиве больше не «тихий зелёный» (причина найдена замером)

- **ЗАМЕР НА ОПУБЛИКОВАННОМ v2.8.2 (скачан из GitHub Releases, не локальная сборка).**
  Один и тот же вызов, две разные правды:
  * `./kerna --diff-equiv base.py head.py` → `[TOOL_ERROR] f: код -4` и
    `ошибок инструмента 1`, `rc=2` (то есть инструмент ЧЕСТНО сказал «не смог»);
  * `./kerna --delta base/ head/` → «поведение общих изменившихся файлов **НЕ разошлось**»,
    `rc=0`.
  Класс `#499` (ровно то, ради чего писан `#407`): отказ инструмента выглядел как успех.
- **КОРЕНЬ 1 — артефакт не переносим по ISA.** `kernc` в CI собирался под процессор
  раннера: `objdump` показал **165 инструкций AVX-512 (`zmm`)** против **0** у локальной
  сборки, а здесь Intel i7-7700 (AVX-512 нет) → **SIGILL, rc=132**, отсюда «код -4» в
  отчёте `--diff-equiv`. Клиент на старом CPU получил бы то же самое.
  Лечение: `-Dcpu=baseline` (Makefile `build`, `release.yml`), `cpu_model = .baseline`
  у musl-таргета в `build.zig`, и **машинный гейт в `make_kerna_dist.sh`**: архив с
  AVX-512 в `kernc` не собирается (`exit 3`), при отсутствии `objdump` — названный пропуск.
- **КОРЕНЬ 2 — код возврата выбрасывался.** В `tools/audit_delta.py` стояло
  `_rc, out = _run_diff_equiv(...)`: `_rc` не использовался, а падение подпроцесса
  дописывалось в `diverged` как «расхождение». Теперь нет вердикта + ненулевой код (или
  `[TOOL_ERROR]`) = **названный отказ `rc=2`**, а строка «НЕ разошлось» в этом случае
  не печатается вовсе; в JSON появилось поле `semantic.tool_errors`.
- **КОРЕНЬ 3 — проверка мерила не то, что уезжает.** `kerna-check` гонял апплаенс с
  `PYTHONPATH=ROOT/tools`: при сбое собственных импортов Python подхватывал ИСХОДНИКИ из
  чекаута, поэтому R6 был зелёным, пока опубликованный архив молчал. Введён
  `_isolated_env()` (у клиента репозитория нет) — и добавлено правило **R7**:
  подменяем `kernc` заглушкой `exit 132`; `--delta` обязан дать `rc≠0` с `[!]`, а
  «НЕ разошлось» при этом — провал гейта.
- **ИЗМЕРЕНО ПОСЛЕ:** `audit-delta --selftest` → **9/9 OK** (новый кейс «отказ
  инструмента — НЕ эквивалентно»: ошибок 1, расхождений 0); тот же вызов с исполнителем,
  который падает по SIGILL (архив v2.8.2 как `KERN_AUDIT_BIN`) → **rc=2** и
  `[!] ПОВЕДЕНЧЕСКОЕ СРАВНЕНИЕ НЕ ВЫПОЛНЕНО`, вместо прежнего `rc=0`;
  `kernc` пересобран с `baseline` (`zmm=0`) — `make kerna-check` → **R1–R7 OK, провалов 0**;
  новый архив `kerna-dist-v2.8.2.tar.gz` (`bbdfe91c15d1765c…`, 27 664 842 Б) на реальной
  паре → `СЕМАНТИЧЕСКОЕ РАСХОЖДЕНИЕ (DIVERGED)` с контрпримером
  `b = 1, res_old = 0, a = -1, res_new = -2`; `make action-check REAL=1` → **5/5** уже
  через `./kerna --delta` (Action снова на самодостаточном апплаенсе).
  `action-check --selftest` поймал устаревший якорь подмены (`обещан SARIF → вакуум`) —
  якорь обновлён, а не ослаблен (класс `#113`).

### #510 + #511: витрина `33/33` и `--delta` ВШИТ В БИНАРЬ `kerna`

- **#510 — `F4 proof-tamper`: НАЗВАННЫЙ ПРОПУСК вместо ложного красного.** Дамп
  (`KERN_DEBUG_TRUSTED=1`) назвал точную причину: чекер отказывает на ЦЕЛОМ выводе QF_S, потому что
  шаг `(_ th-lemma seq)` не имеет проверяющего правила (`[dbg-trusted] th-lemma (структурно) … false`,
  `trusted=1`). Это **fail-closed**, а не дыра: на такой теории подделка неотличима от верного
  вывода, поэтому фаззер там НЕПРИМЕНИМ. Теперь случай печатается как `[SKIP]` с причиной, а
  инвариант гейта стал ТЕОРИЙ-НЕЗАВИСИМЫМ: `ПОДДЕЛОК ВСЕГО: 35 | ПРИНЯТО: 0` (маркер витрины
  больше не требует «40», которого в этом окружении не бывает).
  ИЗМЕРЕНО: `make showcase-live-all` -> **33 строки, 0 провалов (33/33)**.
- **#511 — `./kerna --delta BASE HEAD`.** Клиент, скачавший ТОЛЬКО архив, теперь может спросить
  «что стало хуже в этом изменении» без чекаута репозитория и без `pip install`:
  `tools/kerna_main.py` получил режим `--delta`/`--delta-json` (доктор -> вшитый `audit_delta`),
  `build_kerna.sh` — `--hidden-import audit_delta`; `action.yml` вызывает АППЛАЕНС
  (`"$KERNA_APP/kerna" --delta …`) вместо python-скрипта, плюс новый вход `block-on-diverged`;
  подставной апплаенс в `make action-check` получил тот же контракт `--delta` с `--json`.
  ИЗМЕРЕНО: `./kerna --delta` из `dist-release/…/kerna` -> `СЕМАНТИЧЕСКОЕ РАСХОЖДЕНИЕ (DIVERGED)`
  с контрпримером `b = 1, res_old = 0, a = -1, res_new = -2`; `make kerna-check` -> **R1–R6 OK,
  провалов 0** (новый R6 требует, чтобы `--delta` называл расхождение, с `z3` и `kernc` рядом);
  `action-check REAL=1` -> 5/5 на пересобранном архиве `03392c0dc3cd61d4…`.

### #509: Zig 0.13 из `.venv/bin` больше не перекрывает Zig 0.17 (витрина 16 -> 1 красная)

- **ДЕФЕКТ (измерен витриной).** `make showcase-live-all` давал **33 строки / 16 красных**. Причина
  одна и названная самим гейтом: `.venv/bin` добавляется в PATH ради `z3`, а лежащий там
  pip-пакет `ziglang` 0.13 перекрывает системный Zig 0.17 — и `zig-guard` законно отказывает.
  Замеры: (1) системный python без venv — 16 красных; (2) `PYTHON` из venv, но `.venv/bin`
  РАНЬШЕ Zig — 16; (3) Zig первым — 1.
- **ЛЕЧЕНИЕ (в двух местах, оба — «убрать перекрытие», а не «ослабить гейт»):**
  * `tools/zig_pick.sh` — выбирает ПЕРВЫЙ `zig` вне `.venv`; `Makefile` пинует его в `ZIG`
    (единый источник для ВСЕХ целей), с прежним честным отказом #392, если 0.17 нет;
  * Python-инструменты, которые лепили `.venv/bin` В НАЧАЛО (`conformance_check.py`,
    `anti_self_deception_check.py`, `smtlib_proof_check.py`), теперь ставят его В КОНЕЦ, а
    `conformance_check.zig()` — как `zig_pick` — берёт первый `zig` вне `.venv`.
- **ИЗМЕРЕНО ПОСЛЕ:** при «вредном» порядке (`.venv/bin` ПЕРВЫМ) `zig-guard` → rc=0;
  `make conformance-check` → «CONFORMANCE PASSED, 12 разделов, 95 проверок, 0 провалов»;
  витрина: **33 строки, 1 красная** (было 16).
- **ОСТАВШАЯСЯ КРАСНАЯ — `F4 proof-tamper`, и это НЕ косметика.** Дамп показал: чекер
  ОТВЕРГАЕТ даже НЕПОВРЕЖДЁННЫЙ вывод **QF_S** (`str.++`/`seq.unit`/`(_ Char 115)`, `[dbg-let]
  ?x-связка`), поэтому фаззер подделок неприменим, а на оставшихся теориях `ПОДДЕЛОК 35 |
  ПРИНЯТО 1` — принятая «подделка» приходится на вход, где НЕ ПРОШЁЛ контроль. Это граница
  модели строк при Z3 5.3.1, а не «простая перепись», и она записана как НАЗВАННЫЙ отказ, а не
  спрятана.

### #508: `audit-delta` получил ГЛАЗА — поведенческая дельта (на QuixBugs 40 из 42)

- **ДЕФЕКТ, НАЙДЕННЫЙ ТРИАЖЕМ.** Дельта аудита сравнивала только корзины `--xray` и на 42
  изменённых файлах QuixBugs писала «изменений в находках нет» — ВЕРНО про краши и ЛОЖНО про
  смысл: баги QuixBugs логические (`return a + b` вместо `a - b`), а `--xray` ищет краши/UB/
  границы/ветви. ИЗМЕРЕНО: `quixbugs_diff_check` на этих же парах даёт
  **DIVERGED 40 / EQUIVALENT 0**, то есть движок в руке был, но в дельту не подключён.
- **СДЕЛАНО.** `tools/audit_delta.py` получил поведенческую половину: для ОБЩИХ файлов с
  РАЗЛИЧАЮЩИМСЯ содержимым (идентичные байты сравнивать нечего) запускается семантическая
  проверка `--diff-equiv` (Z3 по телам, все языки) и — по флагу `--live` — ПЕРЕИСПОЛЬЗУЕТСЯ
  готовый движок `quixbugs_check.stage2` (Z3-модель + ЖИВОЕ подтверждение на КОНКРЕТНЫХ
  аргументах, включая списки). Плюс своя сеточная проба `tools/sema_probe.py` как запасной слой.
- **ИЗМЕРЕНО после правки** (`--live`, 42 изменившихся файла): **40 расхождений** с аргументами
  (`wrap: {'text': '', 'cols': 1} buggy=[''] correct=[]`, `gcd: {'a': 0, 'b': 1}
  buggy=RecursionError correct=ok`, `to_base: (2, 2) buggy='10' correct='01'`). Без движка
  (только сетка int-ов) — 11: сетка слишком узкая, и это названо.
- **ПОЧЕМУ 40, А НЕ 42** — две пары вне подмножества движка; это названный предел, а не
  «эквивалентно».
- **БЛОКИРОВКА — ОТДЕЛЬНОЕ РЕШЕНИЕ.** `rc=1` по-прежнему означает НОВЫЕ находки `--xray`
  (регресс по безопасности); изменение поведения ВИДНО (блок + `semantic` в JSON) и блокирует
  только при `--block-on-diverged`, потому что «внёс баг» и «починил баг» без тестов неотличимы,
  а гейт, блокирующий любое изменение, запретил бы рефакторинг. Живой слой исполняет код из
  HEAD, поэтому по умолчанию ВЫКЛЮЧЕН (`--live`), а `make pilot-e2e-check` его включает явно.
- **ДВУСТОРОННИЙ КОНТРОЛЬ** в `audit-delta --selftest`: `a+b → a-b` обязан быть виден;
  идентичные файлы в разных корнях — расхождений 0.

### Полевые испытания v2.8.2: три испытания, 0 правок ядра, все 8 уровней на чужом коде

- **Испытание 1 — четыре репозитория DeepSeek РЕЛИЗНЫМ апплаенсом** (`kerna-dist-v2.8.2`,
  скачан из GitHub Releases, sha256 сверен): `DeepGEMM` 5081f851 (144 файла), `FlashMLA` 395cb3af
  (133), `DeepEP-Ascend` 4dfccac4 (80), `deepseek-harness` fcc0ad46 (6279, срез). ИТОГО
  **357 файлов CUDA/C++: находок класса УГРОЗА — 0**, стилевых `[SMELL]` 145 (в precision не
  входят), `[BOUNDS?]`/`[BOUNDS UNKNOWN]` 464 — это **N**, названы явно. `--anti-cheat` на
  реальном тесте пилота → «чисто, находок 0».
- **Испытание 2 — живой PR-реплей.** (а) ПОЛОЖИТЕЛЬНЫЙ на реальном C (6 пар CWE-близнецов):
  `good -> bad` → **rc=1**, «РЕГРЕСС — новых находок 2» с именами (`cwe193_bad.c [BOUNDS PATH]
  fill_bad`, `cwe570_bad.c [DEAD BRANCH] dead_bits_bad`); `bad -> good` → **rc=0**,
  «ИСПРАВЛЕНО — исчезло 2». (б) ОТРИЦАТЕЛЬНЫЙ, и он важнее: на **40 парах QuixBugs** и
  **3 реальных fix-коммитах DeepGEMM** (`5081f85`, `1fc9c66`, `78b6900`) `audit-delta` даёт
  «изменений нет» — и это ВЕРНО: те баги логические/про гонки и порядок, вне словаря детекторов;
  **ложных блокировок на 43 реальных диффах — 0**. (в) `--diff-equiv` на РЕАЛЬНОЙ функции
  пилота (`deep_ep/utils/math.py: ceil_div`) против `x // y` → **[DIVERGED]** с контрпримером
  `y=0, x=0, res_old=-1, res_new=0`; на циклах/рекурсии — честный `[UNKNOWN]`, не выдумка.
- **Испытание 3 — «Боевой пилот 8-в-1»**: `tools/pilot_e2e.sh` + `make pilot-e2e-check` —
  одна цепочка на одном реальном проекте (`docs/evidence/pilot_full_v2.8.2.log`): паспорт ABI
  (воронка сходится) → `--anti-cheat` на его тестах → `audit-delta` в обе стороны →
  `--diff-equiv` с контрпримером → контракт `@kern:` **ДОКАЗАНО** (e=1) + сертификат `.smt2` →
  `kernx build/status/packet` (`agent_packet.json`) → `.kimg` + `check-integrity` в окружении
  **`env -i PATH=""`** (ни Z3, ни Python) → `kernc.wasm` в `node` (28 проверок, 0 нарушений).
- **Полевой дефект (назван, НЕ исправлялся):** `kernx status <не-.kern>` паникует стектрейсом
  Zig вместо названного отказа (`FileNotFound` → stack trace) — класс #370: отказ обязан быть
  сообщением, а не паникой. Нужен отдельный такт с can-fail кейсом.
- Полные квитанции: `docs/evidence/field_trials_v2.8.2.log` (испытания 1–2) и
  `docs/evidence/pilot_full_v2.8.2.log` (испытание 3).

## [2.8.2] — 2026-11-07

Первый релиз, который **проверен на незнакомом коде** до публикации. Собранное:
двойное лицензирование AGPL-3.0-or-later + коммерческая (`#493`), автономный
апплаенс `kerna-dist` (**27 МБ**, `#494`/`#496`), машинный ABI `--xray-json`
(`#483`), дифференциальный аудит `audit-delta` (`#484`), паспорт аудита
`kern_scan` (`#489`), витрина `make tour` (`#492`), карта возможностей
(`#485`), честные `LIMITS` в каждом архиве (`#497`), `1597/1597` выживших
мутантов, **200/200 CHECK-целей** с `245` невакуумными кейсами `canfail`,
`action.yml`, работающий на релизном архиве (гейт `make action-check`).
Закрыты `#449`–`#501` включительно.

ГЛАВНОЕ ПРО ЭТОТ РЕЛИЗ — цифра, а не обещание: **слепой замер** на трёх
репозиториях, которых никогда не было в кэше (curl `155f6f76`, redis `5b69ba2c`,
tigerbeetle `68958eb7`), дал precision **0.375** (TP 3 / FP 5); после закрытия
корней `#500` (поле структуры как константа), `#501` (беззнаковый индекс) и
`#502` (двойной учёт одной находки) — **TP 4 / FP 0 = 1.00** на том же срезе,
при неизменном SV-COMP **TPR 1.00 / FPR 0.00**. Подробности и границы —
`docs/evidence/blind_p1_2026-11-07.log`.

### #501b + #502 + #503 + #504: расширенный срез 60 файлов — **FP = 0 на 2160 функциях**

- **#501b — ТИП ИНДЕКСА НЕИЗВЕСТЕН.** `curl/lib/curl_gethostname.c`: параметр объявлен МАКРО-ТИПОМ
  (`GETHOSTNAME_TYPE_ARG2 namelen`, раскрывается в `int` ИЛИ `size_t`), парсер его не знает — и имя
  молча становилось «знаковым»: `namelen - 1` обвинялось как отрицательный индекс. Правка: нет
  типа — ПРОПУСК с названной причиной (то же правило, что у локальных, `#178/#183`).
- **#502 — ДВОЙНОЙ УЧЁТ ОДНОГО ОБВИНЕНИЯ.** Две РАЗНЫЕ проверки с ОДНИМ условием в одной функции
  дают текстово идентичные строки (у `[DEAD BRANCH]` нет номера строки) и считались дважды.
  Дедупликация по тексту находки. Фикстура `tests/fixtures/precision_dedupe/dup_same_condition.c`
  и часть гейта: ИЗМЕРЕНО «находок 2» ДО → «1» ПОСЛЕ.
- **#503 — `switch` НЕ МОДЕЛИРУЕТСЯ.** `case` считались ПРЯМОЛИНЕЙНЫМ кодом, поэтому
  `if (c == ']') { … return … }` из ПЕРВОГО `case` отменял такое же условие в ТРЕТЬЕМ —
  ЖИВАЯ ветвь объявлялась мёртвой (`curl/lib/curl_fnmatch.c::setcharset`). Правка: внутри
  `switch` с ≥ 2 `case` мёртвая ветвь НЕ заявляется (названный пропуск, причина в `notes`).
  Фикстура `tests/fixtures/precision_clean/switch_repeated_cond.c`: 1 находка ДО → 0 ПОСЛЕ.
- **#504 — BV-ФОРМА НЕ ЗНАЛА ТИПОВ ЛОКАЛЬНЫХ.** `long long value` получала форму `(32, unsigned)`,
  поэтому `value < 0` переводилось как `bvult value 0` (всегда ложь) → ЛОЖНЫЙ DEAD BRANCH в
  `redis/config.c` (`numericConfigGet`, `rewriteConfigGetDefaultValue`). Правка: объявленные
  ЛОКАЛЬНЫЕ типы подмешиваются в выбор знаковости/ширины BV — и ТОЛЬКО туда: в `path_conds` их
  пускать нельзя, свободное имя заставляет SAT честно отказаться и теряются НАСТОЯЩИЕ находки
  (измерено: `num_enum_vals + 1` при наивной правке исчезал, после разделения — вернулся).
- **Расширенный срез (60 файлов на корпус, те же SHA):** curl/lib **0** находок (161 функция) ·
  tigerbeetle/src **0** (315) · redis/src **8** (1684) — и все восемь класса «UB в домене
  сигнатуры». **Precision 8/8 = 1.00, FP = 0 на 2160 функциях.** Recall не пострадал: SV-COMP
  TPR 1.00 / FPR 0.00, `xray-overflow-check` rc=0, `xray-precision` rc=0 (ловушки 0/1/1 —
  два FP-контроля И один TP-контроль, `buggy` 5/5, `known_fp` 0, внешняя база 4).

### #500 + #501: два корня FP со слепого замера закрыты — precision 0.375 → 1.00 на том же срезе

- **#500 — СТАРОЕ значение поля структуры переживало перезапись поля.** В `_clike_conds_at` ветка
  «после блока с `return`» (то есть `(not cond)`) пересекала имена СЫРО: `{'fe__mask'} & {'mask'}
  = ∅`. Ветка «внутри блока» уже использовала `_mut_names_for` (правка `#416`), которая
  разворачивает `a__b` в базу `a` И поле `b`; в ветке «после блока» этого не было. ИЗМЕРЕНО на
  минимизированном до 10 строк `/tmp/deltaA/p1_write.c` (взят из `redis/ae.c`): ЛОЖНЫЙ
  `[DEAD BRANCH]` (UNSAT). После правки — 0 находок, а РЕАЛЬНЫЙ `redis/ae.c` ушёл с 1 ложной
  находки на 0.
- **#501 — БЕЗЗНАКОВЫЙ индекс считался знаковым.** В C `size_t 0 - 1` заворачивается в `SIZE_MAX`,
  а Int-модель давала `-1` и обвиняла `op[opsetlen - 1]` в отрицательном индексе. ИЗМЕРЕНО на
  `redis/acl.c` (минимизировано до 8 строк). Правка: индекс, построенный ТОЛЬКО из значений,
  чей объявленный диапазон начинается с 0 (`u8/u16/u32/u64/size_t/unsigned`), отрицательным
  быть не может — ПРОПУСК с названной причиной. Знаковый индекс (`int n; a[n-1]`) обвиняется
  по-прежнему.
- **ДВУСТОРОННИЙ КОНТРОЛЬ** (чтобы лекарство не убило пациента): фикстура-ловушка
  `tests/fixtures/precision_clean/field_guard_write.c` (поле переписано между гардом и
  проверкой → `xray-precision` требует 0 находок) И обратный контроль
  `tests/fixtures/precision_dead_field/dead_after_kind.c` (поле НЕ переписано, третья
  `kind == 1` — НАСТОЯЩАЯ мёртвая ветвь → новая часть гейта требует РОВНО 1 `[DEAD BRANCH]`).
  Замер: 1 до правки, 1 после — при том что ловушка ушла с 1 на 0.
- **Повторный замер на ТЕХ ЖЕ трёх SHA и том же срезе** (`blind_p1_2026-11-07.log`): curl 0 ·
  redis **7 → 4** · tigerbeetle **2 → 0**; итого **TP 4, FP 0 → precision 1.00** (порог 0.90 взят
  на срезе). Все четыре оставшихся — «UB в домене сигнатуры» (ни один вызывающий в дереве не
  передаёт `LONG_MIN`/`INT_MIN`/`oplen <= 0`); в «баги» не переименованы. Один вердикт
  пересмотрен ЯВНО (`ACLSetUser`: `oplen` — отдельный `ssize_t`, значит `op[0]=='('` не
  доказывает `oplen >= 1`), а не подкручен молча.
- **Цены по recall не обнаружено (измерено):** SV-COMP `signedintegeroverflow-regression`
  TPR 1.00 / FPR 0.00 без изменений, `xray-overflow-check` rc=0, `xray-precision` rc=0
  (known_fp 0, buggy 5/5, внешняя база 4), can-fail `xray-precision`/`xray-overflow`/
  `xray-bounds-note` — все PASS. Апплаенс пересобран: архив `fdb6e072…`, `action-check REAL=1`
  → 5/5.

### P1 слепой замер на трёх незнакомых корпусах — ЦЕЛЬ 0.90 НЕ ВЗЯТА (0.375)

- **Измерено без единой правки анализатора** (`docs/evidence/blind_p1_2026-11-07.log`): curl
  `155f6f76` (lib/), redis `5b69ba2c` (src/), tigerbeetle `68958eb7` (src/), детерминированная
  выборка — первые 25 файлов по имени. Воронка сходится в каждом корпусе (`Σ == total`).
  **curl: 0 находок на 81 функции** (шума нет); **redis: 7 находок → TP 3 / FP 4 (0.43)**;
  **tigerbeetle: 1 находка (напечатана дважды) → FP (0.00)**; ИТОГО **TP 3 / FP 5 → 0.375**.
  Каждая находка разобрана построчно по исходному коду; три TP — это настоящее UB в домене
  сигнатуры (`long index`, `int numbuckets`, `int table_idx`), но в дереве недостижимое.
- **Названы три корня FP (правка НЕ делалась — отдельный такт):** A) ПОЛЕ СТРУКТУРЫ
  моделируется как константа (`s->flags`, `fe->mask`, `batch.status`), хотя его пишут выше в
  той же функции, ВЫЗВАННЫЙ код и запись через указатель → UNSAT на ДОСТИЖИМЫХ ветвях →
  ложный `[DEAD BRANCH]` (3 из 5 FP); B) беззнаковые типы в детекторе ГРАНИЦ (`size_t` как
  знаковый; `op[0]=='(' && …` не считается гардом непустоты) — 2 FP; C) дубль одной находки.
- **Приёмка P1 не выполнена, и это записано как факт**, а не «зелено»: следующий шаг —
  дельта-минимизация каждого корня, двусторонний контроль в `xray-precision` (FP → 0 И TP
  остаётся найденным) и повторный замер на тех же трёх SHA.

### ecosystem-check → RC=0 без ребейзлайна + `action-check` в реестре как CHECK

- **Два предсуществующих красных пункта `tools/ecosystem_check.sh` закрыты правкой КОДА, а не
  потолка** (оба измерены одинаково на `91ccd53e`, то есть не были вызваны этой сессией):
  голые `except Exception:` в четырёх файлах сужены до ожидаемых типов —
  `kerna_check.py`/`spawn.py` → `(ImportError, OSError)`, `mutation_lock.py` → `OSError`,
  `translator_diff_check.py` → `(ArithmeticError, SyntaxError, ValueError, TypeError, NameError)`
  (класс `#198`/`#457`: программные ошибки больше не глотаются). Ретчет **не поднят**:
  `dup_defs_guard` — 31 в 17 файлах (≤ базиса), rc=0. Второй пункт: `LICENSE` не содержал
  идентификатора, который объявляют манифесты — добавлена явная шапка
  `SPDX-License-Identifier: AGPL-3.0-or-later` (+ указатель на коммерческие условия) НАД
  неизменённым полным текстом AGPL; R3 лицензионного гейта по-прежнему зелёный.
  **`bash tools/ecosystem_check.sh` → RC=0** (было 1 по двум причинам).
- **`action-check`: META → CHECK** с настоящим can-fail кейсом `action-doctor`
  (`action.yml` добавлен в `FAULTABLE`, чтобы подсадка откатывалась — класс `#225`): снимается
  вызов `./kerna --doctor`, и ворота ОБЯЗАНЫ покраснеть, потому что кейс сухого прогона
  «`--doctor` не проходит → rc 2» получает 0. Доказано: `canfail --only action-doctor` →
  «проверка ПОКРАСНЕЛА (rc=2) за 1 с». `CASE_TARGET["action-doctor"] = "action-check"`;
  в карту возможностей добавлены три неклассифицированных цели (`action-check` E4,
  `kerna-check` E5, `license-header-check` E6) → `gen_capability_map.py --check` rc=0.
  Реестр: 272 цели, **CHECK 200**, кейсов 245, покрытие **200/200**.

### Шаг 1 + Шаг 2 плана ROI: измеренная цена `#495`, работающий Action, три дефекта дельты

- **#498c — ЦЕНА `#495` ИЗМЕРЕНА (было «документирована»).** Замер `make svcomp-witness-check`
  после `#495`: **37 задач, 11 UNSAFE подтверждено внешним валидатором, 16 SAFE чисты на
  перебранных свидетелях, 0 ложных тревог, 0 недобора** (`docs/evidence/svcomp_after_495.log`),
  `svcomp_baseline.py` — **TPR 1.00 / FPR 0.00** (как до `#495`). НО пробники показали реальную
  дыру: посторонний `if (flag) {…}` до `int x = 2147483647; x++;` давал **0 находок**, то есть
  правило «запретить ЛЮБОЙ `if/while/for` до точки» глушило ровно тот паттерн, ради которого
  детектор написан. Правило СУЖЕНО: гасим находку, только если УСЛОВИЕ ветвления/цикла упоминает
  саму переменную (мутации ловит отдельный счётчик записей — он и убрал ложное обвинение в
  `cmark`). Замер после: пробник с посторонним `if` → **1 находка**, `if (x==10) return; x++;` →
  **0** (звучимо), `cmark_autolink.c` → **0** (`#495` не регрессировал), `xray-overflow-check` и
  `xray-precision` (known_fp 0) зелёные, SV-COMP **TPR 1.00 / FPR 0.00** без изменений.
- **#498 — `audit-delta` не сравнивал РАЗНЫЕ корни (ИЗМЕРЕНО).** Ключ находки строился как «путь
  без первого сегмента», поэтому `git archive` базы и рабочее дерево головы давали разные ключи
  ВСЕГДА: две ИДЕНТИЧНЫЕ папки в разных корнях → «новых 5 + исправленных 5». PR-гейт на дельте был
  ложным по построению. Исправлено: путь берётся ОТНОСИТЕЛЬНО корня аудита (`audit_target`);
  `--selftest` получил именно этот невакуумный кейс.
- **#498b — относительный `target` разрешался от каталога ИНСТРУМЕНТА.** `audit_json` запускал
  ребёнка с `cwd=ROOT`, поэтому `.` означало «репозиторий KERN»: в Action аудит уходил в чекаут
  САМОГО действия (замер: `head.target = /…/kern` при аудите посторонней папки). Теперь путь
  разрешается от каталога ВЫЗЫВАЮЩЕГО.
- **`action.yml` переписан: работает на ГОТОВОМ архиве релиза**, а не на сборке из исходников —
  клиенту не нужны ни `.venv`, ни Zig. Скачивает `kerna-dist-v<ver>.tar.gz` + `SHA256SUMS`,
  СВЕРЯЕТ SHA-256 ДО распаковки (затем ещё раз — содержимое), `./kerna --doctor`, и считает
  **дельту аудита base→head**: PR падает только на находках, внесённых ЭТИМ изменением.
  Коды: 0 нет находок / 1 есть / 2 дистрибутив неполон / 3 артефакт не сошёлся. Обещание
  `sarif-file` СНЯТО — измерено: `./kerna --xray … --sarif OUT` принимает флаг и НЕ создаёт файл
  (и `--github-annotations` в этом режиме печатает 0 аннотаций), а обещание без артефакта —
  класс #497/#370.
- `tools/action_check.py` + `make action-check` — **локальное доказательство поведением**:
  fail-closed разбор `action.yml`, контракт входов/выходов, образца процесса, и СУХОЙ ПРОГОН
  самих шагов на локальном источнике релиза (`KERN_RELEASE_BASE=file://`), сеть не нужна.
  Матрица: чисто→0, баг→1, баг-был-в-base→**0** (анти-FP), исправлено→0, битый архив→3,
  нет ассета→3, `--doctor` не проходит→**2**. `--selftest` вносит 7 поломок и требует отказа.
  Проверено на РЕАЛЬНОМ архиве: `make action-check REAL=1` → 5/5 (sha256 `381005dd70787804…`).
- `examples/ci/kern-gate.yml` — образец рабочего процесса; ссылка на него проверяется гейтом
  (неверный вход → красный), а не остаётся обещанием.
- `tools/make_kerna_dist.sh`: релизная сумма САМОГО архива (`dist-release/SHA256SUMS`) — иначе
  «проверка целостности» была бы только ВНУТРИ архива, то есть после распаковки недоверенных
  байтов. `README-RUN.txt` исправлен по замеру: `./kerna` на папке с 5 находками даёт **rc=0**,
  поэтому прежняя строка «rc=1 — найдены нарушения (для CI)» была ложью дистрибутива; теперь
  коды описаны как измерены, а гейт для CI — Action (0/1/2).
- `.github/workflows/release.yml`: архив апплаенса СОБИРАЕТСЯ и публикуется (раньше в релизе был
  только `kernc`, а `action.yml` качал бы несуществующий файл), `SHA256SUMS` покрывает ОБА
  ассета, и публикация выполняется ТОЛЬКО после `make action-check REAL=1` на этом же архиве.

- **#499 — «НЕТ РЕШАТЕЛЯ» ПРИХОДИЛО КАК «НАХОДОК 0» В МАШИННОМ КАНАЛЕ (найдено
  репро-квитанцией с чистого клона).** Один и тот же вызов без `z3`: человеческий путь
  `--xray DIR` → **rc=2** и названный отказ («это N(0,0) по Белнапу, а не «находок 0»»), а
  ABI-путь `--xray DIR --xray-json` → **rc=0**, `findings: 0`, `notes: []`. Отказ печатался
  ВНУТРЬ перехваченного буфера, а врата решателя вызывались только на человеческом пути.
  Цена: гейты читали «нет решателя» как «код чист» и печатали «потеря сигнала (FN)»,
  «ПРОПУСК», «JSON-отчёт врёт о происхождении». Исправлено: проверка `kernc` и врата
  решателя работают и в JSON-пути, отказ едет ВНУТРИ ABI отдельным документом
  (`_xray_json_refusal`: нулевая воронка + `note` с причиной) с кодом **2**. Проверено
  поведением: `tools/abi_check.py` получил зонд `refusal_probe` (подставной `kernc`
  отвечает «z3 недоступен») — на коде до правки он даёт `rc=0, notes: []`, после — `rc=2`
  и причину, поэтому гейт не может быть зелёным при спрятанном отказе. Апплаенс
  пересобран, архив несёт правку (`b573408c…`, `action-check REAL=1` → 5/5).

Tack 2.4 / **Test 1**: differential soundness check of the C-like translator against LIVE
compilers (`tools/translator_diff_check.py`, `gcc`/`rustc`/`node`), plus **defect #465**:
nested `if/else` in C-like bodies used to collapse into one statement and were silently skipped.
**Test 1 (hunting third-party code)**: `--xray` over `deepseek-ai/dsh-superagent-prototype`
(`src/policy.ts::settingsPolicy`) produced a FALSE `[DEAD BRANCH]` on a REACHABLE branch —
**defect #467**: a brace-less `if` swallowed the rest of the body in semicolon-free (ASI) TS/JS/Go.
**Test 3**: surviving mutants behind `pytest` (`tools/pytest_blind_check.py`), plus **defect #466**:
the arithmetic/translation gates crashed under the system `python3` (no `z3-solver` package).
**Test 1 (hunting third-party code, part 2)**: `--xray` over `deepseek-ai/DeepJIT` (C++20
header-only) exposed THREE blind spots — **defect #468**: `.hpp`/`.cu`/`.cuh` were missing from
`CLIKE_EXT` (86 of 94 core files invisible), `assert len(x) == 1` was not a path guard, and the
bodies of compound `try`/`with` lost their guards (9 false `[BOUNDS PATH]`).

### Added

- **#494 — УПАКОВКА `kerna` (Zero-Dependency Appliance) + ДВА КОРНЯ.** Спайк (изолированно, main не
  тронут) дал числа: PyInstaller onefile — **9.8 МБ, старт 253 мс, сборка ~40 с**; Nuitka — 9.6 МБ,
  162 мс, но сборка **~9 мин** и `sys.frozen` НЕ выставляется (нужен `__compiled__`); дистрибутив
  целиком **62 МБ** (kerna 9.8 + kernc 26 + z3 27). Nuitka ОТКЛОНЁН: 90 мс не окупают 9 минут.
- `tools/env_resolver.py` — **RESOURCE_ROOT** (вшитые данные, `sys._MEIPASS`) и **HOST_ROOT** (рядом с
  бинарником: `kernc`, `z3`, `.venv`, проверяемый код), с поддержкой ОБОИХ упаковщиков.
  Ловушки, снятые им (все ИЗМЕРЕНЫ на спайке): `ROOT = Path(__file__).parent.parent` в frozen
  указывал в `/tmp` (находок 0, `rc=2`); `server.json` читался на импорте (`ImportError`); путь к
  `kernc` считался ОТДЕЛЬНО и уезжал в `/tmp/zig-out/bin/kernc`.
- `tools/kerna_doctor.py` — предстартовая проверка: отсутствие `z3`/`kernc`/`server.json` —
  **НАЗВАННЫЙ отказ `rc=2`**, а не `findings 0, unreadable 1, rc=0` (измерено: без решателя stderr
  был ПУСТ). **#494a**: Python-часть искала решатель через `z3bin` (`$Z3`/`.venv`/`PATH`), а `kernc`
  зовёт буквально `"z3"` — только `PATH`. Доктор теперь ПУБЛИКУЕТ найденный путь в `PATH` для
  детей; гейт поймал это как R3 «паритета нет».
- `tools/kerna_main.py` — официальная точка входа: ДИСПЕТЧЕР (один бинарь обслуживает и паспорт, и
  подрежимы `--xray`/`--anti-cheat`) + доктор. Без диспетчера собранный бинарь отвечал
  `unrecognized arguments: --xray` и анализ молча не выполнялся (тоже измерено).
- `tools/build_kerna.sh` + `make kerna-build` (BUILD) и `tools/kerna_check.py` + `make kerna-check`
  (CHECK) — **#494**: гейт СОБИРАЕТ настоящий onefile-бинарь и проверяет: R1 сборка; R2 изоляция в
  пустом каталоге; **R3 паритет с dev** (находок 5/5, `unreadable 0`); **R4 без `z3` — `rc=2`**;
  R5 без PyInstaller — НАЗВАННЫЙ SKIP (а при `KERNA_REQUIRE_BUILD=1` — провал).
  ИЗМЕРЕНО после: R1 9.8 МБ · R3 паритет · R4 `rc=2` · `rc=0` всего.
- **#493 — ДВОЙНОЕ ЛИЦЕНЗИРОВАНИЕ: AGPL-3.0-or-later + коммерческая.** `LICENSE` теперь содержит
  ПОЛНЫЙ текст GNU AGPL v3, рядом `LICENSE-COMMERCIAL.md` (когда коммерческая лицензия нужна и
  почему AGPL, а не пермиссивная). MEASURED: файлов в охвате (`src`, `tools`, `tests`, `examples`)
  — **399**, из них без утверждённого заголовка было **398** (242 со старой лицензией, 146 вообще
  без заголовка). После: **0 без заголовка, 0 со старой лицензией**.
- `tools/license_header_check.py` + `make license-header-check` / `license-header-selftest` —
  **#493**: R1 утверждённый однострочный заголовок у каждого файла охвата (после shebang); R2 ни
  одного упоминания старой лицензии; R3 в `LICENSE` ПОЛНЫЙ текст AGPL v3, а не имя; R4 исключения
  НАЗВАНЫ и обоснованы (`audits/` — транскрипции чужого кода: cmark-gfm, DeepJIT, zig-std,
  TheAlgorithms, CWE; `docs/` — генерируется) и обязаны существовать; R5 `--selftest` 3/3.
  Заголовок — ОДНА строка **намеренно**: многострочный сдвинул бы номера строк в фикстурах, на
  которые опираются отчёты `xray-*` («строка N»).
- **#493a (найдено процессом, не ревью)**: единая замена токена лицензии переписала его ВНУТРИ самой
  проверки, и гейт стал искать новый идентификатор вместо старого — то есть **ослеп ровно в момент
  применения** (измерено: «всё ещё упоминают AGPL-3.0-or-later: 399» на 399 файлах). Токен старой
  лицензии теперь собирается из двух частей, и это записано в коде как урок.
  **#493b**: тот же класс во втором гейте (`check_license_consistency`, `#222`) — он проверял
  SPDX-идентификатор внутри текста лицензии, где его нет; проверяется фактическая строка.
- **Замок контрактов (#370-класс) поймал правку правильно**: заголовок сдвинул `/// @kern:` на
  строку, и `contracts-lock-check` сообщил «контракт УДАЛЁН». Диф подтвердил, что изменена ТОЛЬКО
  строка заголовка (ни один контракт не тронут), замок перезапечатан: 73 контракта.
- Манифесты и `--version` приведены к AGPL: `server.json`, `.well-known/mcp.json`, `CITATION.cff`
  (`AGPL-3.0-or-later` — валидный SPDX), `kernc`/`kernx` печатают `AGPL-3.0-or-later / Commercial`.
  Историю (`CHANGELOG`, `docs/RELEASE_NOTES_*`) НЕ переписываю: это запись о том, что было.
- **#492 — РАТЧЕТ `spawn` ЗАКРЫТ: 51 → 0, порог = 0.** Every `subprocess.run/Popen/
  check_output/check_call/call` without a `timeout=` (51 sites in 28 files) got an explicit
  `timeout=900` — mechanically, byte-precisely (CPython `col_offset` is a BYTE offset and the
  files contain Cyrillic), each file syntax-checked before writing. `BASELINE_NO_TIMEOUT 51 -> 0`,
  so from now on ANY new subprocess without a timeout is a RED gate. This is the class that bit
  us three times (`#466` z3 not in PATH → silent SKIPs, `#470` 5.4 GB without a cap, `#477` no
  timeout at all).
- `tools/tour.py` + `make tour` — **#492**: the FIVE-ARC showreel (developer contracts · blind
  pytest · PR delta · `.kimg` without a solver · one-button passport), **21.8 s, 0 failures**.
  Every arc runs a REAL check and prints its REAL output, so the showreel CANNOT be green while
  the code is broken (rc=1 otherwise) — otherwise it would be advertising disconnected from code.
- `docs/LIMITS.{md,ru.md}` — numbers brought up to date after `#476`/`#491`: `known_fp 1 -> 0`,
  external baseline `21 -> 4` (all four triaged: `kth`, `rpn_eval`, `to_base` are REAL crashes,
  `find_in_sorted` is a closure — class `#200`), and the 321 `[!]` per-branch refusals are now a
  named note. **The page can no longer lag the gate**: `make xray-precision` now READS both
  `LIMITS` files and fails if they name a different `EXPECTED_KNOWN_FP` / external baseline.
- `tools/translator_diff_check.py` — the C-like translator is compared against LIVE compilers
  (`gcc`/`rustc`/`node`) on a matrix of 13 constructs × 3 languages. Every live point must be
  PROVEN **and** the floor-semantics trap (Python `//`/`%`) must NOT be proven (defect class
  `#349`). A missing compiler is a NAMED skip, never a silent green.
- `make translator-diff-check` (CHECK) and `make translator-diff-selftest` (META), wired into the
  full `ci.sh` contour (the gate drives real compilers and runs ~77 s); a new can-fail case
  `translator-diff` proves the gate is able to go red.
- `tools/pytest_blind_check.py` — **Test 3** («surviving mutants behind `pytest`»): five functions
  with `@kern:` contracts and deliberately WEAK tests. Every one-line body mutation must SURVIVE
  `pytest` (`rc=0`) **and** be KILLED by `kern` with a counterexample; measured `TP=5/5`, `TN=5/5`,
  `FP=0`, `FN=0`, `J=1.00`.
- `make pytest-blind-check` (CHECK) and `make pytest-blind-selftest` (META); a new can-fail case
  `pytest-blind` proves the gate goes red when a contract is weakened.
- `tools/z3bin.py` — the z3 solver is invoked as a BINARY (`$Z3` → `.venv/bin/z3` → `PATH`); the
  `z3-solver` python package is not a runtime dependency.
- `tools/xray_asi_check.py` + `make xray-asi-check` (CHECK) — regression for **defect #467**:
  four fixtures (real ASI TS, minimal TS repro, TS dead-branch control, C control). The two
  zero-finding fixtures must ALSO be genuinely analysed (`checked >= 1`, `skipped 0`), so a
  silently skipped file cannot masquerade as «0 findings». The control shares the FIXED language
  (TS), since the fix lives in the TS branch; a can-fail case `xray-asi` proves the gate goes red
  (dropping the ASI branch) for the REAL reason, not from a crash.
- `tools/audits_mem_cap_check.py` + `make audits-mem-check` (CHECK) and
  `make audits-mem-selftest` (META) — **defect #470**: the memory cap of the audit harness is
  verified by REAL subprocesses (fast, no Z3): (A) a child asking 8× the cap must return
  `rc=125` with a NAMED reason, (B) death by signal (`rc<0`) must be named (`SIGSEGV`), not
  surface as a raw `-11`, (C) a non-memory failure (`exit 3`) must pass through UNCHANGED (no
  false accusation). The meta mode proves non-vacuity: with `mem_cap=False` the same 1 GB
  allocation succeeds (`rc=0`) and the signal stays raw, so the gate cannot be green without a
  limiter. A can-fail case `audits-mem-cap` removes `preexec_fn` and the gate goes red in 1 s.

### Fixed

- **#497 (справедливая претензия владельца «зачем всё в бинарник, если не утрясли?»)**:
  ИЗМЕРЕНО, что архив `kerna-dist` НЕ содержал `docs/LIMITS.md` — то есть клиент получал
  ИНСТРУМЕНТ БЕЗ КОНТРАКТА О ГРАНИЦАХ, а `README-RUN.txt` ссылался на файл «в репозитории»,
  которого у клиента нет. Это ровно тот класс, который проект запрещает: обещание без мелкого
  шрифта. Теперь: (1) сборка ОТКАЗЫВАЕТ (`exit 3`), если `LIMITS.md`/`LIMITS.ru.md` нет;
  (2) оба файла едут В АРХИВЕ; (3) `README-RUN.txt` указывает на файл РЯДОМ. Проверено:
  в архиве 9 файлов под `SHA256SUMS`, все целы, `LIMITS.ru.md` на месте.
- **#495 ЗАКРЫТ — настоящая причина найдена дельта-минимизацией, предложенная опровергнута.**
  Гипотеза «переприсваивание границы цикла (`link_end = i`) + гард в `switch`» НЕВЕРНА:
  копии БЕЗ этой мутации воспроизводят FP, а С ней — нет (V1/V2/V3, измерено). Минимальный репро
  (M3, ~20 строк) показал настоящее различие: `closing`/`opening` как ЛОКАЛЬНЫЕ с `= 0` против
  ПАРАМЕТРОВ; ни `switch`, ни типы, ни форматирование, ни `const` роли не играют (V5/V11–V13).
  Корень — в детекторе `_clike_incdec_findings` ДВЕ ошибки звучания: он брал ИНИЦИАЛИЗАТОР как
  ТОЧНОЕ значение, хотя переменная МУТИРУЕТ раньше (`closing++` в цикле), и вообще не учитывал
  гарды (`if (closing <= opening) { return; }`).
  ИЗМЕРЕНО: `gcc -fsanitize=undefined,address` на реальной функции UB НЕ видит (`result=0`).
  ФИКС: детектор обвиняет только на ПРЯМОЛИНЕЙНОМ пути с НЕИЗМЕНЁННЫМ значением (потеря recall
  документирована в коде: ложное обвинение хуже пропуска, #178/#183).
  ДВУСТОРОННЯЯ ПРОВЕРКА: фикстура `cmark_autolink.c` переехала в `precision_clean` (0 находок), а
  паттерн SV-COMP `int x = 2147483647; x++;` по-прежнему ловится (`make xray-overflow-check`:
  `collapsing_sum` найдена, 4 ловушки чисты). РЕТАРГЕТ: `EXPECTED_KNOWN_FP 1 → 0`.
- `tools/make_kerna_dist.sh` + `make kerna-dist` (BUILD) — **#496**: релизный архив
  `kerna-dist-v<ver>.tar.gz` (**62 МБ → 27 МБ**): `kerna` + `zig-out/bin/kernc` + `.venv/bin/z3`
  + `server.json` + обе лицензии + `README-RUN.txt` + `SHA256SUMS`.
  ПРОВЕРЕНО «как у клиента»: распаковка в ЧИСТЫЙ каталог вне репозитория → `./kerna --doctor`
  зелёный, `sha256sum -c SHA256SUMS` цел, аудит внешней папки нашёл `[CRASH PATH] ratio: b == 0`.
  В `README-RUN.txt` явно сказано: `rc=2` — «дистрибутив неполон/нет решателя», а НЕ «код чист».
- **#495 — диагноз уточнён ЗАМЕРОМ, гипотеза опровергнута.** Предполагалось, что причина в
  переприсваивании границы цикла (`link_end = i`) и лечится транзитивным `(= link_end i)`.
  ИЗМЕРЕНО дельта-минимизацией: (а) копия без мутации границы — FP **нет**; (б) копия с мутацией —
  FP **нет**; (в) замена `switch` на `if/else-if` — FP **есть**; (г) удаление соседних ветвей — FP
  **исчезает**; (д) соседняя ветвь, которая только `return` (без декремента) — FP **есть**.
  Значит триггер — НАЛИЧИЕ СОСЕДНЕЙ ВЕТВИ рядом с ветвью, содержащей гард-возврат, а НЕ мутация
  границы. Минимальные формы (без цикла `for` + `while` + соседней ветви) не воспроизводят.
  Поэтому «десятиминутный фикс» здесь был бы гаданием: `#495` ОСТАЁТСЯ посчитанным (`known_fp = 1`),
  фикстура — реальная функция, лог минимизации — в отчёте такта.
- **#495 (ТРОФЕЙНАЯ ОХОТА, реальный код)**: `[OVERFLOW PATH]` на `closing--` в
  `cmark-gfm::extensions/autolink.c` оказался **ЛОЖНЫМ**. Проверено компилятором: гард
  `if (closing <= opening) { return link_end; }` защищает, и `gcc -fsanitize=undefined,address`
  на реальной функции UB **не видит** (`result=0`, rc=0). Причина FP: гард в ветви `switch` не
  сужает путь, если граница цикла ПЕРЕПРИСВАИВАЛАСЬ в той же функции (`link_end = i; break;`).
  МИНИМАЛЬНЫЕ формы без переприсваивания **не воспроизводят** — поэтому фикстура сделана из
  реальной функции (транскрипция с атрибуцией, BSD-2-Clause). Учтено ретаргетом:
  `EXPECTED_KNOWN_FP 0 → 1`, имя `autolink_delim_fixture` названо, `LIMITS` обновлён (страж
  сверяет числа с гейтом).
- `tools/kern_contracts.py` — **#491**: the report called a NAMED refusal an «internal error».
  `Unsupported` (a `Call`/`Subscript`/`Attribute` node outside the BV subset) and `SyntaxError`
  (`clike_to_python` could not parse a foreign language) are EXPECTED exits, yet each one printed
  `[!] BV-форма условия: внутренняя ошибка при живом replay`. MEASURED on our own `kern/src`:
  **321 lines** (279 `Call`, 27 `SyntaxError`, 8 `Subscript`, 7 `Attribute`) — the report looked like
  a tool crash where the analyser had simply declined. Now they are counted and emitted as ONE
  note: `note: BV-перевод условия не применён 321 раз (причины: Unsupported: узел Call x279;
  SyntaxError x25; Unsupported: узел Subscript x8)`. OUR real errors (`NameError` etc.) stay LOUD
  (`_replay_soft`, #198/#208).
  MEASURED after: `--xray src` -> **0** internal errors, 92 files, 154/423 checked, **0 findings**,
  `Σ 423 == total 423`, `rc=0`.
- `tools/xray_check.sh` — new block for **#491**: `kern/src` must report **0** «внутренняя ошибка»
  lines; the note counts the refusals instead. The same clean stdout is what keeps the ABI `#490`
  intact for third-party code.
- **(Stage 4 verified, no code change)** `make pcc-offline-check` (#488) confirmed on this tree:
  solver ABSENT from the check environment, `check-integrity rc=0`, `check-proof rc=0 trusted 0`,
  a corrupted proof is REJECTED (`rc=1`) — i.e. the recipient of a `.kimg` really does not need Z3.
- `tools/kern_contracts.py` — **#476 (ШЕСТЬ точных причин вместо одной догадки)**: the class
  «known false positive on correct code» was NOT a chained comparison (the hypothesis):
  `if 0 <= i < len(data)` ALREADY worked (measured). The real causes were six, each fixed
  separately and each with its own measured effect on `QuixBugs/correct_python_programs`
  (**21 unique accusations -> 4**):
  **#476a** `len(<literal>)` in a guard became a SYMBOLIC length while bounds came from the
  LITERAL — the two representations of one length were never tied, so the solver picked
  `kern_len_data = 5` for a 4-element literal (`i = 4`). Now the literal length is asserted.
  SOUNDNESS: `lens` is built only for names bound to a literal EXACTLY ONCE (reassignment ->
  honest refusal), otherwise the fix would create a new false accusation.
  **#476b** loop-variable bounds `for i in range(a, b[, step])` were not added at all —
  `items[i - 1]`, `perm[j]`, `rows[r - 1]` were accused with unreachable counterexamples
  (`i = -1`, `r = 0`). Now `a <= i < b` (or `b < i <= a` for a negative step) enters the path.
  A negative step literal is `UnaryOp(USub, Constant)`, NOT `Constant(-1)` — the first version
  checked only `Constant` and therefore rejected EVERY `range(a, b, -1)`, i.e. exactly the
  loops it was written for (measured before/after).
  **#476c** `d[k] = v` is a WRITE by key, not an index read (`weight_by_node[source] = 0`,
  counterexample `source = -1`); writes are excluded by node identity.
  **#476d** a literal length stops being true when the list GROWS (`rows = [[1]]` +
  `rows.append(row)`) — `append/extend/insert/+=` disable the literal length.
  **#476e** a `dict` name (built by `{...}`, `.items()`, `.get()`) has no «index out of
  0..len-1» — reads by key are skipped instead of accused.
  **#476f** the `[REPO SUMMARY]` finding counter counts BOTH the per-function context line and
  the per-file list, so it is inflated (8 vs 4 measured); the PRECISION metric now counts
  UNIQUE accusations `(file, function, type)`.
- `tools/xray_precision_check.py` — **retarget fired**: `EXPECTED_KNOWN_FP 1 -> 0`, the function
  `idx_literal_guard` moved from `precision_known_fp` to `precision_clean`, external baseline
  `21 -> 4`. MEASURED after: `clean 0`, `known_fp 0`, `buggy 5/5`, external 4 unique. Remaining 4
  are named and triaged: `find_in_sorted` (closure + early return, class `#200`), `kth` (`arr[0]`
  on an empty list — real), `op` (`rpn_eval` divides by a popped value — real), `to_base`
  (`b == 0` — real).
- `tools/kern_scan.py` + `make kern-scan-check` — **#489**: the «ONE BUTTON» for ANY folder
  (`python3 tools/kern_scan.py <path>`): inventory → `--xray` (ABI `--xray-json`) → `@kern:`
  contracts → `--anti-cheat` → ONE-SCREEN passport (RU + `--json`). Scope is honest: on a big repo
  `--sample N` takes a deterministic alphabetical slice and the passport says **ВЫБОРКА** instead of
  pretending it scanned everything. Measured on FIVE third-party corpora (read-only, temp copies):
  `cmark-gfm` C 3 threats; `TheAlgorithms/Rust` 2 (both real: `fast_factorial` `p == 0`,
  `hamiltonian_cycle` `pos - 1`); `DeepJIT` C++20 0; `dsh-superagent` TS 0; `QuixBugs` 13 (ALL false —
  the known `#476` class, every one inside `correct_python_programs/`).
- **#489a**: the passport printed paths of the TEMPORARY copy (`/tmp/kern_scan_ab12/…`) — unreadable
  for the owner; now the original root is restored. **#489b**: `SMELL` (style) was counted as a
  THREAT — the report named something that did not happen; threats and style are now separate numbers.
- **#490**: the scanner concatenated stdout+stderr, so the tool's own diagnostics (`[!] BV-форма
  условия: внутренняя ошибка`) broke the ABI — it stayed green on fixtures (empty stderr) and failed
  on EVERY third-party repo with `arr[i]` in a condition. Now `run_abi()` reads **stdout only** and the
  passport reports `diagnostics_to_stderr`. The gate grew R7 (fixture WITH stderr) and R8 (a real
  third-party corpus, named SKIP if absent), and R4 now compares the **set of types**, not the count —
  the first version was vacuous because 1 `SMELL` happened to equal 1 real threat.
- `tools/kern_contracts.py` — **defect #465**: nested `if/else`
  (`if (a > b) { if (a > 0) { … } else { … } } else { … }`) collapsed into a single statement
  (`SKIP — c-выражение вне подмножества: 'a > b) if (a > 0'`). `_collapse_cond_returns` now
  folds `if (c) { return a; } else { return b; }` into `return c ? a : b;` by bracket balance
  BEFORE brace flattening; nested branches fold recursively.
- `tools/arith_semantics_check.py`, `tools/lang_semantics_check.py`, `tools/arith_zig_ref_check.py`
  — **defect #466**: `import z3` raised `ModuleNotFoundError` under the system `python3`
  (`PYTHON ?= python3`), so `make arith-semantics-check` returned `RC=2` and the `arith-semantics`
  can-fail case passed VACUOUSLY (a non-zero rc read as «the gate can go red»). Now `RC=0` under
  both `python3` and `.venv/bin/python`, and the can-fail case goes red for the real reason.
- `tools/kern_contracts.py` — **defect #467**: a brace-less `if` in an ASI-style file
  (TS/JS/Go without `;`) made `_clike_block_end` fall back to `body.find(";")`, which in such a
  file is the END of the body — the inner condition leaked as an OUTER fact, two contradictions
  made it UNSAT, and a REACHABLE branch was reported as `[DEAD BRANCH]` (a false accusation, worse
  than a miss). `_clike_block_end` now takes `lang`; for `go`/`js`/`ts` without `{}` the statement
  ends at the NEWLINE (`;` is taken only if it comes earlier), which NARROWS the block — fail-closed.
- `tools/kern_contracts.py` — **defect #468** (found hunting `deepseek-ai/DeepJIT`): three blind
  spots in `--xray`. (a) `.hpp`/`.hh`/`.cu`/`.cuh` were missing from the C/C++ extension set, so
  86 of 94 core files of a C++20 header-only library were INVISIBLE (the parser could handle them);
  they are now a single `C_EXT` list, and `CLIKE_EXT = {…} | C_EXT` (lesson #353: one place).
  (b) `assert len(x) == 1` was not a path guard in the BOUNDS walk (the crash walk got one in #179),
  and `assert len(set(x)) == 1` emitted a junk symbol — both now add path conditions, plus the
  finite-set cardinality axiom `|set(x)| <= len(x)` (boundary: a `Name` `x`, `k >= 1`). (c) compound
  `try`/`with` were not walked, so their bodies lost inner guards (an `assert` inside `try`); they
  are now walked SEQUENTIALLY while `except`/`finally`/`else` keep the OUTER path (soundness).
  MEASURED: 9 false `[BOUNDS PATH]` on `DeepJIT` tests -> 0.
- `tools/kern_contracts.py` — **defect #471** (three faces of ONE class: "the guard is
  lost, so protected code is accused"). (a) **Python: the `else` branch carried the WRONG
  guard** — the scan at the `ast.If` node walked the WHOLE `If` (including `orelse`) with the
  direct `cond` instead of `(not cond)`, so `if b == 0: return a; else: return gcd(a % b, b)`
  was accused of `[CRASH PATH] b == 0` — the very condition the `if` excludes. The scan is now
  body-only; the recursive `_walk_branches(orelse, path + [(not cond)])` stays the single
  source of truth. (b) **C-like: the body of `while` was analysed WITHOUT the loop condition**
  (`_exec_clike`/`_xray_clike_file` registered only `if (...)` blocks) — Euclid's
  `while b != 0 { … a % b … }` was accused of dividing by `b == 0`, which is the EXIT
  condition. Added `_clike_while_conds_at`: the condition is applied inside the loop body only,
  with sound invalidation (a variable reassigned BEFORE the current statement drops the guard;
  an assignment INSIDE it does not, because the RHS is evaluated with the OLD value). (c) **C-like:
  the `else` branch got no `(not cond)`** — `if a == 0 { … } else { gcd(b % a, a) }` was accused
  of `a == 0`. Added `_clike_else_conds_at`. HONESTY NOTE: the first version of (c) simply
  ADDED `(not cond)` while `if_blocks` already carried the direct `cond` (one block covers both
  branches) — the path became `cond ∧ ¬cond` = UNSAT, and **REAL findings disappeared**
  (MEASURED: `modular_exponential`, a true `modulus == 0`, vanished). The helper now returns
  `(direct, negated)` pairs and the caller REPLACES the direct guard — measured back.
- `tools/kern_contracts.py` — **defect #472**: `f32`/`f64`/`float`/`double` were absent from
  `_TYPE_MAP`/`_NUMERIC_TYPES`/`_CLIKE_RANGES`, so the fallback silently put them in the
  INTEGER domain (class #321) and `pub fn debt_to_equity(debt: f64, equity: f64) -> f64
  { debt / equity }` was accused of `[CRASH PATH] equity == 0` — in IEEE-754 that is `inf`/`NaN`,
  NOT a panic. QF_FP is honestly unsupported, so such functions now become a **NAMED skip**
  (`вещественная арифметика (f32/f64) — модель QF_FP не поддерживается`) instead of a verdict.
- `tools/kern_contracts.py` — **defect #473**: `[BOUNDS UNKNOWN]` printed "НЕ считается ни
  находкой, ни безопасным" and was appended to `found` — Belnap **N** counted as **F**
  (the same class as #454/#469b, but under a SECOND label). Three branches (index modified in
  a loop; inside `while`; solver "unknown") now go through one `_note()` router to `notes`.
  MEASURED on `QuixBugs`: counter `62 -> 42`, while the set of REAL findings is byte-identical
  (31 `[BOUNDS PATH]` + 6 `[CRASH PATH]` + 5 `[SMELL]` before and after) — только класс N ушёл.
- `tools/xray_check.sh` — TWO-SIDED regression gate for #471a/b/c + #472 + #473 on the new
  fixture `tests/fixtures/xray_crash_guards/{guards.py,guards.rs}`: FIVE cases must be silent
  (`gcd_guarded`, `gcd_no_else`, `gcd_while_rust`, `gcd_else_rust`, `ratio_f64`) and THREE must
  stay findings (`gcd_unguarded`, `arr_unguarded`, `ratio_i64`) — exactly `находок 3`. Without
  the TP controls a "fix" by muting would pass; with them it cannot.
- `tools/canfail.py` + `tools/registry.py` — three can-fail cases (`xray-guard-else`,
  `xray-while-guard`, `xray-float-skip`) prove the gate can go red by disabling exactly one fix
  (231 -> 234 non-vacuous cases).
- **`#480` CLOSED BY MEASUREMENT (no code change)** — «`premises_unbound` для BV» is STRUCTURAL, not a
  naming problem. Investigation, step by step:
  1. with the depth fix (`#479`) the same file parses into 21 758 steps, and the refusal becomes
     `premises_unbound` with `посылок 1/794`;
  2. dumping the actual premises shows only THREE top-level `(asserted …)` steps — `$x16`, `$x22`,
     `(not (bvuge result offset))` — so the missing piece looked like a hash-consed NAME;
  3. `$x16` really is a `let` binding `(and $x9 $x15)` that expands to the contract assertion
     verbatim, so TWO fixes were implemented: an abbreviation lookup for bare atoms in
     `expandLets`, and a `collectAbbrevs` pre-pass (the map was EMPTY when the proof root is a
     command list `(set-logic …) (declare-fun …) … (let …)`);
  4. MEASURED after both fixes: still `посылок 1/794`, trusted steps 19 865 -> 19 874, verification
     SLOWER. Cause, from the checker's own debug channel: the `?x` abbreviations are BIT-LEVEL
     `mkbv` terms over hundreds of `k!` atoms (`?x17516 = (mkbv k!960 k!970 …)`), i.e. the 794
     "premises" are bit-blast CLAUSES, not contract assertions. Matching them to 3 contract
     assertions is conceptually impossible;
  5. therefore BOTH fixes were REVERTED (rule: no measurement — no change) and the boundary is
     recorded instead. The real fix requires a solver emitting DRAT/LFSC (cvc5 / Bitwuzla), which
     is a product decision, not a patch.
  This is why `LIMITS` says BV is not proof-carrying — now with the exact numbers.

- `tools/pcc_demo_check.py` + `make pcc-offline-check` (CHECK) — **#488 / STAGE 4: the proof-carrying
  artifact verified BY THE RECIPIENT WITHOUT A SOLVER**. The whole B2B claim («the artefact carries
  its proof, the recipient needs no Z3») was unmeasured text; now it is a gate. It runs in a CLEAN
  environment (`env -i`, `PATH=/usr/bin:/bin`, no `.venv`) and PROVES the absence of the solver
  instead of assuming it (`command -v z3` must print `NO_Z3` — otherwise the «without Z3» demo would
  be self-deception). Then: (1) `kernc check-integrity audits/real_code_corpus.kimg` -> rc=0
  (Merkle root + per-object digests over 88 objects, so bit-rot cannot pass); (2) `kernc check-proof
  audits/pcc/cwe191_good_sub_good.smt2 audits/pcc/...proof` -> rc=0 with
  `[PROOF VERIFIED] trusted: 0 | holes: 0` (22 steps, premises 3/3, NOT `PARTIAL`); (3) NON-VACUITY:
  a forged proof (one `false` -> `true`) must be REJECTED with rc!=0 and a NAMED reason
  (`ОТВЕРГНУТО: корень вывода не является false`) — a demo that accepts forgeries measures nothing.
  Both the certificate and its SMT-LIB formula are COMMITTED (`audits/pcc/`), so the demo is
  hermetic and re-runnable by anyone, including a container with no solver at all.
  Can-fail case `pcc-demo` corrupts the committed proof and the gate reddens in 0 s.
- `tools/mutate_log_check.py` + `make mutate-log-check` (CHECK) / `make mutate-log-selftest` (META)
  — **#487, the mutation log gets a MACHINE OWNER**. Three different numbers (1345 in the log,
  1376 in README, 1597 in facts) lived side by side precisely because nobody compared the sweep
  log with anything: the file lay there, «100 %» in README lived its own life, and the site count
  grew every tact. The gate now requires the log, `facts.json` and BOTH READMEs to say the same
  thing: sites in the log == `facts.json["mutation_sites"]` (an incomplete log is exactly how
  1345 survived next to a fact of 1597), `0` survivors and `RC=0` (otherwise «100 %» is a lie),
  a `<killed> / <killed>` line and the site count in the README, and NO OTHER mutation number of
  the same order of magnitude in the mutation row (per-module counters such as 184/184 and
  244/244 stay legal — a gate that reddens on correct documentation is useless). The log itself
  now carries a trailer produced by `tools/mutate_full.sh`: `RC=<rc>` and the kill split, so the
  artefact describes its own run. FINAL SWEEP: **1597 / 1597 killed, 0 survivors, RC=0**, and the
  split is NAMED because it matters: **test-killed 1422 · compile-killed 172 · timeout-killed 3**
  — 172 kills by the compiler are weaker evidence than a test kill, so they are not averaged
  away. `--selftest` proves all five breakage types are caught; can-fail `mutate-log` flips
  `RC=0` to `RC=2` in the log and the gate reddens.

- `tools/gen_capability_map.py` + `make capability-map` / `make capability-map-check` (CHECK) —
  **#485, the capability map as a GENERATED artefact**. A hand-written map goes stale on the
  194th target and starts LYING, and a document that lies is worse than none. So the map is
  produced from `tools/registry.py` + `tools/canfail.py`: targets and their class, the canfail
  case proving each target CAN go red (class #356), the defect numbers taken FROM THE CASE
  DESCRIPTION ITSELF, and the reproduce command. The document is grouped into SIX echelons
  (formal core / Belnap-Next / AI-sabotage / x-ray+precision+delta / kimg+attestation+wasm /
  resources+self-control), not alphabetically, so a reviewer sees the defence structure in ten
  seconds. `--check` compares the files with freshly generated content, so adding a target and
  not regenerating REDDENS the gate; it also refuses an unclassified target and a target without
  a case (only `kern` is exempt by name, and the exemption is written down). MEASURED:
  **199 CHECK targets, 0 unclassified, 0 without a case** — including the gate itself. Can-fail
  case `capability-map` deletes one row from the generated document and the gate reddens.
- **`#486`: building the map exposed THREE real defects in the registry itself.** MEASURED:
  (a) `"ubsaFe": "CHECK"` — a TYPO phantom: no such make target exists (the real one is
  `ubsafe`), yet coverage was counted for it; (b) `"stress-real": "CHECK"` — also no target
  (`zig build bench-stress-real` runs inside `bench`), so it was a phantom CHECK too;
  (c) `"ubsafe": "ubsafe"` appeared TWICE in `CASE_TARGET` — the second key silently overwrote
  the first (a lost case, the #356 class). All three removed; the registry now reports
  `194/194` (after adding the new gate) and `CASE_TARGET` is complete in both directions.
  This is exactly the value of machine parity: the map is not a summary, it is a CHECKER of the
  registry.

- `tools/audit_delta.py` + `make audit-delta` (META) / `make audit-delta-selftest` — **#484, stage 3 of
  the strategy: the differential audit**. A reviewer's question is not «how many functions were
  checked» but **«what got worse in THIS change»**; without a delta the audit cannot be a blocking
  PR gate, because «was proven, now SKIP» is invisible in a full report. The comparison goes THROUGH
  the machine ABI (`--xray-json`, #483) instead of parsing text: new finding -> exit code 1, fixed
  finding -> 0, and a funnel drift (checked/trivial/skipped) is printed even when no finding was
  added — that is the QUIET WEAKENING case («proved less, nothing new accused»), which is reported
  explicitly. Finding identity is `(file, type, function)` and not the whole text: counterexamples
  and line numbers change between versions, so comparing them raw would flag every code move as a
  regression. HONEST BOUNDARY: «new finding» means «a detector fired», not «it was safe before»
  — interprocedural inference is still not modelled.
  Selftest (5/5): clean->buggy finds 5 regressions and 0 fixes, buggy->clean the inverse, and the
  same input twice yields an EMPTY delta (a delta tool that always reports something would be
  useless).

- `tools/abi_check.py` + `make abi-check` (CHECK) / `make abi-selftest` (META) — **defect #483, the
  machine ABI**. `kernc audit` turned out to be a DEMO of SMT theories (UNSAT core, arrays, CHC),
  not a code auditor: the real funnel and findings live in the Python frontend. So the versioned
  ABI belongs THERE (`--xray-json`), which is exactly the «matryoshka» split (frontend + kernc
  backend). Without an ABI every consumer (CI plugin, MCP server, a Go/Rust wrapper) had to parse
  TEXT with regexes — i.e. to repeat the «the report says something other than what happened»
  class on their side. The contract is explicit: `schema_version: "1.0"`, `summary` (files/total/
  checked/trivial/skipped/findings/unreadable), structured `findings[]` (file/type/details),
  `skipped[]` and `notes[]` histograms. The gate requires EXACTLY ONE JSON object on stdout (a
  leaked log line breaks every consumer at once), the required keys, `summary.findings ==
  len(findings)`, a non-empty `type`, and the funnel identity `checked+trivial+skipped == total`.
  `--selftest` proves the validator refuses SIX breakage types; can-fail `abi-json` leaks a log
  line into stdout and the gate reddens in 1 s. NOTE: `--json` already existed for CONTRACT
  reports, so the new flag is `--xray-json` — reusing the old name would have silently changed an
  existing interface.
- `tools/mutation_lock.py` + `make mutation-lock-selftest` (META) / `make mutate-full` — **defect
  #482**: the mutation tools shared ONE hard-coded lock `/tmp/kern_mutation.lock`, i.e. one lock
  PER MACHINE, so a 40-minute `mutate_zig` sweep blocked `canfail` — and therefore EVERY gate
  check, even ones about unrelated code. MEASURED as real friction: the sweep in this session had
  to be paused three times just to run a single can-fail case. The lock now names the WORKING TREE
  (`/tmp/kern_mutation.<sha256(root)[:12]>.lock`): inside one tree `canfail` and `mutate_zig` still
  exclude each other (defect #88b stays fixed — both edit the sources), while separate git
  worktrees get separate locks. `make mutate-full` runs the full sweep in its own worktree and
  copies the log back. The selftest proves all four properties with REAL flocks: different trees
  have different paths, the same tree returns `BUSY`, ANOTHER tree stays free, and after closing
  the lock is free again.
  HONEST NOTE: the first attempt exited `rc=2` because the worktree was created at `HEAD` *before*
  this fix, so it still used the machine-wide lock — the defect reproduced itself while being
  fixed. The sweep must therefore start AFTER the commit that contains the fix.

- `src/verifier/proof_check.zig` — **defect #479**: the S-expression depth ceiling was TOO LOW for the
  native build. MEASURED on `audits/smt2/kernel_align_deepjit_align_guarded.smt2`: Z3's proof of a
  32-bit alignment bit-blast has **depth 14 113** (1.29 MB) while `MAX_SEXP_DEPTH` was **12 288**,
  so a formula the solver had PROVED was refused with «вывод ГЛУБЖЕ предела вложенности» and the
  checker reported **0 steps**. The limit is now target-split: **16 384 native** (2 271 of headroom
  over the measured need) and **4 096 on wasm** (a browser stack is tiny, deep parsing there stays
  dangerous). With the fix the SAME file parses into **21 758 steps** and the refusal moves to the
  REAL reason (`premises_unbound`, see #480), i.e. the checker now ACCOUNTS for deep BV proofs
  instead of blanket-refusing them. `zig build test` rc=0, `zig build wasm` rc=0.
- `src/verifier/proof_check.zig` — **named boundary #480 (OPEN)**: raising the depth exposed what
  `premises_unbound` really means for `QF_BV`. On the same file the checker now reports
  `посылок 1/794 | ДОВЕРЕННЫХ 19 865 | шагов 21 758` — because in a bit-blasted proof the
  `asserted` steps are **clauses of the bit-blast** (`(or (not k!N) …)`), not the 3 contract
  assertions. Binding them to the contract is conceptually wrong; they must be classified as
  tautologies/definitions, and each of them rests on the `k!` axioms anyway (91 % trusted). This
  CONFIRMS the LIMITS claim that BV is not proof-carrying, now with numbers.
- `tools/kern_contracts.py` — **defect #478**: `[EQUIVALENT?]` printed a HARD-CODED reason
  `(premises_unbound)` regardless of what the checker actually said. MEASURED: for the deep BV
  formula the checker says `[!] причина: вывод ГЛУБЖЕ предела вложенности парсера
  (MAX_SEXP_DEPTH)`, while the report blamed premise binding — class #370/#371 («the report says
  something other than what happened»): the reader looks for a premise-binding defect that is not
  there. The reason is now parsed from the checker output (verified against real output, not a
  guess).

- `tools/spawn.py` + `tools/spawn_check.py` + `make spawn-check` (CHECK) / `make
  spawn-selftest` (META) — **defect #477, the subprocess choke point**. The class «subprocess
  without a limiter» fired THREE times: `#464` (solver timeout), `#466` (`z3` missing from
  `PATH` → silent SKIPs), `#470` (no memory ceiling, `kernc prove` grew to 5.4 GB). MEASURED by
  AST over `tools/*.py`: **170** `subprocess.*` calls, of which **51 had NO `timeout=`** — i.e.
  51 places where a hung binary blocks a gate FOREVER, without a verdict and without a reason.
  `spawn.run()` is the blessed path: timeout ALWAYS (default 900 s), the `z3` directory from
  `z3bin.find_z3` in `PATH` (single source of truth #353), `RLIMIT_AS` on the child, and NAMED
  outcomes (`124` timeout, `125` memory/signal). Its `--selftest` proves all five cases with
  real subprocesses (normal / timeout / memory cap / signal / foreign exit code). Three real
  sites were fixed rather than ratcheted: the `z3 --version` probe and the
  `trust_scorecard` call in `kern_contracts.py`, and the `zstd` unpack in
  `smtlib_proof_check.py` — each now names its timeout. The gate is a RATCHET (baseline 51,
  target 0): growth reddens it, improvement prints «lower the baseline», and the debt list is
  printed every run so it stays visible. Can-fail case `spawn-timeout` reddens the gate in 1 s.
- `tools/xray_precision_check.py` + `make xray-precision` (CHECK) — **defect #475, the
  PRECISION gate**. Precision on third-party code was measured at **56 %** on
  `TheAlgorithms/Rust` (18 findings, 8 false) and, worse, **21 false accusations on 50
  CORRECT `QuixBugs` programs** — and a false accusation is the worst outcome (worse than a
  miss). The gate is two-sided and hermetic: `precision_clean/` (py+rs+c, every guard style:
  if-return, if-else, while, assert, range check, f64) must yield **0 findings**;
  `precision_buggy/` must yield **exactly 5** with every expected name present (a missed
  finding = lost signal); `precision_known_fp/` must yield **exactly 1** — a RATCHET for
  **`#476`**, so when that defect is fixed the gate goes red and demands the function be moved
  back into `precision_clean`. External corpus (`QuixBugs/correct_python_programs`) is checked
  when present against a NAMED baseline (`EXT_FP_BASELINE = 21`, target 0): growth reddens the
  gate, improvement prints "lower the baseline". A missing corpus is a NAMED skip, never a
  silent green. Can-fail case `xray-precision` drops the `while` guard and the gate reddens in
  18 s.
- **Named boundary `#476` (OPEN, not fixed)**: `len(<literal list>)` in a guard is not unified
  with the literal length, so `data = [1,2,3,4]; if 0 <= i < len(data): return data[i]` is
  accused with the counterexample `i = -1`. It is NOT hidden in an allow-list: the function
  lives in `tests/fixtures/precision_known_fp/` and the gate asserts exactly one finding there,
  so the debt is counted and the ratchet works in both directions.

  formulas whose proof the checker verified only PARTIALLY. MEASURED on
  `audits/smt2/hex_index_deepjit_hex_hi.smt2`: the solver says `ДОКАЗАНО`, the proof checker
  says `[PROOF PARTIAL] … ДОВЕРЕННЫХ 15` (bit-blast axioms `k!` — an unprovable free constant,
  so a strict offline check is impossible). That is TWO different claims under one word, and to
  a buyer of «proof-carrying artifacts» it reads as a promise BV does not keep. `measure()` now
  returns `(verdict, trusted)` and every `PROVEN` row carries the count: `trusted 0` (solver and
  checker agree), `[PROOF PARTIAL] trusted N`, or `` `trusted ?` `` when the checker reports no
  counter at all (MEASURED: 44 formulas → **13** `trusted 0`, **11** PARTIAL, **20** without a
  counter — the last group is `ДОКАЗАНО (допущено)`, a weaker claim that the table previously
  hid behind `PROVEN`). Gate `make evidence-trust` (CHECK) + `make evidence-trust-selftest`
  (META): `PROVEN` without a count is a violated claim; the selftest proves all three breakage
  types are caught (and that an empty table is a failure, not a pass); can-fail `evidence-trust`
  turns the gate red in 0 s.
- `tools/audits_run.py` — **defect #470**: the audit harness put NO memory ceiling on its
  subprocesses. MEASURED: `make audits` → `kernc prove` on `audits/rust-core/midpoint.rs` grew
  to **5.4 GB and kept growing** (a 300 s timeout existed, a memory bound did NOT), and with up
  to `KERN_AUDIT_WORKERS` (6) of them at once a «proof run» could evict the whole machine.
  `run()` now sets `RLIMIT_AS` in the CHILD via `preexec_fn` (`KERN_AUDIT_MEM_MB`, default
  2048), inherited by grandchildren (`kern_contracts.py` → `kernc` → `z3`), and turns the
  outcome into a NAMED one (`rc=125`): (a) allocator said so (`out of memory` /
  `error.OutOfMemory` / `MemoryError` / `Cannot allocate memory`), (b) or the child died by a
  SIGNAL (`rc<0`, `SIGSEGV`/`SIGABRT`/`SIGKILL`) — the usual RLIMIT_AS outcome, which used to
  leak out as a raw `-11` with the cause lost. Non-memory failures are passed through unchanged
  (no false accusation). Belnap `N`, not a verdict: `[N]` rows are printed and the `.kern` claim
  status becomes `unknown` (`src/next/parser.zig` rejects an unknown status string — writing raw
  `oom` would break parsing of the project, so the honest name is `unknown`, and the cause stays
  visible in the report).
- `tools/audits_run.py` — **defect #469b (same class as #469a)**: the harness did not pass the
  SOLVER to its children. MEASURED under `make audits` (`PYTHON ?= python3`): `kernc prove`
  printed `[!] z3 недоступен`, so all 44 corpus formulas got UNKNOWN → `proven 0 | refuted 0` →
  the anti-vacuum guard failed with `rc=2` and the certificate rows could not be counted.
  `run()` now prepends the z3 directory (`z3bin.find_z3`, single source of truth #353) to `PATH`;
  a missing solver still yields a NAMED failure instead of a silent «unknown».
- `tools/real_cases_check.py` — **defect #469a**: the expectations lagged behind the honest
  verdict introduced by **#433**. `qfs_sanitizer.smt2` (QF_S) and `ieee754_nan.smt2` used to
  report a FALSE `[PROOF VERIFIED] trusted: 0` because `.structural_only` steps of `th-lemma`
  never called `markTrusted`; after #433 they honestly report `[PROOF PARTIAL]`
  (`trusted > 0`, `unbound = 0`, `holes = 0`), so the gate went red with `rc=2`. The rows now
  assert the measure of #433 instead of the old wish, and the gate got its own solver `PATH`.
- `tools/kern_contracts.py` — **defect #469b (findings counter)**: `[BOUNDS?] … — это
  НЕОПРЕДЕЛЁННОСТЬ (N), не находка` was still appended to `found`, so an honest Belnap `N`
  inflated the finding count (MEASURED on `deepseek-ai/DeepJIT`: `находок 3` instead of 1
  `[SMELL]`, and `findings 1` on `tests/test_ascend.py`). Those lines now go to `notes` — the
  counter can no longer read `N` as `F`. A can-fail case `xray-bounds-note` proves the gate goes
  red (a `while` body loses `notes`).
- `tools/kern_contracts.py` — **defect #469c**: `.tsx`/`.jsx` were not scanned, so 29–30 files of
  `deepseek-ai/dsh-superagent-prototype` stayed invisible. Both extensions are in `CLIKE_EXT`
  (and therefore in `_XRAY_EXTS`); MEASURED over the agent's 30 `.tsx` files: 171 files scanned,
  122/308 functions analysed, **0 findings** — JSX markup does not break the function splitter.
- `tools/xray_check.sh` — a TWO-SIDED regression gate for **#468**: `examples/array_bounds.py`
  gains `get_assert_guard`, `get_set_assert_guard`, `get_try_assert_guard`; the `xray_exts` fixture
  gains `h.hpp` (counted AND analysed, not merely counted). At `HEAD` the gate yields 2 findings,
  with the fix 0; a new can-fail case `xray-assert-guard` proves it can go red by DISABLING the
  `ast.Assert` branch (not by breaking a signature — that would be a vacuous crash, lesson #466).

## [2.8.1] — 2026-11-01

Tack 2.2 / 2.3: **50 journal entries closed (#399..#448), `Open technical defects: 0`**.
Every number below was produced by a command in the repository (see `docs/METRICS.md`).

### Added

- `tools/funnel_accounting.py` — the coverage funnel's arithmetic under locked contracts
  (`@kern:requires`/`@kern:ensures`, checked by `kernc`, sealed in `contracts.lock.json`).
- `tools/clike_ir_check.py` — a table-driven IR gate (19 Int + 5 BV + 2 safeguards) plus an
  instant IR snapshot of both corpora; `tools/mutation_lock_check.py`;
  `tools/source_hygiene_check.py` (the `0x08` ratchet).
- `docs/PLAN_takt22.*` and `docs/PLAN_takt23.*` — self-contained plans with acceptance
  criteria, safeguards and boundaries, kept under RU/EN parity.

### Changed

- `--xray` coverage of functions with branches: `cmark-gfm/src` `41.8% -> 95.1%`
  (`76/182 -> 173/182`), `actions/toolkit` `12.6% -> 93.5%` (`72/77`), with **0 false alarms**.
  The TS denominator was cleaned of 308 `await`/`throw` calls (`458 -> 150`);
  `scanners.c` is **5.3x faster** (SMT memoisation).
- `src/verifier/proof_check.zig`: **6 of 7** `smtlib-proof-check` tasks now pass with
  `trusted: 0` (was 3) and **0 rejected proofs** (`unbound = 0` everywhere); trusted steps on
  `QF_BV/add_three.4_bit` dropped **`2970 -> 646`**; the report identity
  `checked + trusted + other + holes == steps` holds to the unit.
- `src/next/`: the Belnap conflict `B = JOIN_K(T, F)` (`conflicted`) is representable in the
  SQLite catalogue (CHECK generated at compile time from `ast.Status`) and is no longer
  collapsed into `"refuted"` in `agent_packet.json`.
- `--anti-cheat`: rules moved from syntax to context; noise over its own 132 files of
  `tools/*.py` dropped **31 -> 0** while all **12/12** classes stay caught.
- 8 tools of `tools/` now honour `$ZIG`; `kernc --help` prints 27/27 tokens to stdout.

### Fixed

- Journal entries `#399..#448`, including: a falsely inflated coverage denominator (`#410`),
  a silent `0 findings` without a solver (`#407`), eight control bytes `0x08` instead of
  `` (`#413`), a false HAVOC model `!f(c)` (`#414`), a crash on `xml.c` (`#412`),
  vanishing steps in `storeinv` (`#433`), the report identity (`#432`), the three axioms of
  the theory of arrays (`#445`), a 139-level `let` nest (`#443`), and the sealing tool's
  raw traceback (`#448`).


## [2.8.0] — 2026-10-27

### Added

- **Native Zig AST verifier (`kernc verify-zig <file.zig>`, #375):** a built-in
  `std.zig.Ast.parse` frontend INSIDE the static `kernc` binary (0 Python, 0
  regexes). It extracts `/// @kern:requires` and `/// @kern:ensures` from
  `.doc_comment` tokens across all four `fn_proto` forms, models
  `i32`/`u32`/`i64`/`u64`/`usize`, generates safety obligations for `+`/`-`/`*`,
  unary `-MIN_INT`, division by zero and the `MIN_INT / -1` trap
  (`@divTrunc`/`@divFloor`/`@rem`/`@mod`), and suppresses overflow obligations on
  the modular/saturating operators (`+%`, `-%`, `*%`, `+|`, `-|`). MEASURED:
  `addGuarded`/`divOk` PROVEN, `addWrapOk` PROVEN with **0** obligations,
  `addBad` REFUTED with the counterexample `a = INT_MIN, b = -1`.
- **Native theory CLI (`kernc theory <file>`, #376):** a file-based CLI entry
  point for the native Zig engines (`arrays` McCarthy `QF_AX`, `absint`
  `join`/`widen`/`narrow`, `dtmc` stochasticity and reachability) - previously
  they ran only on strings hardcoded inside `kernc audit`.
- **SMT-COMP proof-checking track (`make smtlib-proof-check`, #366, #371-#373):**
  23 official SMT-LIB tasks across `QF_LIA`, `QF_BV`, `QF_AX` and `QF_S`;
  `proof_check.zig` audited 7 official UNSAT derivations (7,945 steps, 0 holes)
  and three official tasks were proven with **`trusted: 0 | holes: 0`**.
- **SV-COMP executable witness validation (`make svcomp-witness-check`, #367,
  #368, #374):** 37 UNMODIFIED official tasks across 4 categories; UNSAFE
  witnesses are confirmed by two external oracles - the compiler (`-Woverflow`)
  and a run under `gcc -fsanitize=undefined,address`.
- **MBPP+ live-Python oracle (`make mbpp-xray-check`, #377, #378):** `[CRASH
  PATH]` accusations are confirmed by a LIVE Python run on the found
  counterexample instead of trusting the test table.
- **Sub-expression overflow detection in `--xray` (Path C, #368):** intermediate
  signed overflows inside compound expressions (`J = 1.00` on the SV-COMP
  overflow regression).
- **Journal hierarchy invariant (`orphans()`, #370):** every sub-row `| **N.k** |`
  must sit under its own header `| **N** |` (RU and EN, 338 records).

### Fixed

- **#371:** trailing `(exit)` is stripped before `(get-proof)` on official
  SMT-LIB files; `MAX_SEXP_DEPTH` raised 4,096 -> 12,288 (the measured safe
  ceiling) with an explicit `TooDeep` reason instead of blaming the solver.
- **#372:** `kernc prove` prints `[PROOF VERIFIED]` strictly when `trusted == 0`,
  otherwise `[PROOF PARTIAL] ... NOT VERIFIED`.
- **#373:** the 1 MB read limit in `kernc smtlib` is gone - official files of
  1.6 MB were silently skipped and reported as "0 files".
- **#374:** `#include_next <assert.h>` in the SV-COMP witness harness - without
  it our own stub shadowed the system header and 6 official `array-examples`
  tasks would not build (the category was VACUOUS).
- **#377:** a false division-by-zero accusation inside `for i in range(n * k)` -
  the loop-entry non-emptiness guard is now emitted (for a product `A * B` the
  sound ring-of-integers property gives the linear `(distinct A 0)` /
  `(distinct B 0)`).
- **#378:** assignment values (`x = ...`, `x += ...`) were never crash-walked, so
  the whole loop body was a blind spot of `--xray`.
- **#379:** `cyberseceval_check.py` is now explicitly labelled an external
  AST/regex BASELINE (0 `kernc`/`z3` calls); real CWE verification lives in
  `cwe-twins-check`, `svcomp-witness-check` and `smtlib-proof-check`.

### Measured

- 449 core Zig tests (was 436), 172/172 CHECK gates proven able to fail,
  208 non-vacuous can-fail cases, 223 registry targets, journal records
  #1-#379 (338 rows, RU == EN).
- Three blind spots of `EvalPlus MBPP+` confirmed by a live run: `Mbpp/265`,
  `Mbpp/292`, `Mbpp/422` pass BOTH base `MBPP` and the 80x `MBPP+` yet raise
  `ZeroDivisionError` on `n = 0` / `b = 0` - with 0 false accusations.


## [2.7.3] — 2026-10-26

Минорный релиз **измеримых гарантий на внешних задачах**. Пять этапов
Генерального плана закрыты и измерены; каждый пункт ниже — команда, которую
можно повторить.

### Added

- **`make real-cases-check` (ЭТАП 5) — измеренная матрица возможностей.**
  **17/17 возможностей закрыто** (у каждой ОБЕ половины: `bad` пойман точным
  маркером И `good` ДОКАЗАН) и **анатомия одной функции 6/6 режимов**. Режим
  движка назван в таблице (QF_LIA / QF_BV / QF_SLIA / Int+Bool). Документы
  `docs/REAL_WORLD_CAPABILITIES.md` + `.ru.md`.
- **`make cwe-juliet-check` (ЭТАП 3) — парный бенчмарк NIST Juliet-style.**
  **Индекс Юдена `J = 1.00`**, **счёт SV-COMP `27/27`**, `TP 9/9 · TN 9/9 ·
  FP 0 · FN 0` на девяти классах MITRE CWE. Документы `docs/CWE_COVERAGE.md` +
  `.ru.md`.
- **`make ai-traps-check` (ЭТАП 4А) — полигон из шести ИИ-ловушек.**
  **6/6 перехвачено СВОИМ маркером, 6/6 честных близнецов доказаны.**
  Документы `docs/AI_TRAPS_SHOWCASE.md` + `.ru.md`.
- **`make quixbugs-diff-check` (ЭТАП 4Б).** **`false_equivalent = 0`**
  (40/40 `DIVERGED`) и **`false_diverged = 0`** на контрольных парах.
- **Двусторонний инвариант `CASE_TARGET` (#358).** Каждый кейс обязан быть в
  таблице, каждое значение — вести в существующую цель; мета-тест 3 ветки.
  Инвариант сразу нашёл семь кейсов без записи и одну запись в никуда.

### Fixed

- **#361 — `--diff-equiv` падал на не-Python входе.** `parse_bodies` теперь
  маршрутизирует по расширению: Python через `ast`, C-like (`.c .h .zig .rs
  .go .ts .js`) через `parse_clike` с их семантикой из `VALUE_SEMANTICS`.
  **Измерено двусторонне:** C-контроль «файл против себя» → `[EQUIVALENT]`;
  багованная C-пара → `[DIVERGED]` с контрпримером `hi = 0, v = 1`. Нелинейные
  тела теперь **называют причину** (`тело требует QF_BV …`).
- **#365 — метка «QF_FP» в матрице была ложной.** Фикстура
  `ieee754_nan.smt2` моделирует NaN парой **Int + Bool**, а не сортом
  `(_ FloatingPoint 11 53)`; `trusted: 0` там верен для МОДЕЛИ. Настоящий QF_FP
  даёт **213 доверенных шагов** (`METRICS.md` §89.1), где заявлять `trusted: 0`
  нельзя. Метка исправлена; директива `@kern:float` **не реализована** — это
  названо, а не подделано.
- **#359, #360, #362, #363, #364** — дефекты, найденные собственными гейтами
  этого цикла (см. журнал `docs/CAPABILITY_STATUS.md`).

### Upstream

- **[`TheAlgorithms/C#1596`](https://github.com/TheAlgorithms/C/pull/1596)** —
  `math/lcm.c`: переполнение `a * b` (при `50000, 50000` печатает **`-35899`**
  там, где истинный НОК `50000` влезает в `int`) и `SIGFPE` при `(0, 0)`.
  Патч `docs/pr/lcm_fix.patch`, оба дефекта воспроизведены `gcc`, исправление
  перепроверено сборкой `-fsanitize=undefined`. Третий отчёт в апстрим после
  `#1595` (C) и `#1075` (Rust).

### Known limitations

- Настоящий **QF_FP** (сорт `(_ FloatingPoint 11 53)`) даёт **213 доверенных
  шагов** пруф-чекера; `trusted: 0` там не заявляется. Директивы `@kern:float`
  в исходнике **нет**.
- `--diff-equiv` сравнивает в Int-теории: нелинейные тела (произведение двух
  переменных, битовые операции) в сравнение не попадают и **называют причину**.
- Режим `--gen-tests`/`--concolic` работает по ветвям: у функции без ветвей
  честно 0.

### Added

- **Артефакты 3-го внешнего PR: `TheAlgorithms/C math/lcm.c` (ШАГ 3 Захода Б).**
  `docs/pr/lcm_fix.patch` + `docs/pr/thealgorithms_c_lcm_PR.md`. **Оба дефекта
  воспроизведены `gcc` на нетронутом файле:** (1) при `a = b = 50000` промежуточное
  `50000 * 50000 = 2500000000 > INT_MAX` — UB в C11, печатает **`-35899`** вместо
  истинного `50000` (ответ в `int` влезает с запасом ~40 000 раз!); (2) при
  `a = b = 0` `gcd(0,0) == 0` → деление на ноль → **SIGFPE**. **Исправление:**
  гард нуля + **деление ДО умножения** `(a / gcd(a, b)) * b`. **Проверено после
  патча** (`-fsanitize=undefined`): `50000,50000 → 50000`, `0,0 → 0`, контроль
  `15,20 → 60` и `12,18 → 36` не изменился, диагностик санитайзера нет. Патч
  накладывается чисто (`git apply --check`). Граница: если сам НОК не влезает в
  `int`, результат непредставим — это следствие типа, и здесь не заявлено как
  исправленное. PR подготовлен, не отправлен.
  задачах.** `tools/real_cases_check.py`. **ИЗМЕРЕНО: 17/17 возможностей закрыто**
  (у каждой доказаны ОБЕ половины: `bad` пойман точным маркером И `good`
  ДОКАЗАН) и **анатомия одной функции 6/6 режимов** (`--xray` → контракт
  `REFUTED` → `explain` read-only → `--heal` `T (1,0)` → `--diff-equiv`
  `DIVERGED` на точке бага → `--gen-tests`/`--concolic` живые тесты). Режим
  движка назван в таблице (QF_LIA vs QF_BV vs QF_SLIA vs QF_FP). Документы
  `docs/REAL_WORLD_CAPABILITIES.md` + `.ru.md` (пара внесена в `docs-parity`),
  мета-тест 4 ветки, невакуумный кейс `real-cases`. Границы названы: IEEE-754
  NaN поддержан на уровне SMT-фикстуры, а не директивой `@kern:float` в
  исходнике; режим 6 работает по ветвям.
- **`make quixbugs-diff-check` (ЭТАП 4Б) — честный замер QuixBugs через
  `--diff-equiv`.** `tools/quixbugs_diff_check.py`. **ИЗМЕРЕНО на полном корпусе
  (40 пар):** `DIVERGED 40 | EQUIVALENT 0 | false_equivalent 0` — ни одна
  багованная пара не объявлена эквивалентной. **Контрольная половина не зависит
  от датасета:** пары `(correct, correct)` обязаны давать `EQUIVALENT`
  (измерено `false_diverged 0`, падений инструмента 0). Без датасета половина с
  40 парами честно пропускается вслух, но контрольная выполняется ВСЕГДА — гейт
  не бывает вакуумным. Мета-тест 4 ветки, невакуумный кейс `quixbugs-diff`.
- **`make ai-traps-check` (ЭТАП 4А) — полигон из шести ИИ-ловушек.**
  `tools/ai_traps_check.py` + фикстуры `audits/ai_traps/`. **ИЗМЕРЕНО: 6/6
  ловушек перехвачено СВОИМ маркером, 6/6 честных близнецов доказаны.** Классы:
  Contract Tampering (паттерн DeepSeek/GLM) → `[SECURITY] контракт ИЗМЕНЁН`;
  Vacuous Precondition → `[VACUOUS] … B4: N, e = 0`; Point-Patch Overfitting →
  `[КОНТРПРИМЕР] x = -10`; Runtime Reward Hacking → `CHEAT DETECTED` (5/5);
  MCP Poisoning/Rug-Pull → `MCP RUG-PULL DETECTED` + `PROMPT INJECTION` +
  `INVISIBLE UNICODE`; CEGIS Self-Healing → `T (1,0)`, крашей 1 → 0, объяснение
  read-only. **Два правила строгости:** (А) точный маркер, а не `rc != 0` — иначе
  опечатка в фикстуре засчиталась бы за перехват; (Б) честный близнец обязан быть
  `PROVEN`/`PASS`, `SKIP` не считается. Документы `docs/AI_TRAPS_SHOWCASE.md` +
  `.ru.md` (пара внесена в `docs-parity`), мета-тест 4 ветки, невакуумный кейс
  `ai-traps`.
- **`make cwe-juliet-check` (ЭТАП 3) — парный бенчмарк NIST Juliet-style по девяти
  классам MITRE CWE.** `tools/cwe_juliet_check.py` + девять пар `bad`/`good` в
  `audits/cwe_juliet/`, прогнанных через собственные движки KERN. **ИЗМЕРЕНО:**
  `TP 9/9 · TN 9/9 · FP 0 · FN 0`, **Индекс Юдена `J = 1.00`**, **счёт SV-COMP
  `27 / 27`, штраф 0**. Классы: CWE-190, 191, 369, 682, 680, 125/193, 22, 89/285,
  208. Документы `docs/CWE_COVERAGE.md` + `.ru.md` (пара внесена в `docs-parity`),
  мета-тест 4 ветки, невакуумный кейс `cwe-juliet`. Границы названы: это не
  полный SARD (девять классов, а не тысячи случаев); CWE-680 и CWE-190 делят одно
  обязательство типа (различает контекст); «ВНЕ ПОДМНОЖЕСТВА» не считается
  доказательством `good`.
- **Двусторонний инвариант `CASE_TARGET` (ШАГ 0, класс #356 закрыт).** Каждый
  кейс обязан быть в таблице, каждое значение — вести в существующую цель
  (цель Makefile либо шаг `zig build`, сверенный с `build.zig`). Мета-тест 3
  ветки, невакуумный кейс `casetarget-gap`. Инвариант сразу нашёл семь кейсов без
  записи и одну запись, ведущую в никуда (`"kern-invariant": "kern"`).

### Fixed

- **#359 — два дефекта САМОГО нового гейта, найденные его первым прогоном.**
  (а) Классификация `contracts` считала обе ветви по выводу `bad`, поэтому `good`
  «доказывался» выводом уязвимого файла — метрика, считающая не то, что
  заявляет. (б) Фикстура границ использовала литерал списка вместо
  документированной аннотации `# @kern:len(data) = N`, из-за чего защищённый
  `good`-близнец обвинялся с контрпримером `kern_len_data = 9` при 8 элементах —
  ложное обвинение.

### Fixed

- **#355 — гейт `artifact-check` не мог пройти НИ РАЗУ, а запись #285 утверждала
  обратное.** `detect_version` искал версию регекспом `releases/download/(vX.Y.Z)/`
  — **со слэшем**, которого в README нет ни в одном теге (`v2.6.3`, `v2.6.4`,
  `v2.7.0`, `v2.7.1` проверены). Поэтому обе цели падали на первом же звене, а
  #285 объясняла удаление кейсов тем, что «README объявляет хеш, и цепочка жива» —
  при том что хеш из README убрал #250. Класс #312/#350/#354: запись противоречит
  коду. **Исправлено:** регексп принимает фактическую форму и не путает `v2.7.2`
  с `v2.7.20`; источник хеша — опубликованный `SHA256SUMS`; offline-режим сверяет
  `--version` сборки с версией README; байтовое сравнение с CI-ассетом переведено
  в сведение с названной причиной; добавлен `--selftest` (6 веток), он идёт первым.
  **ИЗМЕРЕНО:** `artifact-check` rc=0 — asset v2.7.2 `7028931f…` == `SHA256SUMS`;
  `artifact-check-offline` rc=0. Кейс `artifact-offline` ВОЗВРАЩЁН в харнесс
  (подмена версии в README краснит ворота, rc=2 за 0 с) — защита от #82 снова
  действует, а не заявлена.

## [2.7.2] — 2026-10-25

Патч-цикл «Этап 1–2 (Ядро и Семантика) до нуля»: закрыто **14 дефектов**, включая
мину **звучимости в собственном пруф-чекере** (найдена ревизией плана и подтверждена
измерением Z3), дрейф канона и три класса ложных срабатываний на собственном коде.

### Fixed — звучимость ядра

- **#349 — `evalConstInt` делил по-разному: ложное тождество + ПАНИКА + мёртвый guard.**
  Прежняя реализация считала `div`/`mod` как floor при ЛЮБОМ знаке делителя,
  а в SMT-LIB2 для сорта `Int` деление **евклидово**. ИЗМЕРЕНО в Z3: `(div 1 (- 2)) = 0`,
  `(mod 1 (- 2)) = 1`, `(div (- 7) (- 2)) = 4` (не `3`). Следствия: **(1)** `(= (div 1 (- 2)) (- 1))`
  принималось как **доказанное**; **(2)** `@mod(a, b)` при `b < 0` в Zig **паникует**
  («modulus is negative»); **(3)** защита от переполнения `-@divFloor(a, -b)` была **мёртвым кодом** —
  литерал `-9223372036854775808` (MIN) вообще не парсился (модуль `2^63` не
  влезает в `i64`), и тест «проходил» по неверной причине.
  Дополнительно: `+%`/`-%`/`*%` (wrapping) — та же тихая подмена математики
  (`(= (+ MAX 1) MIN)` принималось бы как тождество, а в SMT это `2^63`).
  **Исправлено:** евклидовы `div`/`mod` при `b < 0`; явный разбор MIN в обеих
  формах; checked `std.math.add/sub/mul` с отказом на переполнении; guard
  `q == minInt → null` (ответ Z3 для `div(MIN, -1)` = `2^63` — ВНЕ `i64`).
  **Звучимость по §95.4:** четыре теоремы в `formal/FarkasSoundness.lean`
  (`0 sorry`, `lean` rc=0), включая `euclid_neg_denom_unique` — через
  **ядерную** `Int.ediv_emod_unique'` с условием `b < 0`.
  **Тесты:** 8+ точек, негативные обязательны (`(= (div 1 (- 2)) (- 1))`
  отвергается; `(= (div (- 7) (- 2)) 3)` отвергается), guard на ВЫЧИСЛЯЕМОМ MIN,
  три случая переполнения. `evm-proof-check` — по-прежнему `trusted: 0 | holes: 0`.

- **#353 — семь мест брали свойство языка из ЛИТЕРАЛОВ, а не из таблицы.**
  Обязанность «знаковое переполнение при `MIN / -1`» и «есть ли границы типов»
  выводились из расширения файла (`suffix in CLIKE_EXT`), а не из
  `ValueSemantics`. Любой новый язык с иной семантикой молча получал свойства
  C. **Исправлено:** таблица расширена полями `signed_min_div_trap`,
  `signed_min_neg_trap`, `allow_bv_fallback`, `bounded_ints`; код **читает** их.
  **KILL CRITERIA соблюдены:** `codecheck` остался `TP=6, TN=6, FP=0, FN=0`,
  `contracts` — `11 доказано / 4 нарушено`. То есть рефакторинг не сдвинул ни
  одного вердикта.
- **#350 — КАНОН врал о состоянии ядра.** `docs/CHARTER.md` §3 и таблица
  L4/L5 утверждали «6 доказано, 2 не покрыты» и «пруф-чекер вывод отвергает»,
  тогда как `make charter-check` давал `8 | 8 | 0` (класс #303 закрыт 22.10.2026).
  Тот же класс, что #312/#335, но в САМОМ уставе проекта. **Исправлено:**
  таблица → PROVEN, §3 переписан в **историю границы** (не удалён — удалять
  неудобное и есть тот failure mode, против которого проект построен), плюс
  новый гейт `charter-text-check`, сверяющий ТЕКСТ канона с фактическим
  `EXPECTED_UNCOVERED` (5 веток мета-теста).
- **#348 — харнесс МАСКИРОВАЛ вердикт.** `sh_out` вызывал
  `subprocess.run(text=True)` без `errors=`, поэтому любой байт, не сложившийся
  в UTF-8, валил кейс исключением — и прятал настоящий вердикт инструмента.
  Измерено полным прогоном: `ОШИБОК КЕЙСОВ 1` → `0`. Исправлено `errors="replace"`.

### Fixed — парсеры и фронтенды

- **#325 — Allman-стиль (`{` на следующей строке) давал МОЛЧАЛИВЫЙ пропуск.**
  `RE_FN_FN`/`RE_FN_TS`/`RE_FN_GO` требовали `{` в конце строки заголовка,
  поэтому функция с перенесённой скобкой не распознавалась вовсе («всего 0»),
  хотя сбор тела уже умел следующую строку. **Исправлено:** `{` необязательна,
  но строка обязана на ней **закончиться** (`$` защищает от `fn f(a: i32) -> i32;`).
  ИЗМЕРЕНО: Allman → 1 проверка; контроль same-line не изменён. Фикстуры
  `audits/codecheck/zig_allman.zig` (T) и `rust_allman.rs` (F), матрица
  `TP=6, TN=6, FP=0, FN=0`.
- **#322 — три класса ЛОЖНЫХ `[BOUNDS PATH]` в Python.** Само-применение
  `--xray tools/` давало 6 кандидатов, все защищённые. Закрыто: (1) гард в
  условном выражении сужает путь своей ветви; (2) ранний выход `continue`/`break`
  теперь считается выходом из ветви (не только `return`/`raise`); (3) индекс от
  переменной, изменённой в цикле, понижен до честного `[BOUNDS UNKNOWN]`
  (инварианты `while` не моделируются, #315) вместо недостижимого свидетеля;
  (4) согласованы символы длины (`len__b` ↔ `kern_len_b`), распознана граница
  `range(start, min(..., len(arr)))`. ИЗМЕРЕНО: `6 → 1` кандидат, и остаток
  осмыслен.
- **#342 — `lang="evm"` не выставлялся НИ ОДНИМ путём разбора** (строка таблицы
  была мёртвой). **Исправлено:** директива `# @kern:lang evm` / `// @kern:lang evm`
  переключает семантику; проверено **двусторонне** — с директивой `2 PASS`,
  без неё тот же код **нарушает** контракт (иначе директива ничего не меняет).
  Гейт `make evm-lang-check`, невакуумный кейс.
- **#344/#341 — развёртка `define-fun` + константная арифметика.** Z3 в выводе
  ПОДСТАВЛЯЕТ тело объявленной функции, а контракт содержит ВЫЗОВ — посылка не
  привязывалась. Теперь чекер читает `define-fun` из ШАПКИ SMT-файла
  (`loadFunDefs`) и раскрывает вызовы подстановкой аргументов
  (`funExpand`/`substParams`). Две ошибки первой версии названы в реестре:
  `parseSexp` разбирает ОДНО выражение (а SMT-файл — последовательность), и
  общая ветка превращала АТОМ в пустой список. **ИЗМЕРЕНО**: было
  `посылок 0/1 | ДОВЕРЕННЫХ 1 | вывод ОТВЕРГНУТ` → стало `посылок 1/1 |
  ДОВЕРЕННЫХ 0 | дыр 0 | [PROOF VERIFIED]` на всех трёх EVM-тождествах.
  Гейт `make evm-proof-check` (CHECK), невакуумный кейс `evm-fundef`, три
  Zig-теста (включая негативные: подделанная подстановка не проходит,
  неизвестная функция не «угадывается»).


### Fixed — инфраструктура и CI

- **#345 — кейс `temp-isolation` был ВАКУУМНЫМ.** Кейс дописывает
  неизолированный путь `/tmp/kern_unsafe_new_path` в `tools/xray_check.sh`, а
  гейт `make temp-isolation-check` его **игнорировал**: тот же путь стоял в
  списке `SHARED`. Запись имела причину — каталог `tools/` сканируется целиком,
  и литерал в теле кейса делал бы гейт красным ВСЕГДА. Две конфигурации
  исчерпывали выбор: вечно красный гейт (его отключат) либо невидимая диверсия.
  **ИЗМЕРЕНО** полным прогоном: `ВАКУУМНЫХ 1` (было) → `ВАКУУМНЫХ 0` (стало).
  Исправлено: путь собирается **склейкой двух литералов** (`"/tmp/" "kern_..."`),
  запись из `SHARED` убрана с пояснением, почему её нельзя возвращать.
- **#346 — SIGTERM-откат терял бит `+x` у 30 скриптов.** `_emergency_restore`
  писал свой tmp без сохранения режима — та же ошибка, что #157, но исправленная
  только в `write_atomic`. Каждый `SIGTERM` снимал `+x` у 30 `tools/*_check.sh`,
  дерево становилось «грязным», следующий прогон блокировался инъекционным
  стражем, и часть кейсов получала «зелёную» цель по **неверной** причине.
  Исправлено: сигнальный путь использует **тот же** `write_atomic` — единый
  источник правды. Проверено мини-тестом: 0755 → SIGTERM-откат → `0o755`.
- **#347 — шесть стадий CI были красными.** (1) Дрейф метрик: каталог тестов
  (27 против фактических 28 у `kernfs_router.zig`), витрина, паспорт
  (`code_hash`), покрытие замка контрактов — все производные артефакты
  пересобраны. (2) Страж «нет следов харнесса» ловил **сам себя**: литерал
  маркера диверсии стоял в трёх инструментах-детекторах
  (`arith_zig_ref_check.py`, `injection_guard.py`, `trust_scorecard.py`) — тот же
  класс, что #290/#296, метка собрана из частей. (3) Аттестат и манифест требуют
  приватного ключа владельца — это **честная граница**, а не дефект: подпись
  агент создать не может и не должен.
- **#312 — C-функция с `unsigned`/`size_t` получает ВЕРДИКТ, а не SKIP** (запись
  в журнале была помечена «ограничение», хотя гейт `c-types-check` и невакуумный
  кейс `c-types` уже существуют — журнал противоречил коду).
- **#335 — журнал дефектов EN == RU.** Переведены 13 записей (#294–#308),
  множества совпадают (**307 = 307**), и создан гейт
  `make journal-parity-check` с невакуумным кейсом `journal-parity`: он сверяет
  МНОЖЕСТВА номеров записей в обе стороны. Граница названа: гейт считает числа,
  а не формулировки — качество перевода проверяет человек.
- **#351 — последний ложный `[BOUNDS PATH]` на собственном коде.** `@deal.pre`
  не моделировался как предусловие, поэтому защищённый индекс считался опасным.
  ИЗМЕРЕНО: само-применение `--xray tools/` → **0 `[BOUNDS PATH]`, 0 `[CRASH PATH]`**.
  Двусторонняя фикстура `examples/deal_guard_demo.py` в `make xray-check`.

### Added

- **Гейт `charter-text-check`** (`tools/charter_text_check.py`) — ТЕКСТ канона
  обязан совпадать с фактическим множеством непокрытых законов; 5 веток
  мета-теста. Закрывает класс «документ-канон врёт о состоянии ядра» (#350).
- **Гейт `journal-parity-check`** (`tools/journal_parity_check.py`, класс META,
  4 ветки мета-теста: только в RU, только в EN, разный порядок, отсутствующий
  файл) — закрывает класс «дефект, живущий только по-русски, для внешнего
  читателя не записан вовсе».
- **Гейты `evm-lang-check`** и **`evm-proof-check`** — фронтенд `@kern:lang evm`
  и три тождества Yellow Paper проверяются двусторонне.
- **`abs`/`-x`/`min`/`max` в `arith-semantics-check`** — перевод этих форм
  раньше не сверялся с рантаймом НИ РАЗУ. Теперь 180 точек, включая края `i32`:
  **0 расхождений**, и контроль невакумности (наивный `abs` без переполнения
  даёт 4 расхождения).
- **Кейсы:** `journal-parity` (181), `allman-style` (182), `evm-fundef` (184),
  `evm-lang`, `charter-text`, `arith-abs-min-max`. Итог харнесса —
  **188 невакуумных / 0 вакуумных / 0 ошибок кейсов**.
- **Кейсы на странице «почему KERN»** (`docs/EXAMPLE_WHY_KERN.md` и `.ru.md`):
  шесть репозиториев, пять языков, десять случаев — к уже описанным
  `TheAlgorithms/C`, `TheAlgorithms/Rust` и `boltons` добавлены `madler/zlib`,
  `ziglang/zig`, `tigerbeetle/tigerbeetle`, `ghostty-org/ghostty` и
  `openjdk` (баг Блоха), с измеренными вердиктами из `audits/EVIDENCE.md`.

### Changed

- **`z3-solver` 5.1.0.0 → 5.3.1.0**, проверено **адверсариально ДО мержа**:
  смена решателя может изменить форму вывода, и покрытие пруф-чекера могло
  отвалиться. Прогон на новом решателе: `evm-proof-check` `trusted: 0`,
  `proof-tamper` 40 подделок / 0 принято, `charter-check` 8/8, `contracts` 11/4,
  `audits` 0 расхождений, `zig build test` rc=0. Регрессий нет — мерж разрешён.
- **Обновления CI:** `github/codeql-action` 3 → 4, `actions/upload-artifact` 4 → 7.
- **Lean 4: 147 теорем, `0 sorry`** (+4 по §95.4 в этом цикле).

### Known limitations

- `SDIV(MIN, -1) = MIN` на контрактном пути даёт видимый **SKIP**, а не тихий
  пропуск: в целочисленной модели нет границы типа, а BV-путь упирается в
  покрытие пруф-чекера (#118). Граница названа, а не спрятана.
- В `.py` с `@kern:lang evm` рантайм-подтверждение **бессмысленно** (исполняется
  Python, а не EVM) — измерено и записано.
- Явная директива `@kern:bitvec32` сильнее таблицы, но BV-путь доступен только
  для C-like входов.
- Байткод-дизассемблера EVM (`0x6080...`) по-прежнему **нет**: фронтенд
  принимает ВЫРАЖЕНИЯ и контракты, а не байткод.


## [2.7.1] — 2026-10-23

Патч: закрыт рассинхрон версии в JSON-отчёте, найденный ВНЕШНИМ исследователем.

### Fixed
- **#343 — версия в JSON-отчёте была зашита литералом `"2.4.0"`.** К релизу
  v2.6.4 бинарник печатал `v2.6.4`, а отчёт о происхождении — `2.4.0`. Заметил
  **Massimiliano Brighindi**, скачав релизный бинарник и сверив его вывод с
  отчётом. `make version-check` контролировал 11 поверхностей, но не отчёт
  (класс #97/#292). Теперь `_kern_version()` читает версию из `server.json`,
  а **12-я поверхность** гейта проверяет ФАКТИЧЕСКИЙ вывод `--json`.
- **#317 — внешнее подтверждение зафиксировано.** Независимая проверка релиза
  v2.6.4: 0/840 расхождений в Python, 0/840 в C/Zig/Rust, сквозная сверка
  статического бинарника по `SHA256SUMS`, побайтовое совпадение скрипта.
- **#344 — точный диагноз ограничения #341** (развёртка `define-fun` требует
  подстановки аргументов; константная арифметика `(div 7 2) = 3` не покрыта).
  Не выпущено: полуприменённая развёртка в пруф-чекере опаснее отсутствующей.

### Known limitations
- Три EVM-тождества доказаны **решателем**, но не доверенным пруф-чекером
  (#341/#344) — EVM-фронтенд отсутствует (#342).
- Остальные ограничения — см. раздел [2.7.0].

## [2.7.0] — 2026-10-22

Цикл «доверие и прозрачность»: устав, снимок состояния, самопроверка,
детектор флейки, изоляция временных путей и — главное — семантика языка как
объект.

### Added
- **Устав (`docs/CHARTER.md` + `charter/laws.py` + `make charter-check`).**
  18 законов в трёх классах: алгебраические (доказывает KERN), процессные
  (гейты), политика (не проверяется машинно). Каждый закон НАЗЫВАЕТ своего
  проверяющего, и гейт падает, если проверяющего нет. **8/8 законов класса I
  машинно доказаны.**
- **`docs/STATUS.md` (+ RU)** — генерируемый снимок состояния проекта из
  `facts.json`, реестра и журнала; `make status-check` сверяет с источником.
- **`docs/SELF_VERIFICATION.md` (+ RU)** — KERN, применённый к себе: 7 прогонов.
  Ключевой результат: **73 из 74 собственных заявлений получают `e=0`**, потому
  что это проза, а не машинные контракты. Врата не принимают собственный
  README за доказательство.
- **JUnit XML (`make junit`)** — стандартный формат для GitHub Actions и IDE.
  Кэш-попадание билд-раннера помечается `skipped`, а не «успехом».
- **Детектор флейки (`make flake-check`)** — N прогонов набора целей, сравнение
  вердикта КАЖДОЙ цели. Расхождение — это `B(1,1)`: два противоречащих
  свидетельства (`joinK(T, F) = B`), и ни одному прогону нельзя доверять.
  Измерено: 7 целей x 3 прогона, флейков 0.
- **Гейт свежести свидетельств (`make evidence-freshness`)** — логи класса
  `NATIVE_LIVE` обязаны совпадать с текущим деревом, `ENV_DEPENDENT` — нести
  явную метку базовой линии.
- **`VALUE_SEMANTICS` — семантика ЗНАЧЕНИЙ языка как объект** (8 языков:
  python/c/zig/rust/go/ts/js/evm) + `semantics_for()` с правилом I4:
  неизвестный язык — ЯВНЫЙ отказ, а не молчаливый дефолт в Python.
  Гейт `make lang-semantics-check` проверяет полноту таблицы, правило I4,
  отсутствие дисперсии и **совпадение таблицы с фактическими SMT-формулами**;
  отдельно — что флаги таблицы ЧИТАЮТСЯ кодом.
- **EVM как строка таблицы** (шаг 8): `div_zero_value` и `signed` управляют
  набором обязанностей. Добавление третьей семантики стоит ОДНУ строку
  таблицы и НОЛЬ новых `if lang`.

### Fixed
- **#317** — языко-зависимая семантика деления: `//` (floor) в Python,
  `/` (усечение к нулю) в C/Zig/Rust, `/` в Python — честный SKIP.
  840 вычислений: расхождений 0 (наивный `div` разошёлся бы в 530).
- **#318** — условия пути считаются ПО ПОЗИЦИИ, а не накоплением: защищённое
  деление больше не обвиняется.
- **#303** — звучимая свёртка тривиальных связок (`(and X true)` = `X`) в
  пруф-чекере: `--diff-equiv` теперь даёт ДОВЕРЕННЫЙ `EQUIVALENT`.
- **#321** — канонизация типа возврата: обязанность переполнения больше не
  снимается молча.
- **#327 / #318 (остаток)** — контекстные гарды в обоих маршрутах: ленивый
  `and`/`or` и тернарник не обвиняются ни в контрактах, ни в `--xray`.
- **#334** — обязанности переполнения деления (`INT_MIN / -1`, `INT_MIN % -1`)
  и унарного минуса (`-INT_MIN`). Наземная правда: `gcc` -> SIGFPE (rc=136)
  и SIGABRT (rc=134).
- **#336** — долг изоляции `/tmp` закрыт: 39 -> 0. Рабочие файлы прогонов
  в своём каталоге (`mktemp -d` + `trap`), выходные артефакты — в `build/`.
- **#339 / #340** — семантика значений стала объектом; регрессия от
  `@dataclass` (падало 10+ загрузчиков через `importlib`) устранена.
- **#333** — устаревшее свидетельство о числе тестов: переснято (436),
  кросс-архитектура помечена явной базовой линией.
- **#320** — отозвано необоснованное утверждение о `prime_sieve.c`.
- **#330** — 46 логов свидетельств в подкаталогах не попадали в git.
- **#331** — устаревшие числа в `llms.txt`; файл теперь генерируется из
  `facts.json`.

### Known limitations
- **`--auto` (zero-annotation) для C-like** ищет деление на ноль и границы;
  переполнение в этом режиме не подключено (есть в контрактном пути).
- **Инварианты `while`** не моделируются: находки по индексам в циклах —
  кандидаты, а не приговоры (#315, #322).
- **C-экстрактор** принимает `int` и канонизированные типы, но не указатели,
  структуры и макросы (#312 — частично).
- **Windows не поддерживается** (3 POSIX-блокера, `docs/PLATFORMS.md`).
- **Подпись своя** (Ed25519 владельца), не сторонний билдер: SLSA L3 и Rekor
  в backlog.
- **Английский журнал дефектов** отстаёт на 13 записей (#294-#308) — #335.

## [2.6.4] — 2026-10-21

### Fixed

- **#320 — a published claim that did not survive re-verification (our own error).**
  `docs/SHADOW_AUDIT_EXAMPLE.md` called `prime_sieve.c:44` a **REAL logic defect**
  and printed `count(arr, size=10) = 5`. Re-running against the **real** prime
  array from the same program gives `count(arr, 10) = 4`; the `5` came from a
  synthetic array. The source is self-contradictory about its contract (the doc
  block says "upto which" — inclusive; the test comment says "array size" —
  exclusive) and the test uses `size = 10`, the one value that cannot distinguish
  them. Verdict: **an ambiguous contract, not a defect**; the upstream report is
  withdrawn. The harness `docs/evidence/prime_sieve/reproduce.sh` reproduces every
  number, so the claim can be re-derived instead of believed.
- **#312 — the C extractor accepted only `int` parameters.** The parser required
  exactly one word before the parameter name, so `unsigned int c` was skipped while
  `size_t a` worked, although `TYPE_RANGE` already knew `unsigned`. Multi-word types
  are now canonicalised (`unsigned int`, `long long`, `unsigned long`,
  `unsigned short`, `unsigned char`, `int32_t`, `size_t`, …); `char` and `float` are
  refused **with a reason** (`char` signedness is implementation-defined).
- **#321 — the return type was not canonicalised, so the overflow obligation was
  silently dropped (false PROVEN).** Fixing #312 exposed this: `meta["ret"]` stayed
  raw (`'unsigned int'`), `ret in TYPE_RANGE` was false, and the machine-overflow
  obligation was never generated. Measured: `u32_add(unsigned int, unsigned int)`
  returning `a + b` with `ensures result >= a` reported **PROVEN** — while `gcc`
  gives `a=4294967295 b=1 -> result=0`, contract violated. Same class as #180
  (Rust). `ret` is canonicalised; a return type outside the integer subset now
  SKIPs with a reason in the contract path.

### Added

- **`docs/PLAN_v2.6.4.md`** — the active cycle: queue with acceptance and kill
  criteria, repository targets ranked **with the measurement that excludes
  `raylib`** (0 functions with an `int` parameter → outside the subset), open
  limitations. New principle: **every numeric claim in a document must ship with a
  committed harness that reproduces it** (#320 is the reason).
- Gate **`make c-types-check`** (CHECK) with the non-vacuous canfail case
  `c-types`; both sabotages verified red (dropping the `unsigned int` mapping, and
  dropping the `ret` canonicalisation). Registry: **189 targets, CHECK 150/150
  covered, 171 can-fail cases**.
- `docs/evidence/prime_sieve/` — the verbatim upstream file, a runnable harness and
  its output.
- `tests/fixtures/c_types_demo.c` — six functions: four integer types that must
  receive verdicts, two out-of-subset types that must SKIP with a reason.

## [2.6.3] — 2026-10-21

### Fixed

- **#318 — false `[CRASH PATH]` on a guarded division.** Found while sweeping
  `TheAlgorithms/C/math/`: `--xray` accused `y / x` of dividing by zero even when
  the division sits **inside** `if (x != 0) { … }`. Cause: path conditions were
  **accumulated** instead of computed per position — the query for a divisor
  inside the block received `(not cond)`, that is the **negation of its own
  guard**. Conditions are now resolved per position (`_clike_conds_at`), and `if`
  blocks are registered even when they contain no `return`. The fix applies to all
  three queries that consumed the accumulated list — divisors, bounds, and
  allocation overflow. Measured: single guard, nested double guard, and the real
  `cartesian_to_polar.c` → **0 findings**; the same division **without** a guard is
  still accused. Locked in `xray_check.sh` with both cases.

### Added

- **Upstream contribution — [`TheAlgorithms/C#1595`](https://github.com/TheAlgorithms/C/pull/1595)**
  (22,554 ★, opened 2026-10-21, one file, `+7 −0`, CI `triage` passed): the minimal
  fix for the two defects KERN found in `math/catalan.c` — `SIGFPE` on `n = 0` and
  silent wrong output from `n = 11`.
- `docs/pr/catalan_fix.patch` and `docs/pr/thealgorithms_c_PR.md` — the patch as
  submitted and the PR text.

## [2.6.2] — 2026-10-21

### Fixed

- **#317 — integer division semantics (soundness).** Externally reported by
  **Massimiliano Brighindi (PHI-OMEGA / M)**, reproduced here, and escalated from
  "translation mismatch" to **false acceptance**: the translator emitted SMT-LIB
  `div`/`mod` for Python `//` and `%`, but those are *Euclidean* (remainder always
  ≥ 0) while Python is *floor* and C/Zig/Rust *truncate toward zero*. Measured
  consequence: `requires a == 3 and b == -2` / `ensures result >= -1` over
  `a // b` was reported **PROVEN** (`premises bound: 3/3`, `holes: 0`) while live
  Python yields `-2` and violates the contract.
  The translator is now language-aware: `_CURRENT_LANG` is set in
  `parse_clike`/`parse_file`, `expr_smt` takes `lang`; Python `//` uses the floor
  adapter, `%` the identity `a - b*q`, `/` an honest SKIP (true division is
  float); C/Zig/Rust `/` uses truncation, `%` the same identity.
  Measured after the fix: `tools/arith_semantics_check.py` reports **0 mismatches
  out of 840** (the naive `div` would differ in 530), and
  `tools/arith_zig_ref_check.py` confirms both adapters against the **built-in
  Zig operators** `@divFloor`/`@divTrunc` — **0 mismatches out of 1640 pairs**.
  Gates: `arith-semantics-check`, `arith-zig-ref-check`, canfail cases
  `arith-semantics` and `arith-zig-ref` (both non-vacuous), a CI stage, and the
  Zig reference fixture `tests/fixtures/zig_div_reference.tsv`.

### Added

- `docs/CONTRACT_ANY_PROJECT.md` — the 5-step recipe for writing a contract for
  any project, plus a worked example that found a real crash (SIGFPE) in
  `TheAlgorithms/C`.
- `docs/SHADOW_AUDIT_EXAMPLE.md` — two real defects in `TheAlgorithms/C`
  `math/catalan.c` (crash on `n = 0`, silent wrong answers from `n = 11`), the
  correct fix, and the warning that the obvious fix is wrong.
- `docs/pr/` — patch and pull-request text for `TheAlgorithms/C`.

### Known limitations

- **#318 (OPEN)** — the C-like divisor check accuses *guarded* code:
  `int f(int x, int y) { if (x != 0) { return y / x; } return 0; }` still yields
  `[CRASH PATH]`. A false accusation is worse than a miss, so this is filed as a
  defect, not noise.
- `python3 /` (true division) now yields SKIP instead of a wrong verdict — an
  honest reduction in coverage, by design: soundness outranks completeness.

### Credit

The defect was found and reported privately by **Massimiliano Brighindi
(PHI-OMEGA / M)** with a differential reproducer and a proposed floor adapter.
His adapter is what shipped for Python; the C-like truncation adapter was derived
from the same reasoning and is validated against Zig's built-in operators.

## [2.6.1] — 2026-10-21

Real-world hardening: four languages verified, live models measured, and three
defects found by the field tests themselves.

### Added
- `kernc pack-dir <dir> -o out.kimg`: pack a directory tree (a cloned repository)
  into one image; verified on a real clone with `fsck` (20/20 objects), `inspect`
  and `diff` (one changed file detected).
- `kernc prove --query-kind refutation|equivalence`: the premise-binding rule now
  belongs to contract proofs only, so `--diff-equiv` returns a **trusted**
  EQUIVALENT for real refactorings (verified on a live model rewrite of
  `boltons::clamp_int`).
- The code-checking corpus covers **Python, Zig, C and Rust** with machine-type
  bounds: `TP=5, TN=5, FP=0, FN=0, UNKNOWN=4`, including an `i32` overflow
  witness `a = 2147483647, b = 1 -> 2147483648`.
- Idiomatic Rust (tail expression) is now verified instead of skipped.

### Fixed
- #299 `kernc build <directory>` printed a raw Zig stack trace; now a clean
  message and exit code 2 (same for a missing argument).
- #300 `trace_explorer.py` builds parameter domains from standard Python
  annotations when the QuixBugs-style docstring is absent.
- #302 `pack-dir` silently packed 5 of 20 files (relative paths); the skipped
  counter exposed it on the first run.
- #304 `kernc prove` read the file path from a fixed argument position, so a new
  flag was read as a file.
- #306 Rust bodies written as tail expressions were skipped, so live model
  answers were never verified.

### Measured (live models, not opinions)
- 3 free models x 4 languages: round 1 blind **4 proved / 7 refuted / 1 honest N**;
  after KERN’s counterexample **4 of 7 refuted tasks repaired**. The three
  un-repaired ones are the same Zig overflow task, while the Rust twin was fixed.
- Both models tested rewrite `@kern:requires` (never `@kern:ensures`) when the
  contract is unsatisfiable; `contracts-lock-check` catches it.
## [2.6.0] — 2026-10-21

Trust that can be checked from outside, and an exam that can fail.

### Added
- **External attestation**: `docs/keys/kern-owner.pub` ships in the repository,
  so anyone can verify `kern.intoto.jsonl` with `make verify-attestation`
  (no `$HOME` key, no owner machine). `kid` is recorded in the attestation.
- **Secrets scanner** (`make secrets-check`): 9 provider patterns, redacted
  output, self-test with 7 plantings; runs over git-tracked files.
- **Determinism gate**: the same SMT input twice must give the same verdict,
  counterexample, `trusted` and `holes`.
- **Conformance exam** (`make conformance-check`): 12 sections, 95 checks,
  reading facts emitted by the kernel itself; `--selftest` corrupts nine facts
  and requires every section to turn red.
- **Code-checking corpus** (`make codecheck`) with an honest confusion matrix:
  `TP=2, TN=2, FP=0, FN=0, UNKNOWN=8` - `TN` only means "proved clean".
- **Contract classes** `hard` / `advisory`: `T_advisory` never mixes into `T`,
  and the class is part of the lock fingerprint.
- **Read-only abductive report**: `explain --hypotheses` proposes `requires`
  only, re-verifies each candidate, rejects vacuous ones out loud, and never
  writes to the source.
- **Evidence ledger** `add`/`retract` with recomputation, three provenance
  graphs, and rejection of negative recursive SCCs.
- **`kernx graph`** as the single source of the `G_src` graph (byte parity with
  the showcase).
- **KIMG**: unknown-optional vs unknown-required policy, `WrongEndianness`,
  `kernc fsck / inspect / diff`, three golden fixtures.
- **13-field cache key** and **KERN-X shared budget** with quotas.

### Changed
- `kernc` and the C ABI are `v2.6.0`; `kern_kimg_object_count` returns
  `int64_t` and lengths use `size_t` (LLP64-safe).
- QuixBugs: **40/40** tasks diverge (29 value, 10 crash, 1 hang); the seven
  former `EXPLORED` cases were harness bugs, not clean code.
- `artifact-check*` reclassified `CHECK -> BUILD`: they verify a release
  artefact against a hash announced in README, which only exists at release.

### Fixed
- `timeout`, `out_of_fuel` and `invalid_certificate` no longer collapse into
  `F`; a missing solver is `N`, not an accusation (#277).
- `andT`/`orT` were wrong on the pairs (N,B) and (B,N) (#279).
- Harness: rollback now restores file modes (#283); a skipped case under
  `--only` is an error, not a silent pass (#275).
- Two can-fail cases no longer cling to numbers that `make sync` rewrites
  (#282) and cannot silently pass (#281).

### Known limitations
- Bounded intuitionistic mode (`--intuitionistic --worlds N`) is in the
  backlog: the full text of Kamide & Niki 2026 (IGPL, `10.1093/jigpal/jzag024`)
  describes a Gentzen calculus `sQBDi` and is not available locally
  (`read = {false}`); writing Kripke semantics from an abstract is forbidden.
- Windows is not supported (three POSIX blockers in `docs/PLATFORMS.md`).
- The attestation is signed by the owner key, not by a hosted builder
  (Sigstore/Rekor remain in the backlog).
## [2.5.2] — 2026-10-20

Honest showcase and a release pipeline that cannot lie: proof-flow map with
CEGIS arrow, Ego-Lens over the real `@import` graph, `[+][~][-][=]` filter
matrix, zoom on both diagrams, `--diff-equiv` no longer declares identical
files divergent, unknown KIMG flags are honoured, orphan fact-anchors are
caught, Release Drafter no longer hijacks the release tag, and the site
stopped claiming that README, build and asset hashes are equal (#243–#250).

Full release notes: [`docs/RELEASE_NOTES_v2.5.2.md`](docs/RELEASE_NOTES_v2.5.2.md).

## [2.5.1] — 2026-10-20

Honest QuixBugs boundary (6/40 SMT + 33/40 differential), `make sync` with
`docs/facts.json` and anchors, EN/RU parity guard, no AI boilerplate,
canfail 144/0/0/0, scorecard 128/144, attestation with `attests_commit`.

Full release notes: [`docs/RELEASE_NOTES_v2.5.1.md`](docs/RELEASE_NOTES_v2.5.1.md).

## [2.5.0] — 2026-10-19

Full release notes: [`docs/RELEASE_NOTES_v2.5.0.md`](docs/RELEASE_NOTES_v2.5.0.md).
Every number below is produced by a command in this repository; historical measurements
(e.g. the 77.5% mutation score obtained *without* a solver in `PATH`) are kept as history,
not as the current state.

### Added
- **Native Fourier–Motzkin LIA solver** (`src/verifier/builtin_lia.zig`): 100 systems
  checked against Z3 — 0 disagreements; 60/60 metamorphic checks; `--full-file` 18/18.
- **SAT-model validation inside the kernel** (`verifyModelAgainstSmt`): the Z3 model is
  substituted back into every `(assert …)` and evaluated independently; a false model is
  reported as `SPURIOUS MODEL` and **no counterexample is shown**.
- **`musl abs.c`: `SKIP → PROVEN`** (51 steps, `trusted: 0 | holes: 0`) — `intro-def`,
  `lemma`, `def-axiom`, `rewrite` and `monotonicity` are now checked, not trusted.
- **New theories at `trusted: 0`**: IEEE-754 (the NaN trap), QF_S (sanitiser bypass),
  loops (`invariant`/`decreases`), array bounds, state invariants and RLS policies.
- **`--xray` with zero annotations** across 7 languages (`.py .zig .c .rs .ts .js .go`);
  six field adapters (`self.x`, let-inlining, module constants, `min/max/abs`,
  recursive directory walk, length invariant).
- **`--audit-repo <path|owner/repo|url>`**: sandboxed git
  (`core.hooksPath=/dev/null`, `GIT_TERMINAL_PROMPT=0`, `GIT_LFS_SKIP_SMUDGE=1`,
  30 s timeout), `/dev/shm` cleanup on SIGTERM/atexit, junk/symlink filters.
- **Proof-Carrying `.kimg`** (`[PCC VERIFIED]` with no solver) · **Evidence Decay** ·
  **Merkle audit chain** · **Bit-Rot Guard** (30/30 injections caught).
- **WASM kernel** `kernc.wasm` (86,953 bytes; 5 `kern_wasm_*` functions including `kern_wasm_verify_proof`; 7 export entries with `memory`/`__stack_pointer`).
- **8 MCP tools** plus `server.json` / `mcp.json` / `.well-known/mcp.json`
  (generated from `tools/list`) and MCP tool annotations.
- **`llms.txt`**, `--sarif` (SARIF 2.1.0), `action.yml` with an `xray` mode,
  `tools/trust_scorecard.py` and the `#scorecard` section on the site.

### Fixed (selected; the full journal is `docs/CAPABILITY_STATUS.md` §6c–§6d)
- **#155** the proof checker accepted a tampered DAG (a broken `@xN` reference now yields `.bad`).
- **#166** false `unknown` in WASM (the solver picked a variable with a zero coefficient).
- **#171** `bench-semantic`: single source of truth for the Merkle root (`sealImageRoot`).
- **#173** the evidence guard wrongly accused the harness (write-once baseline, artefacts
  outside the baseline, dirty start → `rc=3`).
- **#174** 52 duplicate top-level definitions in `kern_contracts.py` — **resolved
  (52 → 0, −2003 lines)**; `dup_defs_guard` ratchet now at 0. A second
  `if __name__ == "__main__"` (early `main()` before later defs) and the lost
  C-like routing in `cmd_xray` were found and fixed. Field-audit fixes
  **#178–#184** (comment/string stripping, `assert` guards, Rust signatures,
  scorecard profiles, balanced-paren `assert`, type ranges + let-inlining,
  three-valued `_smt_sat`) ship in the same release.
  by the ratchet guard `tools/dup_defs_guard.py`; the refactor is scheduled after the release.
- **#179** mobile layout overflowed by 12 px (the `owner/repo` input had a fixed `size`
  attribute); the scorecard input is now fluid, and `scrollWidth == clientWidth` on both
  360 px and 1425 px viewports.

### Notes
- License: **PolyForm Noncommercial 1.0.0** (source-available); commercial use requires a
  license from the copyright holder.
- `align(32)` in `blake3_simd8`: no measurable speed-up (2.42 vs 2.41 GB/s) — the change is
  harmless but is **not** claimed as an optimisation.


## [2.4.0] — 2026-10-17

### Added
- **Polyglot contract checking**: `@kern:requires` / `@kern:ensures` are read from
  `.py`, `.zig`, `.c` and `.rs`; machine types (`i32`/`u32`/`i64`/`usize`) are enforced,
  so i32 overflow / unsigned underflow and division by zero are caught.
- **Vacuous-requires detector**: a contradictory precondition (`false ⟹ anything`) is
  reported as `[VACUOUS] precondition is unsatisfiable (empty domain) -> B4: N, e = 0`
  instead of a false PASS.
- **Contract lock** (`--lock` / `--verify-lock`): BLAKE3 fingerprints of every contract in
  `docs/contracts.lock.json`; removing or weakening an `@kern:ensures` line is `rc = 2`.
- **Refactoring equivalence without contracts** (`--diff-equiv old.py new.py`): checks
  `∃x: f_old(x) ≠ f_new(x)` over all of ℤ and prints the exact diverging input;
  exposed as the fifth MCP tool `kern_check_equivalence`.
- **Counterexample → pytest** (`--emit-pytest`) and **SARIF 2.1.0** / GitHub annotations
  (`--sarif`, `--github-annotations`) so a refuted contract lands on the exact PR line.
- **Git pre-commit hook** (`--install-hook`, `--git-diff`): an AI agent cannot commit
  broken code or a weakened contract.
- **`make self-verify`**: KERN verifies its own arithmetic functions.
- **`docs/FarkasSoundness.lean`**: soundness of the proof checker formalised in Lean 4
  (`int_not_le_iff`, `farkas_2_sound`, `farkas_3_sound`, `three_valued_check_sound`,
  `vacuous_requires_unsound`, `skip_preserves_belnap_join`) — 8 files, **42 theorems, 0 sorry**.
- **Ed25519-signed SLSA attestation** (`kern.intoto.jsonl` + `kern.intoto.sig`), verified
  by `python3 tools/slsa_provenance.py --check`.
- **`action.yml`**: the reusable GitHub Action now verifies the downloaded binary against
  `SHA256SUMS` (`sha256sum -c`) before running it.
- **English mirrors** of the key documents: `docs/CAPABILITIES.en.md`,
  `docs/ATTESTATION_PASSPORT.en.md`, `docs/CAPABILITY_STATUS.en.md`, `docs/METRICS.en.md`.

### Changed
- **Mutation score 95.0 % (38/40 killed; 2 survivors proven equivalent)** over
  **14 files / 420 sites** (previously 6 files / 63 sites). The mutator now requires a
  solver in `PATH` (`--require-solver`), because the earlier 77.5 % figure was taken with
  8 solver-dependent tests silently skipped (defect #110).
- **Mutator speed**: `KERN_MUTATE_FAST` reduces stress-loop iterations *without disabling
  any test* (11.4 s → 5.8 s per mutant), plus `--jobs N` (2.15×).
- Can-fail harness: **78/78 CHECK targets** have a proven-can-fail case
  (93 non-vacuous cases, 0 vacuous, 0 case errors) and a `--check-anchors` pre-flight.
- Constant-time digest comparison (`std.crypto.timing_safe.eql`) in 5 places (FIPS 140-3).

### Fixed
- **CI #68/#69 went red** because can-fail cases patched a hard-coded hash in `README.md`
  (root cause found via the GitHub API; anchors are now derived from the files).
- Defects **#104–#116**, including: `witness_model` was always `null` (#104), the memory
  leak opened by that fix (#105), sampling bias in the mutation run (#107), a hanging pipe
  regression test (#108), a pipe deadlock in `child.wait()` (#109), environment variables
  that silently did nothing in tests (#112), the mutation score measured without a solver
  (#110), can-fail polluting committed evidence (#114), a vacuous `slsa` case (#115) and
  harness rollback silently discarding edits made during a run (#116).
- Documentation honesty: fabricated cross-architecture numbers (`279/279` where the log
  says `240 passed / 4 skipped / 0 failed`), stale core counts (198 → 279), a stale KERN-Next
  count (37 → 38 executed tests) and several dated snapshots now marked as such.

## [2.2.0] — 2026-10-16

### Added
- MCP server (stdio) with four verification tools, `make mcp-selftest`.
- `docs/contracts.lock.json`-based specification sealing; `--diff-equiv` groundwork.
- GitHub Action with a SARIF output path.

### Fixed
- Release artefact chain (README ↔ build ↔ asset) enforced by `make artifact-check`.

[2.4.0]: https://github.com/newmathphys/kern/compare/v2.2.0...v2.4.0
[2.2.0]: https://github.com/newmathphys/kern/releases/tag/v2.2.0
