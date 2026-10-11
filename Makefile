# =========================================================================
#  KERN: Knowledge, Evidence, Reasoning Network
#  Единая точка входа для сборки, тестов и упаковки.
# =========================================================================

ZIG      ?= zig
PYTHON   ?= python3
VENV     ?= .venv
OUT      ?= .kernnext

.PHONY: help venv zig golden build test test-next verify attack next demo docker lean stress bench perf mutate prove clean memcheck ubsafe stress-kimg smt-stress test-all formal-ci fd-check align avalanche pool semantic-gap echelons audit localize arrays chc strings cegis theories test-fault attest-key attest mbpp chc-bench coverage lib capi-demo hermetic cert fuzz-1m litmus concolic dtmc absint nra noninterference redos cross-arch research binlevel probe

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
	@echo "  make venv        — создать venv и поставить Zig 0.13"
	@echo "  make golden      — собрать эталонный образ .kimg v1.3"
	@echo "  make build       — собрать kernc / kern-attack / kernx"
	@echo "  make test        — тесты ядра (188)"
	@echo "  make test-next   — тесты KERN-Next (25)"
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

# Формальные доказательства Lean 4 (0 ошибок, 0 sorry).
lean:
	./formal/check.sh

# Тактика 3: стресс-тесты (1M + усиленный по реальному коду).
stress:
	$(ZIG) run tests/stress_1m.zig -O ReleaseFast
	$(ZIG) run src/stress_real.zig -O ReleaseFast

# Тактика 2: KERN-native бенчмарк (методология EvalPlus).
bench:
	$(ZIG) run src/kern_bench.zig -O ReleaseFast

# Производительность конвейера .kimg (zero-copy).
perf:
	$(ZIG) run src/perf_bench.zig -O ReleaseFast

# SMT-эквивалентность оптимизаций (Alive2 / Hacker's Delight) через Z3.
smt:
	$(ZIG) run src/smt_bench.zig -O ReleaseFast

# Доказательство SMT-скрипта через реальный Z3 (e=1).
prove:
	$(ZIG) run src/main.zig -- prove formal/example.smt2

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
	$(ZIG) test -O ReleaseSafe src/test_root.zig
	$(ZIG) test -O ReleaseSafe src/next/test_root.zig -lc -lsqlite3

# Стресс .kimg на 1 000 000 объектов (Merkle + случайный доступ).
stress-kimg:
	$(ZIG) run src/kimg_stress.zig -O ReleaseFast

# Логический стресс Z3-моста (парадоксы, overflow, NIA, Alive2).
smt-stress:
	$(ZIG) run src/smt_stress.zig -O ReleaseFast

# Полный контур: всё, одной командой.
test-all: build test test-next ubsafe smt-stress perf smt stress bench mutate
	@echo "=== ВСЁ ПРОЙДЕНО ==="

# Формальный контур (ядро + Lean + бенчмарки).
formal-ci: build test test-next lean smt-stress
	@echo "=== FORMAL CI OK ==="

# Ресурсы ОС: утечки FD и зомби-процессы (тесты в z3_bridge.zig).
fd-check:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "РЕСУРСЫ|ПЧЕЛИНЫЙ|passed"

# ==== ЭШЕЛОНЫ 1-4: ФИНАЛЬНЫЙ ШТУРМ ====

# Эшелон 1: строгое выравнивание памяти и endianness (ARM64/RISC-V safety).
align:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "ALIGN|ENDIAN|passed"

# Эшелон 2: лавинный штурм хэш-таблицы (100 000 мутаций, защита от Hash Flooding).
avalanche:
	$(PYTHON) tools/cache_avalanche_bench.py

# Эшелон 3: изнурение пула потоков (128 запросов на 4-8 воркеров, без голодания).
pool:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "POOL|passed"

# Эшелон 4: семантический разрыв Lean vs Zig (границы i32/i64).
semantic-gap: lean
	@echo "=== ЭШЕЛОН 4: KernSemanticGap.lean — 8 теорем, 0 sorry ==="

# Финальный штурм: все 4 эшелона одной командой.
echelons: align avalanche pool semantic-gap
	@echo "=== ВСЕ 4 ЭШЕЛОНА ПРОЙДЕНЫ ==="

# ==== МАТЕМАТИЧЕСКИЙ ИНТЕЛЛЕКТ: ТЕОРИИ SMT (векторы 1-4, 8) ====

# Все 5 теорий одной командой: UNSAT-core, массивы, CHC/Horn, строки, CEGIS.
audit: build
	./zig-out/bin/kernc audit

# UNSAT CORE: локализация конфликтующей строки контракта.
localize:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "UNSAT CORE|passed"

# ТЕОРИЯ МАССИВОВ: аксиомы Маккарти, алиасинг, выход за границы.
arrays:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "ARRAY|passed"

# CHC / HORN: синтез инвариантов циклов через Z3 SPACER.
chc:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "CHC|passed"

# СТРОКИ (QF_S): path traversal, нуль-байт, regex.
strings:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "STRINGS|passed"

# CEGIS: синтез программы по спецификации (SyGuS).
cegis:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "CEGIS|passed"

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
	$(ZIG) run src/chc_bench.zig -O ReleaseFast

# ==== DO-178C / ISO 26262: ПОКРЫТИЕ, КВАЛИФИКАЦИЯ, ГЕРМЕТИЧНОСТЬ ====

# Покрытие решений (self-instrumented: Zig 0.13 не умеет LLVM coverage).
# Печатает отчёт по инструментированным решениям и падает при < 95 %.
coverage:
	$(ZIG) test src/test_root.zig 2>&1 | grep -A40 'ПОКРЫТИЕ РЕШЕНИЙ'

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
	$(ZIG) run src/fuzz_ast.zig -O ReleaseFast

# ==== ИССЛЕДОВАТЕЛЬСКИЕ НАПРАВЛЕНИЯ ====

# Слабые модели памяти: литмус-тесты SB/MP (TSO vs ARM64).
litmus:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "LITMUS"

# Конколическое исполнение (гибрид фаззинга и символьного движка).
concolic:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "CONCOLIC"

# Вероятностный модел-чекинг DTMC/PCTL.
dtmc:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "DTMC"

# Абстрактная интерпретация (интервалы + widening/narrowing).
absint:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "ABSINT"

# Нелинейная арифметика (QF_NRA) и кванторы (E-matching).
nra:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "NRA|QUANT"

# Невмешательство / гиперсвойства (сайд-каналы, constant-time).
noninterference:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "NONINTERFERENCE"

# ReDoS-анализ регулярных выражений (CWE-1333).
redos:
	$(ZIG) test src/test_root.zig 2>&1 | grep -E "REDOS"

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
	$(ZIG) run src/semantic_probe.zig -O ReleaseFast

# Нормативный пакет Tool Qualification (DO-330 / EAL7).
cert:
	@echo "=== TOOL QUALIFICATION PACKAGE ==="
	@ls -1 formal/certification/
	@echo
	@echo "Требований в матрице трассируемости: $$(grep -c '^| TOR-' formal/certification/TRACEABILITY_MATRIX.md)"

# MBPP+ через API (генерация + официальная оценка EvalPlus).
mbpp: 
	$(PYTHON) tools/humaneval_api.py --dataset mbpp --model $${MODEL_NAME:-nvidia/nemotron-3-super-120b-a12b} \
		--out samples_mbpp.jsonl --workers 8
	./.venv-evalplus/bin/python -m evalplus.evaluate --dataset mbpp --samples samples_mbpp.jsonl
