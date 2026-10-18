# =========================================================================
#  KERN: Knowledge, Evidence, Reasoning Network
#  Единая точка входа для сборки, тестов и упаковки.
# =========================================================================

ZIG      ?= zig

# Решатель для мутационного прогона. Без него 8 тестов уходят в `SkipZigTest`,
# и мутационный скор считается по УСЕЧЁННОМУ набору (дефект #110). Уважаем PATH;
# если `z3` там нет — ищем в типовых местах (в т.ч. venv с пакетом z3-solver).
KERN_Z3_PATH ?= $(firstword $(wildcard $(HOME)/*/.venv/bin/z3 $(HOME)/.venv/bin/z3 $(HOME)/.local/bin/z3 /usr/local/bin/z3 /usr/bin/z3))
PYTHON   ?= python3
VENV     ?= .venv
OUT      ?= .kernnext

.PHONY: contracts contracts-json edge-cases contracts-lock contracts-lock-check diff-equiv self-verify sarif-check hook-check artifact-check artifact-check-offline help venv zig golden build test test-next verify attack next demo run-example adversarial telemetry telemetry-quick evidence evidence-fast guardrail docker lean stress bench perf mutate prove clean memcheck ubsafe stress-kimg smt-stress test-all formal-ci fd-check align avalanche pool semantic-gap bench-json echelons audit localize arrays chc strings cegis theories test-fault attest-key attest mbpp chc-bench coverage lib capi-demo hermetic cert fuzz-1m litmus concolic dtmc absint nra noninterference redos portable-bench canfail canfail-anchors registry svg-check evidence-gate ci ci-fast cross-arch research binlevel probe mcp-selftest kimg-deflate audits lia-diff version-check proof-tamper

# АРХИТЕКТУРНЫЙ МОСТ «текст → контракт»: сканирует репозиторий, извлекает
# якоря @kern:spec / @kern:evidence, собирает образ и прогоняет контракты
# через Z3. Утверждение с доказанным контрактом получает e=1.
bridge:
	$(PYTHON) tools/scan_to_kern.py . -o /tmp/kern_bridge.kern
	./zig-out/bin/kernc build /tmp/kern_bridge.kern -o /tmp/kern_bridge.kimg
	./zig-out/bin/kernc verify /tmp/kern_bridge.kimg 2>&1 | grep -E "claim|контракт|свидетельство|ИТОГ" | head -40

help:
	@echo "KERN — цели Makefile"
	@echo ""
	@echo "Основные:"
	@echo "  make venv        — venv с Zig 0.13 (только для main/portable-bench)"
	@echo "  make golden      — собрать эталонный образ .kimg v1.3"
	@echo "  make build       — собрать kernc / kern-attack / kernx"
	@echo "  make test        — тесты ядра (191)"
	@echo "  make test-next   — тесты KERN-Next (37)"
	@echo "  make demo        — сквозная демонстрация (kernc + kernx)"
	@echo "  make coverage    — покрытие инструментированных решений"
	@echo "  make mutate      — мутационное тестирование (работает на копии)"
	@echo "  make contracts-lock-check — замок контрактов (агент не ослабил спецификацию)"
	@echo "  make contracts-json — JSON-отчёт контрактов (--json)"
	@echo "  make diff-equiv  — эквивалентность рефакторинга без контрактов"
	@echo "  make self-verify — KERN проверяет СВОЙ код (Zig) + полиглот C/Rust"
	@echo "  make sarif-check — SARIF 2.1.0 для GitHub Code Scanning"
	@echo "  make hook-check  — самотест Git pre-commit шлюза"
	@echo "  make perf        — производительность (.kimg, оба пути чтения)"
	@echo "  make test-all    — полный контур проверок"
	@echo "  make formal-ci   — ядро + Lean + бенчмарки"
	@echo "  make echelons    — 4 эшелона финального штурма"
	@echo ""
	@echo "Все цели ($$(grep -cE '^[a-z][a-z0-9_-]*:' Makefile)):"
	@grep -oE '^[a-z][a-z0-9_-]*:' Makefile | tr -d ':' | sort | column -c 96 2>/dev/null || \
	 grep -oE '^[a-z][a-z0-9_-]*:' Makefile | tr -d ':' | sort | tr '\n' ' '

venv:
	@echo "[i] ВНИМАНИЕ: на ветке zig-0.17-migration нужен Zig 0.17.0."
	@echo "    Этот venv (Zig 0.13) — ТОЛЬКО для ветки main и для portable-bench."
	@echo "    Рабочий тулчейн: ~/opt/zig-x86_64-linux-0.17.0/zig"
	uv venv $(VENV)
	uv pip install --python $(VENV)/bin/python ziglang==0.13.0

zig:
	@$(ZIG) version

golden:
	$(PYTHON) tools/golden_v1_3.py

build:
	$(ZIG) build

test:
	$(ZIG) build test

test-next:
	$(ZIG) build test-next

verify: build
	./zig-out/bin/kernc check-integrity tests/fixtures/valid_v1_3.kimg
	./zig-out/bin/kernc verify tests/fixtures/valid_v1_3.kimg

attack: build
	./zig-out/bin/kern-attack

next: build
	./zig-out/bin/kernx build examples/project.kern --out $(OUT) --scope issue-42

# Сквозная демонстрация обеих веток: kernc (образ) и kernx (проект).
demo: golden build next
	./zig-out/bin/kernc build examples/project.kern -o release.kimg
	./zig-out/bin/kernc ls release.kimg
	./zig-out/bin/kernc unify 50 120
	./zig-out/bin/kernc handoff release.kimg
	./zig-out/bin/kernx status examples/project.kern

docker:
	docker build -t kern:1.3 .

# ─────────────────────────────────────────────────────────────────────────────
#  TOY EXAMPLE: «зелёный CI» против математики.
#
#  Агент «починил» списание со счёта (потеряв проверку amount <= 0) и написал
#  тест БЕЗ единого assert, чтобы CI стал зелёным. Обычный pytest: exit 0.
#  KERN: находит контрпример к контракту (amount = -1) и закрывает Врата.
#  Запуск: make run-example   (нужен z3 в PATH)
# ─────────────────────────────────────────────────────────────────────────────
run-example: build
	@echo "=== [1] Обычный CI: pytest на «тесте» агента ==="
	-$(PYTHON) -m pytest -q examples/toy_ai_hallucination/withdraw.py 2>&1 | tail -3 || \
	 echo "(pytest не установлен — вакуумный тест всё равно не имеет assert)"
	@echo
	@echo "=== [2] KERN: сборка образа доказательств ==="
	./zig-out/bin/kernc build examples/toy_ai_hallucination/project.kern -o toy.kimg
	@echo
	@echo "=== [3] KERN: Врата Истины (вердикт даёт Z3) ==="
	./zig-out/bin/kernc verify toy.kimg
	@echo
	@echo "=== [4] Чтение через KERNFS (виртуальная ФС образа) ==="
	./zig-out/bin/kernc ls toy.kimg
	@echo
	@echo "ИТОГ: заявление агента ОПРОВЕРГНУТО (e=0), исправленная версия ДОКАЗАНА (e=1)."

# Прицельные атаки на ядро: заголовок .kimg, переполнение u64, подмена payload,
# обход путей KERNFS, бомба зависания Z3, конфликт Белнапа. Критерий: 0 пробитий.
adversarial: build
	bash tools/adversarial_suite.sh

# Телеметрический стенд: веса · время · MaxRSS · SHA-256 · JSON-паспорт.
telemetry:
	$(PYTHON) tools/measure_all_kern.py --out telemetry_report.json

# Быстрый вариант стенда (без двух сборок, мутаций и фаззинга).
telemetry-quick:
	$(PYTHON) tools/measure_all_kern.py --quick --out telemetry_report.json

# GUARDRAIL-ПРОКСИ: живой перехватчик галлюцинаций (HTTP 409 при конфликте).
# ВАЖНО: цель ПРОВЕРЯЕТ коды ответов и ПАДАЕТ при неверных. Раньше она лишь
# печатала их — то есть не могла упасть (вакуумная проверка, найдено can-fail
# кейсом guardrail-verdict).
guardrail: build lib
	$(PYTHON) examples/guardrail_proxy.py --self-test

# СБОРЩИК СВИДЕТЕЛЬСТВ: прогоняет все проверки и сохраняет их ПОЛНЫЕ логи
# в docs/evidence/ (у каждого заявления — доказательство, а не только запись).
evidence:
	bash tools/collect_evidence.sh

# То же без тяжёлых проверок (мутации, фаззинг, QEMU).
# Жёсткий гейт: ни один лог в docs/evidence/ не заканчивается RC!=0.
# Наивный grep даёт ложные срабатывания (в canfail.log FAIL намеренны),
# поэтому проверяется финальная строка RC=<n> каждого лога.
evidence-gate:
	$(PYTHON) tools/evidence_gate.py

evidence-fast:
	bash tools/collect_evidence.sh --fast

# Формальные доказательства Lean 4 (0 ошибок, 0 sorry).
lean:
	./formal/check.sh

# Тактика 3: стресс-тесты (1M + усиленный по реальному коду).
stress:
	$(ZIG) build bench-stress-1m
	$(ZIG) build bench-stress-real

# Тактика 2: KERN-native бенчмарк (методология EvalPlus).
bench:
	$(ZIG) build bench-kern

# Производительность конвейера .kimg (zero-copy).
perf:
	$(ZIG) build bench-perf

# SMT-эквивалентность оптимизаций (Alive2 / Hacker's Delight) через Z3.
smt:
	$(ZIG) build bench-smt

# Доказательство SMT-скрипта через реальный Z3 (e=1).
prove:
	$(ZIG) build
	./zig-out/bin/kernc prove formal/example.smt2

# Тактика 1: Zig-native мутационное тестирование (аналог cargo-mutants).
# --jobs: параллельные воркеры (у каждого СВОЯ копия дерева и свой кэш).
# Вердикты и скор от параллелизма НЕ зависят (проверено: --jobs 1 и --jobs 3
# дали идентичный результат), меняется только время: замер 6 мутантов
# 59.6 с -> 27.7 с (2.15x).
# --require-solver: без `z3` 8 тестов уходят в SkipZigTest, и скор считается
# по УСЕЧЁННОМУ набору (дефект #110) -> прогон обязан падать, а не врать.
mutate:
	KERN_ZIG="$(ZIG)" $(PYTHON) tools/mutate_zig.py --max 40 --seed 7 --jobs 4 \
		--require-solver --z3-path "$(KERN_Z3_PATH)"

clean:
	rm -rf zig-out .zig-cache $(OUT) release.kimg report.md agent_packet.json PROJECT_CANONICAL_SPEC.kern.md

# Контракты прямо в Python-коде: @kern:requires / @kern:ensures -> SMT-LIB2 -> Z3.
# Демонстрация: make contracts  (корректная функция ДОКАЗАНА, багованная НАРУШЕНА)
# ПРОВЕРКА, а не демо: --expect-demo падает, если вердикты разошлись с ожиданием.
# РАНЬШЕ здесь стоял `|| true`, поэтому цель НЕ МОГЛА УПАСТЬ — «молчаливо
# сломанная проверка» в самой цели (закрыто can-fail кейсом `contracts`).
contracts: build
	@$(PYTHON) tools/kern_contracts.py examples/contracts_demo.py \
		examples/contracts_demo.zig examples/contracts_demo.c \
		examples/contracts_demo.rs --expect-demo

# --- ЭТАП 2: САМОВЕРИФИКАЦИЯ (KERN проверяет СВОЙ код) ---------------------
# Только файл самоверификации: в `contracts_demo.*` лежат НАМЕРЕННЫЕ баги
# (деление на ноль, переполнение) — их место в `make contracts`, а не здесь.
self-verify: build
	@$(PYTHON) tools/kern_contracts.py examples/self_verify.zig

# --- ЭТАП 2: КРАЙНИЕ СЛУЧАИ ПАРСЕРА ----------------------------------------
# Формы, найденные РУЧНОЙ проверкой (и дважды вскрывшие реальные дефекты):
# else отдельным оператором, умножение на локальную константу, u32 underflow,
# детектор чистоты. Цель — ПРОВЕРКА: падает, если форма перестала разбираться.
edge-cases:
	@bash tools/edge_cases_check.sh

# ЗОЛОТОЙ КОРПУС АУДИТОВ: РЕАЛЬНЫЕ функции чужих проектов -> таблица вердиктов
# (генерирует инструмент) + запечатанный .kimg (L0 заголовок/Merkle, L2 KERNFS,
# L4 доказательства Z3). Формулы выгружает ДЕТЕРМИНИРОВАННЫЙ фронтенд (не LLM).
audits: build
	@$(PYTHON) tools/audits_run.py --emit-md audits/EVIDENCE.md

# ПУНКТ 1 ПЛАНА v2.5: дифференциальный гейт встроенного LIA-решателя
# против реального Z3 (0 ложных «доказано», 0 ложных контрпримеров).
lia-diff: build
	@$(PYTHON) tools/lia_diff.py

# ИСПЫТАНИЕ А: адверсариальный фаззер пруф-чекера. Берёт РЕАЛЬНЫЙ вывод Z3
# (51 шаг, abs.c, trusted: 0) и вносит 30 точечных подделок в разные классы
# правил; КАЖДАЯ обязана быть отвергнута (rc != 0).
proof-tamper: build
	@$(PYTHON) tools/proof_tamper_check.py --n 30

# --- ЭТАП 1: ЛИНИЯ ДЛЯ GITHUB ---------------------------------------------
# SARIF 2.1.0 (Code Scanning / плашки в Pull Request) + нативные аннотации.
# Цель — ПРОВЕРКА: отчёт обязан быть валидным И содержать находки.
SARIF_OUT ?= /tmp/kern.sarif
CONTRACTS_JSON_OUT ?= /tmp/kern_contracts.json

sarif-check: build
	@$(PYTHON) tools/kern_contracts.py examples/contracts_demo.c \
		--sarif $(SARIF_OUT) --github-annotations >/dev/null 2>&1 || true
	@$(PYTHON) tools/check_sarif.py $(SARIF_OUT)

contracts-json: build
	@$(PYTHON) tools/kern_contracts.py examples/contracts_demo.py \
		--json $(CONTRACTS_JSON_OUT) >/dev/null 2>&1 || true
	@$(PYTHON) tools/check_contracts_json.py $(CONTRACTS_JSON_OUT)

# --- ЭТАП 1: ПОЛЬЗОВАТЕЛЬСКИЙ GIT-ШЛЮЗ -------------------------------------
# Установка: python3 tools/kern_contracts.py --install-hook
# Здесь — САМОТЕСТ: корректный контракт проходит, сломанный/деление на ноль
# блокируются.
hook-check:
	@bash tools/hook_selftest.sh

# --- УЛУЧШЕНИЕ №2: ЗАМОК КОНТРАКТОВ (Contract Lock) --------------------------
# ЗАЧЕМ. Самый простой чит ИИ-агента, которому не удаётся починить код под
# `make contracts`, — УДАЛИТЬ или ОСЛАБИТЬ строку `# @kern:ensures`.
# Замок хранит SHA-256 отпечатки всех спецификаций; `contracts-lock-check`
# ловит удаление/изменение и падает с rc=2.
KERN_CONTRACTS_LOCK ?= docs/contracts.lock.json

contracts-lock:
	@$(PYTHON) tools/kern_contracts.py examples/contracts_demo.py \
		--lock $(KERN_CONTRACTS_LOCK)

contracts-lock-check:
	@$(PYTHON) tools/kern_contracts.py examples/contracts_demo.py \
		--verify-lock $(KERN_CONTRACTS_LOCK)

# --- УЛУЧШЕНИЕ №3: ЭКВИВАЛЕНТНОСТЬ РЕФАКТОРИНГА -----------------------------
# Цель — ПРОВЕРКА, а не демонстрация: расходящаяся пара (перепутан знак)
# ОБЯЗАНА быть поймана, иначе цель падает. Доказательство эквивалентности,
# не отличающее сломанный рефакторинг от корректного, — фикция.
diff-equiv: build
	@$(PYTHON) tools/kern_contracts.py --diff-equiv \
		examples/refactor_before.py examples/refactor_after.py; \
	rc=$$?; if [ $$rc -eq 1 ]; then \
		echo "[OK] расхождение обнаружено (rc=1) — доказательство не фиктивно"; \
	else echo "[!] РАСХОЖДЕНИЕ НЕ ОБНАРУЖЕНО (rc=$$rc)"; exit 1; fi

# MCP-сервер: живая проверка протокола (JSON-RPC 2.0 поверх stdio).
# Запускает examples/kern_mcp_server.py как ДОЧЕРНИЙ ПРОЦЕСС и проверяет 9 пунктов:
# initialize, отсутствие ответа на уведомление, tools/list, доказуемый и
# опровергаемый контракт, сводку пруф-чекера, JOIN_K(T,F)=B, ошибки -32601/-32700.
mcp-selftest: build
	@$(PYTHON) tools/mcp_selftest.py

# СЖАТИЕ ОБЪЕКТОВ (кодек deflate 0x02) в CLI: сборка --deflate, прозрачная
# распаковка в `cat` и ОБНАРУЖЕНИЕ порчи сжатого потока. Проверка, а не демо:
# падает, если содержимое не совпало побайтово или порча не поймана.
kimg-deflate: build
	@bash tools/kimg_deflate_check.sh

# СОГЛАСОВАННОСТЬ ВЕРСИИ (дефект #97): `--version`, баннер `usage` и README
# обязаны называть ОДНУ версию. Падает при любом расхождении.
version-check: build
	@bash tools/version_check.sh

# Сквозной аудит релизного артефакта (защита от дефекта #82): сверяет хеш,
# объявленный в README, с локальной сборкой и с asset'ом в релизе.
# ДЕФЕКТ #93: цель зависела только от `build`, а `zig build` НЕ собирает
# `kernc-hermetic` (это отдельный шаг). Поэтому проверялся УСТАРЕВШИЙ
# бинарник, и цепочка «сходилась» сама с собой, даже когда исходники ушли
# вперёд. Теперь цель сначала СОБИРАЕТ герметичный бинарник.
artifact-check: hermetic
	@$(PYTHON) tools/artifact_check.py

artifact-check-offline: hermetic
	@$(PYTHON) tools/artifact_check.py --offline

# ==== РАСШИРЕННЫЙ КОНТУР ВЕРИФИКАЦИИ ====

# Проверка утечек памяти (GeneralPurposeAllocator, Debug).
memcheck:
	$(ZIG) build test
	$(ZIG) build test-next

# Детектор UB: ReleaseSafe сохраняет проверки границ/переполнений.
ubsafe:
	$(ZIG) test -O ReleaseSafe --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig
	$(ZIG) build test-next -Doptimize=ReleaseSafe

# Стресс .kimg на 1 000 000 объектов (Merkle + случайный доступ).
stress-kimg:
	$(ZIG) build bench-kimg-stress

# Логический стресс Z3-моста (парадоксы, overflow, NIA, Alive2).
smt-stress:
	$(ZIG) build bench-smt-stress

# Полный контур: всё, одной командой.
test-all: build test test-next ubsafe smt-stress perf smt stress bench mutate
	@echo "=== ВСЁ ПРОЙДЕНО ==="

# Формальный контур (ядро + Lean + бенчмарки).
formal-ci: build test test-next lean smt-stress
	@echo "=== FORMAL CI OK ==="

# Ресурсы ОС: утечки FD и зомби-процессы (тесты в z3_bridge.zig).
fd-check:
	$(PYTHON) tools/run_filtered.py "РЕСУРСЫ|ПЧЕЛИНЫЙ"

# ==== ЭШЕЛОНЫ 1-4: ФИНАЛЬНЫЙ ШТУРМ ====

# Эшелон 1: строгое выравнивание памяти и endianness (ARM64/RISC-V safety).
align:
	$(ZIG) build test-align

# Эшелон 2: лавинный штурм хэш-таблицы (100 000 мутаций, защита от Hash Flooding).
avalanche:
	$(PYTHON) tools/cache_avalanche_bench.py

# Детерминированный бенчмарк (машиночитаемо): лавина / цепочки коллизий / χ².
# Это ГЕЙТ, а не украшение: при деградации хэша код возврата ненулевой.
# График для сайта: python3 tools/bench_json.py --html docs/bench/index.html
bench-json:
	$(PYTHON) tools/bench_json.py --json /tmp/kern_bench.json

# Эшелон 3: изнурение пула потоков (128 запросов на 4-8 воркеров, без голодания).
pool:
	$(ZIG) build test-pool

# Эшелон 4: семантический разрыв Lean vs Zig (границы i32/i64).
semantic-gap: lean
	@echo "=== ЭШЕЛОН 4: KernSemanticGap.lean — 8 теорем, 0 sorry ==="

# Финальный штурм: все 4 эшелона одной командой.
echelons: align avalanche pool semantic-gap
	@echo "=== ВСЕ 4 ЭШЕЛОНА ПРОЙДЕНЫ ==="

# ==== СТРОГИЙ ЗАМЕР КОМПИЛЯТОРОВ (0.13 vs 0.17 на ИДЕНТИЧНОМ коде) ====
# См. docs/METRICS.md §26. Бенчмарк не зависит от KERN-модулей (только std +
# libc clock_gettime), поэтому собирается ОБОИМИ компиляторами без правок.
ZIG13 ?= .venv/bin/zig

portable-bench:
	@$(PYTHON) tools/portable_check.py

# ==== CAN-FAIL: доказательство, что проверки СПОСОБНЫ УПАСТЬ ====
# Для каждой проверки искусственно ломается её инвариант; цель ОБЯЗАНА
# покраснеть. Вакуумная проверка тоже даёт RC=0 — этот харнесс это ловит.
# Найдено так: дефекты #32 (CLI возвращал 0 при провале) и #33 (disasm
# молча пропускал исчезнувшую функцию).
canfail:
	$(PYTHON) tools/canfail.py

# БЫСТРАЯ ПРОВЕРКА ЯКОРЕЙ (дефект #113, красный CI #68/#69): кейсы правят
# файлы ЛИТЕРАЛЬНЫМИ подстроками. Устаревший якорь роняет весь шаг CAN-FAIL,
# но только через ~15 минут — здесь это видно за секунду, с именем файла.
# `canfail` вызывает эту же проверку первым делом (fail fast).
canfail-anchors:
	@$(PYTHON) tools/canfail.py --check-anchors

# КТО ПРОВЕРИТ ПРОВЕРЯЮЩЕГО: мета-проверка самого харнесса.
# Синтетические входы проверяют, что вердикт не «врёт в обе стороны»:
#   NOT_VACUOUS / VACUOUS / META_OK / META_FALSE_ALARM.
canfail-selftest:
	$(PYTHON) tools/canfail.py --selftest

# ==== РЕЕСТР ЦЕЛЕЙ (K5) + ПРЕДОХРАНИТЕЛЬ ====
# Падает, если появилась цель, не отнесённая ни к CHECK/MEASURE/BUILD/META/EXTERNAL.
registry:
	$(PYTHON) tools/registry.py

# Геометрия SVG-баннера: подписи не выходят за панели.
# XML-валидность НЕ ловит этот дефект: строка шире контейнера просто
# «уезжает» в соседнюю панель, оставаясь валидным XML. Инструмент умеет
# падать (проверено возвратом длинной строки -> rc=1).
svg-check:
	$(PYTHON) tools/svg_check.py

# ==== CI: ЕДИНЫЙ КОНТУР ПРОВЕРКИ ====
# Обязательный набор стадий. Красный CI = мержить нельзя.
# Найденные вручную дефекты #18/#23/#25/#26/#30/#32-#37 вернутся без этого.
ci:
	./tools/ci.sh

# Быстрая проверка (без Lean и canfail) — для итераций.
ci-fast:
	./tools/ci.sh --fast

# ==== МАТЕМАТИЧЕСКИЙ ИНТЕЛЛЕКТ: ТЕОРИИ SMT (векторы 1-4, 8) ====

# Все 5 теорий одной командой: UNSAT-core, массивы, CHC/Horn, строки, CEGIS.
audit: build
	./zig-out/bin/kernc audit

# UNSAT CORE: локализация конфликтующей строки контракта.
localize:
	$(PYTHON) tools/run_filtered.py "UNSAT CORE"

# ТЕОРИЯ МАССИВОВ: аксиомы Маккарти, алиасинг, выход за границы.
arrays:
	$(PYTHON) tools/run_filtered.py "ARRAY"

# CHC / HORN: синтез инвариантов циклов через Z3 SPACER.
chc:
	$(PYTHON) tools/run_filtered.py "CHC"

# СТРОКИ (QF_S): path traversal, нуль-байт, regex.
strings:
	$(PYTHON) tools/run_filtered.py "STRINGS"

# CEGIS: синтез программы по спецификации (SyGuS).
cegis:
	$(PYTHON) tools/run_filtered.py "CEGIS"

# Весь математический контур тестами.
theories: localize arrays chc strings cegis
	@echo "=== ТЕОРИИ SMT: ВСЁ ПРОЙДЕНО ==="

# ==== СБОИ ПАМЯТИ И АТТЕСТАЦИЯ ====

# Инъекция аппаратных сбоев памяти (SIGBUS/SIGSEGV) — требует libc.
test-fault:
	$(ZIG) build test-fault

# Извлечь 32-байтный seed владельца из PEM (для подписи аттестации).
# Приватный ключ лежит ВНЕ репозитория: ~/kern_owner_private.pem
attest-key:
	@test -f $(HOME)/kern_owner_private.pem || { echo "[!] нет $(HOME)/kern_owner_private.pem"; exit 1; }
	@openssl pkey -in $(HOME)/kern_owner_private.pem -outform DER 2>/dev/null | tail -c 32 > .kern_seed.bin
	@echo "[OK] .kern_seed.bin (32 байта). НЕ КОММИТИТЬ!"

# Аттестовать эталонный образ и проверить сертификат.
attest: build attest-key
	./zig-out/bin/kernc attest sign tests/fixtures/valid_v1_3.kimg -k .kern_seed.bin -o attestation.cert
	./zig-out/bin/kernc attest verify tests/fixtures/valid_v1_3.kimg attestation.cert

# Бенчмарк инвариантов циклов (CHC/Horn, стиль SV-COMP loop-lit / TermCOMP).
chc-bench:
	$(ZIG) build bench-chc

# ==== DO-178C / ISO 26262: ПОКРЫТИЕ, КВАЛИФИКАЦИЯ, ГЕРМЕТИЧНОСТЬ ====

# Покрытие решений (self-instrumented: Zig 0.13 не умеет LLVM coverage).
# Печатает отчёт по инструментированным решениям и падает при < 95 %.
coverage:
	$(PYTHON) tools/coverage_check.py 100

# C-ABI: libkern.so + libkern.a + include/kern.h (встраивание без CLI).
lib:
	$(ZIG) build lib
	@echo "[OK] zig-out/lib/libkern.so + zig-out/include/kern.h"

# Демонстрация C-ABI из Python (ctypes).
# ==== ХАРДКОР-АУДИТ C-ABI (чистый C, строгие флаги) =========================
# Проверяет NULL-указатели, нулевые длины и многопоточность ЧЕРЕЗ РЕАЛЬНУЮ
# библиотеку (в тестовой сборке Zig ветка is_test замыкает compat.io(),
# поэтому tls_io там не проверяется в принципе).
c-abi-test: lib
	@zig cc -Wall -Wextra -Werror -pedantic -std=c11 -Iinclude \
		tests/c_abi_test.c -Lzig-out/lib -lkern -o /tmp/kern_cabi_test
	@LD_LIBRARY_PATH=zig-out/lib /tmp/kern_cabi_test

c-abi-threads: lib
	@zig cc -Wall -Wextra -Werror -pedantic -std=c11 -pthread -Iinclude \
		tests/c_abi_threads.c -Lzig-out/lib -lkern -o /tmp/kern_cabi_th
	@LD_LIBRARY_PATH=zig-out/lib /tmp/kern_cabi_th

capi-demo: lib
	$(PYTHON) examples/capi_demo.py

# Герметичная статическая сборка (x86_64-linux-musl) + проверка воспроизводимости.
hermetic:
	$(ZIG) build hermetic
	@sha256sum zig-out/bin/kernc-hermetic
	@file zig-out/bin/kernc-hermetic | cut -c1-90

# Долгоживущая фаззинг-кампания: 1 000 000 мутаций (0 паник — критерий).
fuzz-1m:
	$(ZIG) build bench-fuzz-ast

# ==== ИССЛЕДОВАТЕЛЬСКИЕ НАПРАВЛЕНИЯ ====

# Слабые модели памяти: литмус-тесты SB/MP (TSO vs ARM64).
litmus:
	$(PYTHON) tools/run_filtered.py "LITMUS"

# Конколическое исполнение (гибрид фаззинга и символьного движка).
concolic:
	$(PYTHON) tools/run_filtered.py "CONCOLIC"

# Вероятностный модел-чекинг DTMC/PCTL.
dtmc:
	$(PYTHON) tools/run_filtered.py "DTMC"

# Абстрактная интерпретация (интервалы + widening/narrowing).
absint:
	$(PYTHON) tools/run_filtered.py "ABSINT"

# Нелинейная арифметика (QF_NRA) и кванторы (E-matching).
nra:
	$(PYTHON) tools/run_filtered.py "NRA|QUANT"

# Невмешательство / гиперсвойства (сайд-каналы, constant-time).
noninterference:
	$(PYTHON) tools/run_filtered.py "NONINTERFERENCE"

# ReDoS-анализ регулярных выражений (CWE-1333).
redos:
	$(PYTHON) tools/run_filtered.py "REDOS"

# Кросс-архитектурная проверка: ARM64 (выравнивание) + POWERPC64 (big-endian).
cross-arch:
	./tools/cross_arch_test.sh

# Весь исследовательский контур.
research: litmus concolic dtmc absint nra noninterference redos
	@echo "=== ИССЛЕДОВАТЕЛЬСКИЙ КОНТУР: ВСЁ ПРОЙДЕНО ==="

# BINARY-LEVEL SOUNDNESS: дифференциальный translation validation +
# constant-time на ассемблере + дизассемблирование финального бинарника.
binlevel:
	./tools/binlevel_verify.sh

# Только семантический зонд (дайджест одного уровня оптимизации).
probe:
	$(PYTHON) tools/probe_check.py

# Детерминированный симуляционный тест (VOPR-стиль, как TigerBeetle).
# Тот же сид → та же история на любой машине. Инварианты I1-I4 + I5 (гонки).
sim:
	$(ZIG) build sim-seeds
	@echo "--- конкурентность (I5) ---"
	$(ZIG) build sim-threads

# ОС-стресс: пайпы, spawn-флуд, инъекция сбоев (границы «клея с ОС»).
os-stress:
	$(ZIG) test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig --test-filter "ОС-СТРЕСС"

# Сигнальный флуд: каскадный штурм сигналами (внешние сигналы во время работы).
flood:
	$(PYTHON) tools/os_signal_flood.py

# Независимая проверка выводов Z3 (Python, структурная + гигиена связываний).
proof-check:
	$(PYTHON) tools/proof_checker.py

# Diff-Disasm: ассемблер Debug vs ReleaseFast — не вырезал ли оптимизатор
# критические проверки (защита от Dead Code Elimination).
disasm:
	$(PYTHON) tools/diff_disasm.py

# SLSA Provenance: аттестат цепочки сборки (бинарник ↔ коммит ↔ команда).
slsa:
	$(PYTHON) tools/slsa_provenance.py --no-build
	@$(PYTHON) tools/slsa_provenance.py --check

# Design by Contract: контракты @deal -> SMT-LIB -> вердикт Z3.
deal:
	$(PYTHON) tools/deal_contracts.py

# Нормативный пакет Tool Qualification (DO-330 / EAL7).
cert:
	@echo "=== TOOL QUALIFICATION PACKAGE ==="
	@ls -1 formal/certification/
	@echo
	@# ДЕФЕКТ #43 (найден can-fail): префикс `@` ГЛУШИЛ ошибку — при
	@# отсутствии файла цель оставалась ЗЕЛЁНОЙ. Теперь файлы проверяются.
	@for f in TRACEABILITY_MATRIX.md TOR.md TAS.md SOUNDNESS_ARGUMENT.md \
	          SECURITY_TARGET.md KNOWN_LIMITATIONS.md; do \
	  test -s "formal/certification/$$f" || { echo "[!] ОТСУТСТВУЕТ или пуст: $$f"; exit 1; }; \
	done
	@n=$$(grep -c '^| TOR-' formal/certification/TRACEABILITY_MATRIX.md); \
	 echo "Требований в матрице трассируемости: $$n"; \
	 test "$$n" -gt 0 || { echo "[!] матрица трассируемости ПУСТА"; exit 1; }

# Сводный аттестационный манифест: каждая строка — РЕАЛЬНЫЙ прогон.
# Если проверка невозможна — печатается NOT RUN (не «PASS»).
audit-manifest:
	@chmod +x tools/audit_manifest.sh
	@./tools/audit_manifest.sh

# MBPP+ через API (генерация + официальная оценка EvalPlus).
mbpp: 
	$(PYTHON) tools/humaneval_api.py --dataset mbpp --model $${MODEL_NAME:?задайте MODEL_NAME=<модель>} \
		--out samples_mbpp.jsonl --workers 8
	./.venv-evalplus/bin/python -m evalplus.evaluate --dataset mbpp --samples samples_mbpp.jsonl
