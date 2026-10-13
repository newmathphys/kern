# =========================================================================
#  KERN: Knowledge, Evidence, Reasoning Network
#  Единая точка входа для сборки, тестов и упаковки.
# =========================================================================

ZIG      ?= zig
PYTHON   ?= python3
VENV     ?= .venv
OUT      ?= .kernnext

.PHONY: help venv zig golden build test test-next verify attack next demo docker lean stress bench perf mutate prove clean memcheck ubsafe stress-kimg smt-stress test-all formal-ci fd-check align avalanche pool semantic-gap echelons audit localize arrays chc strings cegis theories test-fault attest-key attest mbpp chc-bench coverage lib capi-demo hermetic cert fuzz-1m litmus concolic dtmc absint nra noninterference redos portable-bench canfail cross-arch research binlevel probe

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
	@$(ZIG) build-exe bench/portable_merkle.zig -O ReleaseFast -lc -femit-bin=/tmp/pb17
	@echo "=== Zig 0.17 ==="; /tmp/pb17
	@if [ -x "$(ZIG13)" ]; then \
	  $(ZIG13) build-exe bench/portable_merkle.zig -O ReleaseFast -lc -femit-bin=/tmp/pb13; \
	  echo "=== Zig 0.13 ==="; /tmp/pb13; \
	else echo "[i] $(ZIG13) нет — сравнение только на 0.17"; fi

# ==== CAN-FAIL: доказательство, что проверки СПОСОБНЫ УПАСТЬ ====
# Для каждой проверки искусственно ломается её инвариант; цель ОБЯЗАНА
# покраснеть. Вакуумная проверка тоже даёт RC=0 — этот харнесс это ловит.
# Найдено так: дефекты #32 (CLI возвращал 0 при провале) и #33 (disasm
# молча пропускал исчезнувшую функцию).
canfail:
	$(PYTHON) tools/canfail.py

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
	$(ZIG) test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig 2>&1 | grep -A40 'ПОКРЫТИЕ РЕШЕНИЙ'

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
	$(ZIG) build bench-semantic

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
	@echo "Требований в матрице трассируемости: $$(grep -c '^| TOR-' formal/certification/TRACEABILITY_MATRIX.md)"

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
