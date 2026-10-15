#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
#
# ============================================================================
#  KERN: установка проекта Mathlib для формальных доказательств (formal/*.lean).
#
#  ЗАЧЕМ: 5 из 7 Lean-файлов импортируют Mathlib (реальная арифметика ℝ).
#  Mathlib в исходниках собирается часами, поэтому используем ПРЕДСОБРАННЫЙ
#  кэш (`lake exe cache get`) — это ~5–10 минут вместо часов.
#
#  Запуск:  ./formal/setup_mathlib.sh [каталог]
#  По умолчанию каталог: $MATHLIB_PROJ или $HOME/mathlib_proj
#
#  Требуется: elan/lake в PATH ($HOME/.elan/bin) + сеть + ~10 ГБ диска.
# ============================================================================
set -euo pipefail

TARGET="${1:-${MATHLIB_PROJ:-$HOME/mathlib_proj}}"
TOOLCHAIN="${KERN_LEAN_TOOLCHAIN:-leanprover/lean4:v4.34.0}"
MATHLIB_REV="${KERN_MATHLIB_REV:-v4.34.0}"

if ! command -v lake >/dev/null 2>&1 && [ ! -x "$HOME/.elan/bin/lake" ]; then
  echo "[!] lake не найден. Установите elan:"
  echo "    curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y"
  exit 1
fi
export PATH="$HOME/.elan/bin:$PATH"

if [ -f "$TARGET/lakefile.toml" ] || [ -f "$TARGET/lakefile.lean" ]; then
  echo "[i] проект уже есть: $TARGET"
else
  echo "[i] создаю проект Mathlib: $TARGET (rev $MATHLIB_REV)"
  mkdir -p "$TARGET"
  cd "$TARGET"
  cat > lakefile.toml <<EOF
name = "kernmath"
[[require]]
name = "mathlib"
git = "https://github.com/leanprover-community/mathlib4.git"
rev = "$MATHLIB_REV"
EOF
  printf '%s\n' "$TOOLCHAIN" > lean-toolchain
fi

cd "$TARGET"
echo "[i] обновление зависимостей (lake update)"
lake update >/dev/null 2>&1 || lake update

echo "[i] скачивание предсобранного кэша Mathlib (lake exe cache get)"
lake exe cache get

echo "[OK] Mathlib готов: $TARGET"
echo "     Проверка: ./formal/check.sh"
