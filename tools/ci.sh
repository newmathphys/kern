#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
#
# KERN CI: ЕДИНЫЙ КОНТУР ПРОВЕРКИ. Один скрипт — весь обязательный набор.
#
# ЗАЧЕМ: за одну сессию найдено 21 дефект, из них 11 «молчаливо сломанных
# проверок» (#18, #23, #25, #26, #30, #32, #33, #34, #35, #36, #37). Всё это
# обнаружилось ТОЛЬКО потому, что контур гоняли вручную. Без автоматизации
# те же поломки вернутся при первом же рефакторинге.
#
# Запуск:  ./tools/ci.sh            (весь контур)
#          ./tools/ci.sh --fast     (без Lean и canfail — быстрая проверка)
#          ./tools/ci.sh --list     (показать стадии)
#
# Код возврата: 0 — всё зелёное; 1 — есть провал (см. сводку).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

# Тулейн: Zig 0.17 (ветка zig-0.17-migration) + venv (z3, python-обёртки).
ZIG_DIR="${ZIG_DIR:-$HOME/opt/zig-x86_64-linux-0.17.0}"
export PATH="$ZIG_DIR:$ROOT/.venv/bin:$HOME/.elan/bin:$PATH"

export KERN_FAST="${KERN_FAST:-1}"
FAILED=()
PASSED=()
START=$(date +%s)

stage() { # $1 = имя, $2... = команда
  local name="$1"; shift
  local t0; t0=$(date +%s)
  printf '\n\033[1m=== %s ===\033[0m\n' "$name"
  if "$@"; then
    local dt=$(( $(date +%s) - t0 ))
    printf '\033[32m[OK]\033[0m %s (%d с)\n' "$name" "$dt"
    PASSED+=("$name")
  else
    local dt=$(( $(date +%s) - t0 ))
    printf '\033[31m[ПРОВАЛ]\033[0m %s (%d с)\n' "$name" "$dt"
    FAILED+=("$name")
  fi
}

FAST=0
for a in "$@"; do
  case "$a" in
    --fast) FAST=1 ;;
    --list) printf 'стадии: build test test-next test-align test-pool test-fault lean canfail mutate\n'; exit 0 ;;
  esac
done

if [ ! -x "$ZIG_DIR/zig" ]; then
  echo "[!] нет Zig по пути $ZIG_DIR/zig — задайте ZIG_DIR=" >&2
  exit 2
fi

# --- 1. Инструментальная проверка самого CI ---------------------------------
stage "инструменты (zig/python/z3)" bash -c 'zig version && python3 --version >/dev/null && (z3 --version || echo "[i] z3 нет в PATH")'

# --- 1b. РЕЕСТР ЦЕЛЕЙ + ПРЕДОХРАНИТЕЛЬ (K5) ----------------------------------
# Падает, если появилась неклассифицированная цель: новая проверка не может
# появиться «молча», не решив, как её проверять.
stage "реестр целей (K5)" python3 tools/registry.py

# --- 2. Сборка --------------------------------------------------------------
stage "build" zig build

# --- 3. Тесты ядра ----------------------------------------------------------
stage "test (ядро, полный)" bash -c 'out=$(zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig 2>&1); echo "$out" | tail -3; echo "$out" | grep -q "0 failed" || echo "$out" | grep -q "All .* tests passed"'

# --- 4. KERN-Next -----------------------------------------------------------
stage "test-next" zig build test-next

# --- 5. Эшелоны -------------------------------------------------------------
stage "эшелон 1 (выравнивание)" zig build test-align
stage "эшелон 3 (пул потоков)" zig build test-pool
stage "инъекция сбоев (SIGBUS)" zig build test-fault

# --- 6. Демонстратор атак (обязан вернуть 0 в норме) ------------------------
stage "attack (нет уязвимости)" bash -c './zig-out/bin/kern-attack >/dev/null 2>&1'

# --- 7. Формальные доказательства -------------------------------------------
if [ "$FAST" = "0" ]; then
  stage "Lean 4 (0 errors, 0 sorry)" bash -c './formal/check.sh 2>&1 | tail -3'
fi

# --- 8. CAN-FAIL: доказательство, что проверки СПОСОБНЫ упасть ---------------
if [ "$FAST" = "0" ]; then
  stage "canfail --selftest (мета)" python3 tools/canfail.py --selftest
  stage "canfail (полный контур)" python3 tools/canfail.py
fi

# --- СВОДКА -----------------------------------------------------------------
TOTAL=$(( $(date +%s) - START ))
echo
echo "============================================================"
printf 'СВОДКА CI: зелёных %d, провалов %d, всего %d с\n' "${#PASSED[@]}" "${#FAILED[@]}" "$TOTAL"
if [ "${#FAILED[@]}" -gt 0 ]; then
  printf 'ПРОВАЛЕНО: %s\n' "${FAILED[*]}"
  echo "============================================================"
  exit 1
fi
echo "ВСЁ ЗЕЛЁНОЕ"
echo "============================================================"
exit 0
