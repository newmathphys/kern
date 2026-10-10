#!/usr/bin/env bash
# Компиляция ВСЕХ формальных доказательств KERN и проверка отсутствия 'sorry'.
set -euo pipefail
LEAN="${LEAN:-$HOME/.elan/bin/lean}"
MATHLIB_PROJ="${MATHLIB_PROJ:-$HOME/mathlib_proj}"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== core-only (Lean без Mathlib) =="
"$LEAN" "$DIR/KernAllMath.lean"
"$LEAN" "$DIR/KernDfsTermination.lean"

echo "== Mathlib =="
for f in KernTalk KernTalkND KernConvergence KernZeroCopy KernSemanticGap; do
  ( cd "$MATHLIB_PROJ" && lake env lean "$DIR/$f.lean" )
done

echo "== проверка отсутствия 'sorry' (без учёта комментариев) =="
viol="$(grep -vE '^[[:space:]]*--' "$DIR"/*.lean | grep -nE '\bsorry\b' || true)"
if [ -n "$viol" ]; then
  echo "ОШИБКА: найден sorry:"; echo "$viol"; exit 1
fi
echo "ALL LEAN PROOFS OK (0 errors, 0 sorry)"
