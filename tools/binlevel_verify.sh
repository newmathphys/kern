#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
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
  # ⚠️ ФИКС 0.17: `zig run src/semantic_probe.zig` НЕ РАБОТАЕТ — модули
  # `compat`/`owner`/`atomic` передаёт только сборочная система. Раньше
  # дайджесты получались ПУСТЫМИ и скрипт выдавал ЛОЖНОЕ «расхождение
  # оптимизатора LLVM» (дефект #29).
  bin="/tmp/kern_semprobe_$opt"
  "$ZIG" build-exe --dep compat --dep owner --dep atomic \
      -Mroot=src/semantic_probe.zig \
      -Mcompat=src/compat.zig -Mowner=src/owner.zig -Matomic=src/atomic_write.zig \
      -O "$opt" -femit-bin="$bin" >/dev/null 2>&1
  # std.debug.print пишет в STDERR — захватываем оба потока.
  d="$("$bin" 2>&1 | grep -oE 'SEMANTIC_DIGEST=[0-9a-f]+' | cut -d= -f2)"
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
BIN2=/tmp/kern_binlevel_probe
# ⚠️ ФИКС 0.17: `-femit-asm` в этом тулчейне НЕ создаёт файл (молча no-op).
# Поэтому ассемблер получаем ДИЗАССЕМБЛИРОВАНИЕМ собранного бинарника.
"$ZIG" build-exe --dep compat -Mroot=src/binlevel_probe.zig -Mcompat=src/compat.zig \
    -OReleaseFast -femit-bin="$BIN2" >/dev/null 2>&1
if [ -x "$BIN2" ]; then
  # Приводим вывод objdump к формату, который ждёт binlevel_verify.py:
  #   "0000000000001234 <kern_ct_equal>:"  ->  "kern_ct_equal:"
  #   "  1234:\tmov ..."                    ->  "mov ..."
  # ВАЖНО: `-M intel` — анализатор написан под Intel-синтаксис (dst, src).
  # С AT&T-синтаксисом (по умолчанию) распространение taint идёт НАОБОРОТ
  # и проверка становится вакуумной (дефект #30).
  objdump -d -M intel --no-show-raw-insn "$BIN2" 2>/dev/null \
    | sed -E -e 's/^[0-9a-f]+ <([^>]+)>:$/\1:/' \
             -e 's/^[A-Za-z_][A-Za-z0-9_]*\.(kern_[A-Za-z0-9_]*):$/\1:/' \
             -e 's/^ +[0-9a-f]+:\t//' \
             -e '/^$/d' > "$ASM"
fi
if [ -s "$ASM" ]; then
  # ⚠️ ФИКС (#30): анализировать надо РЕАЛЬНЫЕ функции сравнения, а НЕ
  # экспорт-обёртки `kern_ct_equal` / `kern_early_exit_equal`: обёртка —
  # это всего лишь `push/mov/call/ret` (0 ветвлений), поэтому проверка на
  # ней ВАКУУМНА и всегда «проходит». Символы реальных функций имеют
  # префикс модуля.
  CT_SYM="verifier.noninterference.constantTimeEqual"
  EE_SYM="verifier.noninterference.earlyExitEqual"
  grep -q "^${CT_SYM}:" "$ASM" || CT_SYM="kern_ct_equal"
  grep -q "^${EE_SYM}:" "$ASM" || EE_SYM="kern_early_exit_equal"
  echo "  [i] анализируемые символы: $CT_SYM ; $EE_SYM"
  out="$(python3 "$HERE/binlevel_verify.py" "$ASM" "$CT_SYM" "$EE_SYM")"
  echo "$out" | sed 's/^/  /'
  # Число УСЛОВНЫХ ПЕРЕХОДОВ: у constant-time обязано быть СТРОГО МЕНЬШЕ,
  # чем у версии с ранним выходом (иначе проверка не различает их — вакуумна).
  ct_jcc="$(echo "$out" | grep -F "$CT_SYM" | grep -oE 'переходов [0-9]+' | grep -oE '[0-9]+')"
  ee_jcc="$(echo "$out" | grep -F "$EE_SYM" | grep -oE 'переходов [0-9]+' | grep -oE '[0-9]+')"
  if [ -n "${ct_jcc:-}" ] && [ -n "${ee_jcc:-}" ] && [ "$ee_jcc" -gt "$ct_jcc" ]; then
    echo "  [OK] constant-time: условных переходов МЕНЬШЕ, чем у раннего выхода ($ct_jcc < $ee_jcc) — проверка РАЗЛИЧАЕТ"
  else
    echo "  [!] проверка НЕ различает constant-time и ранний выход (${ct_jcc:-?} vs ${ee_jcc:-?})"; fail=1
  fi
  # ПРИМЕЧАНИЕ: счётчик «ветвлений от ДАННЫХ» даёт ложные срабатывания на
  # проверках ДЛИНЫ (длина публична) — он информационный, не критерий.
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
