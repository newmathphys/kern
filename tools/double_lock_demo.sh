#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
#
# ДВОЙНОЙ ЗАМОК РЕАЛЬНОСТИ: KERN находит вход — ЖИВОЙ компилятор падает на нём же.
#
# ЗАЧЕМ. Обычный анализатор просит верить ему на слово («warning: line 12»). Здесь
# одно и то же утверждение проверяют ДВА независимых судьи:
#   1) KERN: решатель находит КОНТРПРИМЕР (точные значения аргументов);
#   2) gcc с санитайзерами: на ЭТИХ значениях программа физически падает.
# Если второй судья не падает — доказательство не считается (скрипт возвращает 1).
#
# Запуск: bash tools/double_lock_demo.sh [путь_к_kerna]
#   по умолчанию берётся опубликованный апплаенс dist-release/kerna-dist-*/kerna
set -uo pipefail
cd "$(dirname "$0")/.." || exit 9

K="${1:-}"
if [ -z "$K" ]; then
  K="$(ls -d dist-release/kerna-dist-v*/kerna 2>/dev/null | tail -1)"
fi
[ -x "$K" ] || { echo "[!] нет апплаенса: $K (соберите: make kerna-dist)"; exit 2; }
command -v gcc >/dev/null || { echo "[!] нет gcc — второй судья недоступен, доказательства НЕТ"; exit 2; }

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT

cat > "$W/ratio.c" <<'C'
// @kern:requires a >= 0
// @kern:ensures result >= 0
int ratio(int a, int b) {
    return a / b;
}
C

echo "── 1. KERN ищет контрпример"
OUT="$(PATH="$PWD/.venv/bin:$PATH" timeout 300 "$K" "$W/ratio.c" 2>&1)"
echo "$OUT" | grep -E '\[FAIL\]|\[КОНТРПРИМЕР\]' | sed 's/^/   /'
CE="$(echo "$OUT" | grep -oE 'a = -?[0-9]+, b = -?[0-9]+' | head -1)"
[ -n "$CE" ] || { echo "[FAIL] KERN не дал контрпример — проверять нечем"; exit 1; }
A="$(echo "$CE" | sed -E 's/a = (-?[0-9]+).*/\1/')"
B="$(echo "$CE" | sed -E 's/.*b = (-?[0-9]+)/\1/')"
echo "   контрпример: a=$A b=$B"

echo "── 2. ЖИВОЙ gcc -fsanitize=undefined,address на ЭТИХ значениях"
cat > "$W/run.c" <<C
#include <stdio.h>
int ratio(int a, int b) { return a / b; }
int main(void) { printf("результат: %d\n", ratio($A, $B)); return 0; }
C
gcc -fsanitize=undefined,address -o "$W/run" "$W/run.c" 2>"$W/gcc.log" \
  || { echo "[FAIL] не скомпилировалось:"; head -3 "$W/gcc.log"; exit 1; }
RUN="$("$W/run" 2>&1)"; echo "$RUN" | head -3 | sed 's/^/   /'

if echo "$RUN" | grep -qiE 'division by zero|FPE|runtime error'; then
  echo
  echo "[OK] ДВОЙНОЙ ЗАМОК СРАБОТАЛ: KERN нашёл вход — настоящий компилятор на нём упал"
  exit 0
fi
echo
echo "[FAIL] gcc НЕ подтвердил находку KERN — это ложное обвинение, доказательства нет"
exit 1
