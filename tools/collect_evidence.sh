#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
#
# ============================================================================
#  KERN: СБОРЩИК СВИДЕТЕЛЬСТВ (evidence collector).
#
#  ЗАЧЕМ. Принцип проекта — MEASURED: у каждого ЗАЯВЛЕНИЯ должно быть
#  СВИДЕТЕЛЬСТВО (лог прогона), а не только запись в документации. До этого
#  скрипта в `docs/evidence/` лежало 9 логов из ~25 проверок: результаты
#  canfail, torture, hardcore C-ABI, бенчмарков и cross-check НЕ сохранялись,
#  то есть были недоказуемы для внешнего читателя.
#
#  ЧТО ДЕЛАЕТ. Прогоняет каждую проверку и сохраняет ЕЁ ПОЛНЫЙ вывод в
#  docs/evidence/<имя>.log вместе с кодом возврата. Печатает сводку.
#
#  Запуск:  make evidence          (полный, ~25 мин)
#           make evidence-fast     (без мутаций/фаззинга/двух сборок)
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${ZIG_DIR:-$HOME/opt/zig-x86_64-linux-0.17.0}:$ROOT/.venv/bin:$HOME/.elan/bin:$PATH"

EV="$ROOT/docs/evidence"
mkdir -p "$EV"

FAST=0
for a in "$@"; do [ "$a" = "--fast" ] && FAST=1; done

OK=0; BAD=0; SKIP=0
declare -a FAILED_LIST=()

# --- один прогон: имя, команда -------------------------------------------------
collect() { # $1 = имя лога, $2... = команда
  local name="$1"; shift
  local out="$EV/$name.log"
  printf '  %-28s ' "$name"
  local t0; t0=$(date +%s)
  {
    echo "=== KERN EVIDENCE: $name ==="
    echo "=== команда: $* ==="
    echo "=== дата: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
    echo
  } > "$out"
  "$@" >> "$out" 2>&1
  local rc=$?
  { echo; echo "RC=$rc"; } >> "$out"
  local dt=$(( $(date +%s) - t0 ))
  if [ "$rc" = "0" ]; then
    printf 'OK    %4d с  ->  %s\n' "$dt" "$(basename "$out")"
    OK=$((OK+1))
  else
    printf 'FAIL  %4d с  ->  %s (RC=%s)\n' "$dt" "$(basename "$out")" "$rc"
    BAD=$((BAD+1)); FAILED_LIST+=("$name")
  fi
}

skip() { printf '  %-28s NOT RUN (%s)\n' "$1" "$2"; SKIP=$((SKIP+1)); }

echo
echo "[KERN EVIDENCE COLLECTOR]  режим: $([ "$FAST" = 1 ] && echo быстрый || echo полный)"
echo "─────────────────────────────────────────────────────────────────────────"

# --- 1. Ядро и KERN-Next -----------------------------------------------------
collect core_tests          zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig
collect core_tests_relsafe  zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig -O ReleaseSafe
collect kern_next_tests     zig build test-next
collect test_fault          zig build test-fault
collect test_align          zig build test-align
collect test_pool           zig build test-pool

# --- 2. Формальные доказательства -------------------------------------------
collect lean_proofs         bash formal/check.sh

# --- 3. Аттестация и реестр --------------------------------------------------
collect audit_manifest      bash tools/audit_manifest.sh
collect registry            python3 tools/registry.py
collect slsa_check          python3 tools/slsa_provenance.py --check

# --- 4. Атаки и хардкор ------------------------------------------------------
collect torture             bash tools/torture_kern.sh
collect hardcore_capi       python3 tests/hardcore_capi_smt.py
collect kern_attack         ./zig-out/bin/kern-attack

# --- 4b. Guardrail-прокси (живой перехватчик галлюцинаций) --------------------
# --self-test поднимает сервер на ЭФЕМЕРНОМ порту и проверяет 4 кода:
# health 200 · доказано 200(T) · опровергнуто 422(F) · конфликт 409(B).
collect guardrail         python3 examples/guardrail_proxy.py --self-test

# --- 5. Демонстрация «зелёный CI против математики» --------------------------
collect run_example         make run-example

# --- 6. Бенчмарки ------------------------------------------------------------
collect bench_perf          zig build bench-perf
collect bench_smt           zig build bench-smt
collect bench_smt_stress    zig build bench-smt-stress
collect bench_chc           zig build bench-chc
collect bench_semantic      zig build bench-semantic

# --- 7. Тяжёлые (пропускаются в --fast) -------------------------------------
if [ "$FAST" = 1 ]; then
  skip canfail   "--fast"
  skip mutate    "--fast"
  skip fuzz_1m   "--fast"
  skip kimg_1m   "--fast"
  skip avalanche "--fast"
  skip cross_arch "--fast (QEMU долго)"
else
  collect canfail            python3 tools/canfail.py
  collect mutate             python3 tools/mutate_zig.py --max 40 --seed 7
  collect fuzz_1m            zig build bench-fuzz-ast
  collect kimg_1m            zig build bench-kimg-stress
  collect avalanche          python3 tools/cache_avalanche_bench.py
  collect cross_arch         bash tools/cross_arch_test.sh
fi

# --- 8. Внешние сверки (только если есть инструменты/датасеты) ---------------
if command -v z3 >/dev/null 2>&1; then
  collect solver_crosscheck  python3 tools/solver_crosscheck.py
else
  skip solver_crosscheck "нет z3"
fi
if [ -d /tmp/QuixBugs-master ]; then
  collect quixbugs           python3 tools/quixbugs_full.py /tmp/QuixBugs-master
else
  skip quixbugs "нет /tmp/QuixBugs-master (git clone jkoppel/QuixBugs)"
fi

# --- 9. Телеметрия -----------------------------------------------------------
# ВАЖНО: `--quick` пропускает 3 проверки (2 сборки, мутации, фаззинг) и потому
# ЗАКОННО даёт RC=1 (не 100/100). Поэтому полный прогон — только в полном
# режиме, а в --fast телеметрия честно помечается NOT RUN.
if [ "$FAST" = 1 ]; then
  skip telemetry "--fast (полный стенд требует ~12 мин)"
else
  collect telemetry          python3 tools/measure_all_kern.py --out telemetry_report.json
fi

echo "─────────────────────────────────────────────────────────────────────────"
echo "СВИДЕТЕЛЬСТВ: OK=$OK  FAIL=$BAD  NOT RUN=$SKIP"
if [ "$BAD" -gt 0 ]; then
  echo "ПРОВАЛЫ: ${FAILED_LIST[*]}"
  exit 1
fi
echo "Все прогоны сохранены в docs/evidence/ — заявления подкреплены логами."
