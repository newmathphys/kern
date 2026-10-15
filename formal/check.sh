#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
#
# ============================================================================
#  KERN: компиляция ВСЕХ формальных доказательств + проверка отсутствия 'sorry'.
#
#  ЧЕСТНОСТЬ: скрипт НЕ печатает «0 errors, 0 sorry», если Mathlib недоступен
#  и часть файлов не скомпилирована. В этом случае он явно сообщает, сколько
#  файлов проверено из скольких, и (при KERN_REQUIRE_MATHLIB=1) падает.
#
#  Mathlib ищется по путям (в порядке приоритета):
#    $MATHLIB_PROJ, $HOME/mathlib_proj, $HOME/mathlib4, $PWD/.mathlib
#  Если не найден и KERN_SETUP_MATHLIB=1 — попытается установить
#  (см. formal/setup_mathlib.sh).
#
#  Запуск:  ./formal/check.sh
#           KERN_REQUIRE_MATHLIB=1 ./formal/check.sh   # строгий режим (CI)
# ============================================================================
set -uo pipefail

LEAN="${LEAN:-$HOME/.elan/bin/lean}"
LAKE="${LAKE:-$HOME/.elan/bin/lake}"
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"

CORE_FILES=(KernAllMath KernDfsTermination)
MATHLIB_FILES=(KernTalk KernTalkND KernConvergence KernZeroCopy KernSemanticGap)

fail=0

# --- 1. Ядро (не требует Mathlib) ------------------------------------------
echo "== core-only (Lean без Mathlib) =="
if [ ! -x "$LEAN" ]; then
  echo "[ПРОВАЛ] Lean не найден: $LEAN"
  echo "         Установка: https://leanprover-community.github.io/install/"
  exit 1
fi
for f in "${CORE_FILES[@]}"; do
  if "$LEAN" "$DIR/$f.lean" >/dev/null 2>&1; then
    echo "  [OK]   $f.lean"
  else
    echo "  [ПРОВАЛ] $f.lean"
    "$LEAN" "$DIR/$f.lean" 2>&1 | tail -12
    fail=1
  fi
done

# --- 2. Поиск проекта Mathlib ----------------------------------------------
find_mathlib() {
  for p in "${MATHLIB_PROJ:-}" "$HOME/mathlib_proj" "$HOME/mathlib4" "$ROOT/.mathlib"; do
    [ -n "$p" ] || continue
    if [ -f "$p/lakefile.toml" ] || [ -f "$p/lakefile.lean" ]; then
      echo "$p"; return 0
    fi
  done
  return 1
}

ML="$(find_mathlib || true)"
if [ -z "$ML" ] && [ "${KERN_SETUP_MATHLIB:-0}" = "1" ]; then
  echo "== Mathlib не найден — установка =="
  if bash "$DIR/setup_mathlib.sh"; then
    ML="$(find_mathlib || true)"
  fi
fi

# --- 3. Mathlib-файлы -------------------------------------------------------
if [ -n "$ML" ]; then
  echo "== Mathlib ($ML) =="
  ml_ok=0
  for f in "${MATHLIB_FILES[@]}"; do
    if ( cd "$ML" && "$LAKE" env lean "$DIR/$f.lean" ) >/dev/null 2>&1; then
      echo "  [OK]   $f.lean"
      ml_ok=$((ml_ok + 1))
    else
      echo "  [ПРОВАЛ] $f.lean"
      ( cd "$ML" && "$LAKE" env lean "$DIR/$f.lean" ) 2>&1 | tail -12
      fail=1
    fi
  done
  checked=$(( ${#CORE_FILES[@]} + ml_ok ))
else
  echo "== Mathlib: НЕДОСТУПЕН =="
  echo "  [!] ${#MATHLIB_FILES[@]} файлов НЕ скомпилированы (нет проекта Mathlib)."
  echo "      Установка: ./formal/setup_mathlib.sh   (или KERN_SETUP_MATHLIB=1)"
  echo "      Пути поиска: \$MATHLIB_PROJ, ~/mathlib_proj, ~/mathlib4, \$PWD/.mathlib"
  checked=${#CORE_FILES[@]}
  if [ "${KERN_REQUIRE_MATHLIB:-0}" = "1" ]; then
    echo "  [ПРОВАЛ] KERN_REQUIRE_MATHLIB=1 — полная проверка обязательна."
    fail=1
  fi
fi

# --- 4. Проверка отсутствия 'sorry' (по ВСЕМ файлам, текстово) -------------
echo "== проверка отсутствия 'sorry' (без учёта комментариев) =="
viol="$(grep -vE '^[[:space:]]*--' "$DIR"/*.lean | grep -nE '\bsorry\b' || true)"
if [ -n "$viol" ]; then
  echo "ОШИБКА: найден sorry:"
  echo "$viol"
  fail=1
fi

total=$(( ${#CORE_FILES[@]} + ${#MATHLIB_FILES[@]} ))
if [ "$fail" -ne 0 ]; then
  echo "LEAN PROOFS: ПРОВАЛ (проверено $checked/$total файлов)"
  exit 1
fi
if [ "$checked" -eq "$total" ]; then
  echo "ALL LEAN PROOFS OK ($total/$total файлов, 0 errors, 0 sorry)"
else
  echo "LEAN PROOFS OK ЧАСТИЧНО: $checked/$total файлов, 0 errors, 0 sorry"
  echo "  (Mathlib-файлы не скомпилированы — см. предупреждение выше)"
fi
