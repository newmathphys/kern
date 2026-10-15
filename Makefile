# =========================================================================
#  KERN: Knowledge, Evidence, Reasoning Network
#  Единая точка входа для сборки, тестов и упаковки.
# =========================================================================

ZIG      ?= zig
PYTHON   ?= python3
VENV     ?= .venv
OUT      ?= .kernnext

.PHONY: help venv zig golden build test test-next verify attack next demo run-example torture telemetry telemetry-quick evidence evidence-fast guardrail docker lean stress bench perf mutate prove clean memcheck ubsafe stress-kimg smt-stress test-all formal-ci fd-check align avalanche pool semantic-gap echelons audit localize arrays chc strings cegis theories test-fault attest-key attest mbpp chc-bench coverage lib capi-demo hermetic cert fuzz-1m litmus concolic dtmc absint nra noninterference redos portable-bench canfail registry ci ci-fast cross-arch research binlevel probe

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
torture: build
	bash tools/torture_kern.sh

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
mutate:
	$(PYTHON) tools/mutate_zig.py --max 40 --seed 7

clean:
	rm -rf zig-out .zig-cache $(OUT) release.kimg report.md agent_packet.json PROJECT_CANONICAL_SPEC.kern.md

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

# КТО ПРОВЕРИТ ПРОВЕРЯЮЩЕГО: мета-проверка самого харнесса.
# Синтетические входы проверяют, что вердикт не «врёт в обе стороны»:
#   NOT_VACUOUS / VACUOUS / META_OK / META_FALSE_ALARM.
canfail-selftest:
	$(PYTHON) tools/canfail.py --selftest

# ==== РЕЕСТР ЦЕЛЕЙ (K5) + ПРЕДОХРАНИТЕЛЬ ====
# Падает, если появилась цель, не отнесённая ни к CHECK/MEASURE/BUILD/META/EXTERNAL.
registry:
	$(PYTHON) tools/registry.py

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
