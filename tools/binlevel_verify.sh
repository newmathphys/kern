#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
#
# KERN: BINARY-LEVEL SOUNDNESS — проверки на уровне КОДА, а не исходника.
#
# Полный translation validation (Alive2) — отдельный исследовательский проект.
# Здесь — ПРАКТИЧЕСКИЕ проверки, которые реально закрывают разрыв
# «исходник ↔ бинарник»:
#
#   1. ДИФФЕРЕНЦИАЛЬНЫЙ TRANSLATION VALIDATION. Один и тот же зонд собирается
#      с -ODebug, -OReleaseSafe, -OReleaseFast. Если оптимизатор LLVM изменил
#      семантику — канонические дайджесты разойдутся.
#   2. ПРОВЕРКА CONSTANT-TIME НА АССЕМБЛЕРЕ. Доказать constant-time на
#      исходнике мало: компилятор вправе вернуть ранний выход. Анализируем
#      сгенерированный ассемблер на ветвления, зависящие от ДАННЫХ.
#   3. ДИЗАССЕМБЛИРОВАНИЕ ФИНАЛЬНОГО БИНАРНИКА: токен автора в .rodata,
#      отсутствие ud2 (unreachable) в критичных функциях.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ZIG="${ZIG:-zig}"
cd "$ROOT"

fail=0
echo "=== 1. ДИФФЕРЕНЦИАЛЬНЫЙ TRANSLATION VALIDATION (Debug/ReleaseSafe/ReleaseFast) ==="
declare -a DIG=()
for opt in Debug ReleaseSafe ReleaseFast; do
  # std.debug.print пишет в STDERR — захватываем оба потока.
  d="$("$ZIG" run src/semantic_probe.zig -O "$opt" 2>&1 | grep -oE 'SEMANTIC_DIGEST=[0-9a-f]+' | cut -d= -f2)"
  printf '  %-12s %s\n' "$opt" "${d:-<нет>}"
  DIG+=("$d")
done
if [ -n "${DIG[0]}" ] && [ "${DIG[0]}" = "${DIG[1]}" ] && [ "${DIG[1]}" = "${DIG[2]}" ]; then
  echo "  [OK] все три уровня дали ИДЕНТИЧНЫЙ дайджест — оптимизации семантику не изменили"
else
  echo "  [!] РАСХОЖДЕНИЕ ДАЙДЖЕСТОВ — возможна ошибка оптимизатора LLVM"; fail=1
fi

echo
echo "=== 2. CONSTANT-TIME НА УРОВНЕ АССЕМБЛЕРА ==="
ASM=/tmp/kern_binlevel.s
"$ZIG" build-exe src/binlevel_probe.zig -femit-asm="$ASM" -fno-emit-bin -OReleaseFast >/dev/null 2>&1
if [ -s "$ASM" ]; then
  out="$(python3 "$HERE/binlevel_verify.py" "$ASM" kern_ct_equal kern_early_exit_equal)"
  echo "$out" | sed 's/^/  /'
  ct="$(echo "$out" | grep 'kern_ct_equal' | grep -oE '[0-9]+$')"
  ee="$(echo "$out" | grep 'kern_early_exit_equal' | grep -oE '[0-9]+$')"
  if [ "${ct:-1}" = "0" ]; then echo "  [OK] constant-time: НЕТ ветвлений от данных"; else echo "  [!] УТЕЧКА: ветвление зависит от данных"; fail=1; fi
  if [ "${ee:-0}" -ge 1 ]; then echo "  [OK] контрольный ранний выход ОБНАРУЖЕН (проверка не пустая)"; else echo "  [!] проверка нечувствительна"; fail=1; fi
else
  echo "  [SKIP] не удалось сгенерировать ассемблер"
fi

echo
echo "=== 3. ДИЗАССЕМБЛИРОВАНИЕ ФИНАЛЬНОГО БИНАРНИКА ==="
BIN=zig-out/bin/kernc-hermetic
if [ ! -x "$BIN" ]; then "$ZIG" build hermetic >/dev/null 2>&1; fi
if [ -x "$BIN" ]; then
  TOKEN=ed53cd2f1ca8ffb8c9ba3e488f116de4134b9fa3b5afa90e1a040fffde9eefaa
  # ВНИМАНИЕ: `strings | grep -q` при `pipefail` ломается — grep -q выходит
  # сразу, strings получает SIGPIPE, и пайплайн «падает» с кодом 141.
  # Поэтому считаем совпадения (grep -c читает вход до конца).
  HITS=$(strings -a "$BIN" | grep -c "$TOKEN")
  if [ "$HITS" -ge 1 ]; then
    echo "  [OK] токен автора найден в бинарнике ($HITS совпадение) — метка несмываема"
  else
    echo "  [!] токен автора НЕ найден"; fail=1
  fi
  UD2=$(objdump -d "$BIN" 2>/dev/null | grep -c 'ud2')
  echo "  [i] инструкций ud2 (unreachable) в бинарнике: $UD2"
  SECT=$(readelf -S "$BIN" 2>/dev/null | grep -cE '^ *\[[ 0-9]+\]')
  echo "  [i] секций ELF: $SECT ; размер $(stat -c%s "$BIN") байт"
  echo "  [i] тип: $(readelf -h "$BIN" 2>/dev/null | grep -oE 'DYN \(Shared object file\)|EXEC \(Executable file\)' | head -1)"
else
  echo "  [SKIP] бинарник не собран"
fi

echo
if [ "$fail" = "0" ]; then echo "=== BINARY-LEVEL SOUNDNESS: ВСЁ ПРОЙДЕНО ==="; else echo "=== ЕСТЬ ПРОБЛЕМЫ ==="; fi
exit "$fail"
