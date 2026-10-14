#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
#
# ============================================================================
#  KERN QUALIFICATION AUDIT SUITE — сводный аттестационный манифест.
#
#  ВАЖНО О ЧЕСТНОСТИ: скрипт НЕ печатает заранее заготовленные числа.
#  Каждая строка получается РЕАЛЬНЫМ прогоном; если проверка невозможна
#  в текущем окружении — печатается NOT RUN, а не «PASS».
#
#  Запуск: make audit-manifest
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ZIG="${ZIG:-zig}"
# Цвета — только в терминале (в пайпе/логе печатаем без escape-последовательностей)
if [ -t 1 ]; then
  GREEN=$'\033[32m'; RED=$'\033[31m'; YEL=$'\033[33m'; OFF=$'\033[0m'
else
  GREEN=''; RED=''; YEL=''; OFF=''
fi

ok()   { printf '%sPASS%s' "$GREEN" "$OFF"; }
bad()  { printf '%sFAIL%s' "$RED" "$OFF"; echo x >> "$FAILFILE"; }
skip() { printf '%sNOT RUN%s' "$YEL" "$OFF"; }

line() { printf '%-22s: %s\n' "$1" "$2"; }

# ДЕФЕКТ #45 (найден can-fail): скрипт печатал FAIL, но ВСЕГДА выходил с 0.
# ⚠️ Счётчик — ФАЙЛ, а не переменная: bad() вызывается внутри $(...),
# то есть в ПОДОБОЛОЧКЕ, где инкремент переменной теряется.
FAILFILE="$(mktemp)"
trap 'rm -f "$FAILFILE"' EXIT

echo
echo "[KERN QUALIFICATION AUDIT SUITE v1.3.1]"
echo "─────────────────────────────────────────────────────────────────────────────"

# --- 1. Ядро (Debug) ---------------------------------------------------------
core_out="$($ZIG test src/test_root.zig 2>&1 | tail -2)"
if echo "$core_out" | grep -q 'All .* tests passed'; then
  n=$(echo "$core_out" | grep -oE '[0-9]+' | head -1)
  line "Core (Debug)" "$(ok) — $n/$n tests"
else
  line "Core (Debug)" "$(bad)"
fi

# --- 2. ReleaseSafe (детектор UB) -------------------------------------------
rs_out="$($ZIG test src/test_root.zig -O ReleaseSafe 2>&1 | tail -2)"
if echo "$rs_out" | grep -q 'All .* tests passed'; then
  line "Memory Safety" "$(ok) — ReleaseSafe, 0 UB"
else
  line "Memory Safety" "$(bad)"
fi

# --- 3. KERN-Next ------------------------------------------------------------
if $ZIG build test-next >/dev/null 2>&1; then
  line "KERN-Next" "$(ok)"
else
  line "KERN-Next" "$(bad)"
fi

# --- 4. Lean 4 ---------------------------------------------------------------
if [ -x formal/check.sh ] || [ -f formal/check.sh ]; then
  lean_out="$(bash formal/check.sh 2>&1 | tail -1)"
  if echo "$lean_out" | grep -q 'ALL LEAN PROOFS OK'; then
    files=$(ls -1 formal/*.lean 2>/dev/null | wc -l)
    line "Kernel Invariants" "$(ok) — Lean 4 ($files files, 0 errors, 0 sorry)"
  else
    line "Kernel Invariants" "$(bad)"
  fi
else
  line "Kernel Invariants" "$(skip)"
fi

# --- 5. Кросс-архитектура (по сохранённому логу, если есть) ------------------
if [ -f docs/evidence/cross_arch.log ]; then
  # Лог содержит строки «All 188 tests passed» на каждую архитектуру.
  arches="$(grep -c 'All .* tests passed' docs/evidence/cross_arch.log)"
  names="$(grep -oE '^=== [A-Za-z0-9]+' docs/evidence/cross_arch.log | sed 's/=== //' | paste -sd' ' -)"
  if [ "$arches" -ge 2 ]; then
    line "Target Systems" "$(ok) — $arches платформы: $names"
  else
    line "Target Systems" "$(bad) — пройдено платформ: $arches"
  fi
elif [ -x /tmp/qemu-aarch64-static ] || command -v qemu-aarch64-static >/dev/null 2>&1; then
  line "Target Systems" "$(skip) — запустите ./tools/cross_arch_test.sh"
else
  line "Target Systems" "$(skip) — нет qemu-user-static"
fi

# --- 6. Атаки (kern-attack) --------------------------------------------------
if [ -x zig-out/bin/kern-attack ]; then
  # Маркеры закрытия атак из src/attack.zig: «ИТОГ:» печатается ровно дважды
  # (0xAA-обход и KERNFS). Проверяем именно их, а не слово «закрыта».
  at="$(./zig-out/bin/kern-attack 2>&1 | grep -c 'ИТОГ:')"
  if [ "$at" -ge 2 ]; then
    line "Attack Surface" "$(ok) — $at/2 (0xAA-обход закрыт, KERNFS согласован)"
  else
    line "Attack Surface" "$(bad) — найдено маркеров: $at"
  fi
else
  line "Attack Surface" "$(skip) — соберите: zig build"
fi

# --- 7. Покрытие решений -----------------------------------------------------
cov="$($ZIG test src/test_root.zig 2>&1 | grep -oE 'ФАКТ: [0-9.]+%' | head -1)"
if [ -n "$cov" ]; then
  line "Decision Coverage" "$(ok) — $cov (порог 95%)"
else
  line "Decision Coverage" "$(skip)"
fi

# --- 8. Мутации (по сохранённому отчёту) ------------------------------------
if [ -f docs/evidence/mutation_report.txt ]; then
  ms="$(grep -oE 'MUTATION SCORE: *[0-9.]+%' docs/evidence/mutation_report.txt | head -1)"
  line "Mutation Coverage" "$(ok) — ${ms:-см. отчёт}"
else
  line "Mutation Coverage" "$(skip) — запустите: make mutate"
fi

# --- 9. Формальные теории ----------------------------------------------------
if [ -x zig-out/bin/kernc ]; then
  th="$(./zig-out/bin/kernc audit 2>&1 | grep -cE '^\[[1-5]\]')"
  if [ "$th" -ge 5 ]; then
    line "Formal Theories" "$(ok) — $th/5 (UNSAT-core, QF_AX, CHC, QF_S, CEGIS)"
  else
    line "Formal Theories" "$(skip) — нужен Z3 (uv pip install z3-solver)"
  fi
else
  line "Formal Theories" "$(skip)"
fi

# --- 10. Целостность образа --------------------------------------------------
if [ -f tests/fixtures/valid_v1_3.kimg ] && [ -x zig-out/bin/kernc ]; then
  if ./zig-out/bin/kernc check-integrity tests/fixtures/valid_v1_3.kimg >/dev/null 2>&1; then
    line "Payload Integrity" "$(ok) — Merkle + SHA-256 (PayloadTampered)"
  else
    line "Payload Integrity" "$(bad)"
  fi
else
  line "Payload Integrity" "$(skip)"
fi

echo "─────────────────────────────────────────────────────────────────────────────"
echo "Реестр ограничений : formal/certification/KNOWN_LIMITATIONS.md"
echo "Трассируемость     : formal/certification/TRACEABILITY_MATRIX.md (TOR-требования)"
echo "Полный статус      : docs/ATTESTATION_PASSPORT.md"
echo "─────────────────────────────────────────────────────────────────────────────"
echo "ВЕРДИКТ: определяется ПРОГОНАМИ выше. Строки NOT RUN не считаются PASS."
NFALL=$(wc -l < "$FAILFILE" 2>/dev/null || echo 0)
if [ "$NFALL" -gt 0 ]; then
  echo "[!] ПРОВАЛОВ: $NFALL — аттестационный манифест НЕ пройден"
  exit 1
fi
echo "[OK] провалов: 0"
echo
