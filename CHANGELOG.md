# Changelog

All notable changes to KERN. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below is produced by a command in the repository — see
[`docs/METRICS.md`](docs/METRICS.md) and [`docs/evidence/`](docs/evidence/).

## [Unreleased]

Полный прогон `make ci` показал **55 зелёных / 8 провалов** — разбор дал три
разных класса, и все три закрыты или названы честно. Здесь же — два дефекта,
найденных по ходу (вакуумный кейс и потеря режима файлов при откате).

### Fixed
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

### Added
- **Гейт `journal-parity-check`** (`tools/journal_parity_check.py`, класс META,
  4 ветки мета-теста: только в RU, только в EN, разный порядок, отсутствующий
  файл) — закрывает класс «дефект, живущий только по-русски, для внешнего
  читателя не записан вовсе».
- **Кейс `journal-parity`** в харнессе can-fail (181-й): перенумерация одной
  записи в EN обязана покраснить гейт.
- **Кейсы на странице «почему KERN»** (`docs/EXAMPLE_WHY_KERN.md` и `.ru.md`):
  шесть репозиториев, пять языков, десять случаев — к уже описанным
  `TheAlgorithms/C`, `TheAlgorithms/Rust` и `boltons` добавлены `madler/zlib`,
  `ziglang/zig`, `tigerbeetle/tigerbeetle`, `ghostty-org/ghostty` и
  `openjdk` (баг Блоха), с измеренными вердиктами из `audits/EVIDENCE.md`.


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
