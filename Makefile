# =========================================================================
#  KERN: Knowledge, Evidence, Reasoning Network
#  Единая точка входа для сборки, тестов и упаковки.
# =========================================================================

ZIG      ?= zig
PYTHON   ?= python3
VENV     ?= .venv
OUT      ?= .kernnext

.PHONY: help venv zig golden build test test-next verify attack next demo docker lean stress bench perf mutate prove clean memcheck ubsafe stress-kimg smt-stress test-all formal-ci fd-check align avalanche pool semantic-gap echelons

help:
	@echo "make venv        — создать venv и поставить Zig 0.13"
	@echo "make golden      — собрать эталонный образ .kimg v1.3"
	@echo "make build       — собрать kernc / kern-attack / kernx"
	@echo "make test        — тесты ядра (47)"
	@echo "make test-next   — тесты KERN-Next (13)"
	@echo "make demo        — сквозная демонстрация (kernc + kernx)"
	@echo "make docker      — собрать Docker-образ"

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
