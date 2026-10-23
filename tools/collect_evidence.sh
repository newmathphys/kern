#!/usr/bin/env bash
# N2: рабочие файлы прогона живут в СВОЁМ каталоге, а не в общем /tmp
# (гонка двух прогонов уже портила вердикты). Каталог снимается по выходу.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/kern_work.XXXXXX")"; export WORK
trap 'rm -rf "$WORK"' EXIT INT TERM
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
#
# ============================================================================
#  KERN: СБОРЩИК СВИДЕТЕЛЬСТВ (evidence collector).
#
#  ЗАЧЕМ. Принцип проекта — MEASURED: у каждого ЗАЯВЛЕНИЯ должно быть
#  СВИДЕТЕЛЬСТВО (лог прогона), а не только запись в документации. До этого
#  скрипта в `docs/evidence/` лежало 9 логов из ~25 проверок: результаты
#  canfail, adversarial, capability C-ABI, бенчмарков и cross-check НЕ сохранялись,
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

# 🔴 ДЕФЕКТ #110: мутационный прогон БЕЗ решателя считает скор по УСЕЧЁННОМУ
# набору тестов — 8 из них уходят в `SkipZigTest` (`263 passed; 8 skipped`
# вместо `272 passed`), то есть СВИДЕТЕЛЬСТВО ЛОЖНО, а скор невоспроизводим.
# Если `z3` не в PATH — ищем его в типовых местах (в т.ч. venv с z3-solver).
if ! command -v z3 >/dev/null 2>&1; then
  for c in "$HOME"/*/.venv/bin/z3 "$HOME"/.venv/bin/z3 "$HOME"/.local/bin/z3 \
           /usr/local/bin/z3 /usr/bin/z3; do
    if [ -x "$c" ]; then
      export KERN_Z3_PATH="$c"
      export PATH="$(dirname "$c"):$PATH"
      echo "[i] решатель найден вне PATH: $c (дефект #110)"
      break
    fi
  done
fi

EV="${KERN_EVIDENCE_DIR:-$ROOT/docs/evidence}"
mkdir -p "$EV"

# --- ПРЕДОХРАНИТЕЛЬ #88: снимок FAULTABLE-файлов на СТАРТЕ -------------------
# Харнесс canfail и мутатор НАМЕРЕННО меняют исходники и восстанавливают их.
# Но если файл правит КТО-ТО ЕЩЁ (человек/IDE/параллельный агент) во время
# прогона, свидетельства снимаются при ПРОПАТЧЕННЫХ исходниках и ЛОЖНЫ.
# Снимок + сверка после каждого шага превращают это из «непонятного RC=1 в
# конце» в ТОЧНЫЙ диагноз сразу.
GUARD="${GUARD:-$WORK/kern_evidence_guard.json}"
# ДЕФЕКТЫ #168/#170: перед снятием свидетельств в дереве НЕ ДОЛЖНО быть
# маркеров инъекций и чужих незакоммиченных правок в src/.
python3 tools/injection_guard.py || { echo "[!] свидетельства НЕ снимаются: грязный src/"; exit 2; }
# ДЕФЕКТ #173b: снимок пишется ОДИН раз (защита от перезаписи базиса посреди
# прогона). Новый сбор свидетельств — это НОВЫЙ прогон, значит старый базис
# удаляется ЯВНО здесь, а не молча перезаписывается.
rm -f "$GUARD"
python3 tools/evidence_guard.py --snapshot "$GUARD" || exit 1

FAST=0
for a in "$@"; do [ "$a" = "--fast" ] && FAST=1; done

OK=0; BAD=0; SKIP=0
declare -a FAILED_LIST=()

# --- один прогон: имя, команда -------------------------------------------------
collect() { # $1 = имя лога, $2... = команда
  local name="$1"; shift
  # ONLY=<имя>[,<имя>] — точечная пересборка ТОЛЬКО указанных свидетельств.
  # ЗАЧЕМ: после правки одного инструмента незачем ждать полные ~25 минут,
  # но свидетельство обязано быть снято ТЕМ ЖЕ способом (заголовок, команда,
  # дата, RC) — иначе оно перестанет быть свидетельством.
  if [ -n "${ONLY:-}" ]; then
    case ",$ONLY," in
      *",$name,"*) ;;
      *) printf '  %-28s NOT RUN (ONLY=%s)\n' "$name" "$ONLY"; SKIP=$((SKIP+1)); return 0 ;;
    esac
  fi
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

  # ДЕФЕКТ #333: среда-зависимый лог ОБЯЗАН нести метку базовой линии — иначе
  # гейт свежести не отличает «снято на текущем дереве» от «снято давно».
  # Метка ВЫЧИСЛЯЕТСЯ ИЗ САМОГО ЛОГА (passed+skipped), а не вписывается руками:
  # вписанную можно было бы «поправить» отдельно от свидетельства.
  case "$name" in
    cross_arch)
      local bp sp base
      bp=$(grep -oE '[0-9]+ passed' "$out" | tail -1 | grep -oE '[0-9]+')
      sp=$(grep -oE '[0-9]+ skipped' "$out" | tail -1 | grep -oE '[0-9]+')
      if [ -n "$bp" ] && [ -n "$sp" ]; then
        base=$((bp + sp))
        echo "=== ENV-DEPENDENT: baseline $base (требует qemu-user-static; на машине без QEMU пересъёмка невозможна) ===" >> "$out"
      fi
      ;;
  esac

  { echo; echo "RC=$rc"; } >> "$out"
  local dt=$(( $(date +%s) - t0 ))

  # --- ПРЕДОХРАНИТЕЛЬ #88: сверка после КАЖДОГО шага ----------------------
  # Пока шаг вернул управление, все FAULTABLE-файлы обязаны побайтово
  # совпадать со стартовым снимком. Иначе свидетельство НЕДЕЙСТВИТЕЛЬНО.
  if ! python3 tools/evidence_guard.py --verify "$GUARD" >> "$out" 2>&1; then
    printf 'FAIL  %4d с  ->  %s (ВНЕШНЯЯ ПРАВКА ФАЙЛА!)
' "$dt" "$(basename "$out")"
    BAD=$((BAD+1)); FAILED_LIST+=("$name(guard)")
    return
  fi

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
# 🔴 ДЕФЕКТ #70: `slsa_check` стоял ПОСЛЕ записи свидетельств, а отпечаток
# исходников включает docs/evidence/. Значит сборщик сам делал дерево
# грязным, и аттестат «не сходился» при КАЖДОМ запуске. Проверяем ДО
# первой записи свидетельств.
collect slsa_check          python3 tools/slsa_provenance.py --check
collect core_tests          zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig
collect core_tests_relsafe  zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig -O ReleaseSafe
collect kern_next_tests     bash -c 'rm -rf $WORK/kern_next_evidence_cache; zig build test-next --summary all --cache-dir $WORK/kern_next_evidence_cache; rc=$?; rm -rf $WORK/kern_next_evidence_cache; exit $rc'
collect test_fault          zig build test-fault
collect test_align          zig build test-align
collect test_pool           zig build test-pool

# --- 2. Формальные доказательства -------------------------------------------
collect lean_proofs         bash formal/check.sh

# --- 3. Аттестация и реестр --------------------------------------------------
collect audit_manifest      bash tools/audit_manifest.sh
collect registry            python3 tools/registry.py

# --- 4. Атаки и хардкор ------------------------------------------------------
collect adversarial             bash tools/adversarial_suite.sh
collect capi_cli       python3 tests/capi_cli_suite.py
collect kern_attack         ./zig-out/bin/kern-attack

# --- 4b. Guardrail-прокси (живой перехватчик галлюцинаций) --------------------
# --self-test поднимает сервер на ЭФЕМЕРНОМ порту и проверяет 4 кода:
# health 200 · доказано 200(T) · опровергнуто 422(F) · конфликт 409(B).
collect guardrail         python3 examples/guardrail_proxy.py --self-test

# --- 5. Демонстрация «зелёный CI против математики» --------------------------
collect run_example         make run-example
collect c_abi               make c-abi-test
collect c_abi_threads       make c-abi-threads

# --- 6. Бенчмарки ------------------------------------------------------------
collect bench_perf          zig build bench-perf
collect bench_smt           zig build bench-smt
collect bench_smt_stress    zig build bench-smt-stress
collect bench_chc           zig build bench-chc
collect bench_semantic      zig build bench-semantic
# Хеш-примитив: SHA-256 vs BLAKE3 по размерам блоков (README ссылается на этот лог).
collect hash_bench          zig build bench-hash

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
  # --require-solver: без решателя скор считался бы по УСЕЧЁННОМУ набору
  # (8 тестов -> SkipZigTest) и свидетельство было бы ЛОЖНЫМ (дефект #110).
  collect mutate             python3 tools/mutate_zig.py --max 40 --seed 7 --jobs 4 --require-solver
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
  # Ступень 2 (живой дифференциальный эксплорер) — Ф4: домены расширены,
  # fsck-подобная диагностика в `--explain-task`. Лог обязан сниматься ТЕМ ЖЕ
  # инструментом, что строит вердикт (`trace_explorer`), иначе числа в
  # `quixbugs_full.log` расходятся с кодом.
  collect quixbugs_full     python3 tools/trace_explorer.py /tmp/QuixBugs-master
  # «Обвязка датасета»: падают ли багованные версии на СВОИХ тестах.
  # Это НЕ метрика KERN (дефект #231), но полезно видеть отдельно.
  collect quixbugs_dataset  python3 tools/quixbugs_full.py /tmp/QuixBugs-master
  # Ступень 1 ОТДЕЛЬНО: без fallback Ступени 2 — чтобы цифра 6/40 была
  # воспроизводима одной командой (дефект #239: раньше fallback включался всегда).
  collect quixbugs_stage1    python3 tools/quixbugs_check.py /tmp/QuixBugs-master --stage1-only
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

# --- 10. ЖЁСТКИЙ ГЕЙТ: ни одного лога с RC!=0 --------------------------------
collect evidence_gate      python3 tools/evidence_gate.py
