#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
#
# КРОСС-АРХИТЕКТУРНАЯ ПРОВЕРКА ЯДРА (Эшелон 1: выравнивание + endianness).
#
# Зачем: zero-copy парсер .kimg читает сырую память. На x86_64 невыровненный
# доступ «прощается», на ARM64 — аппаратный Bus Error. А на BIG-ENDIAN
# (powerpc64) все многобайтные поля читаются наоборот. Проверяем РЕАЛЬНО:
# кросс-компилируем и запускаем тесты под qemu-user-static.
#
# Требуется: curl, qemu-user-static (скачивается автоматически в /tmp).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ZIG="${ZIG:-zig}"
# Абсолютный путь к Zig нужен ДО того, как мы переопределим PATH для QEMU
# (дефект #74): иначе после `PATH=/usr/bin:/bin` шелл не найдёт `zig`.
if [ "${ZIG#/}" = "$ZIG" ]; then
  ZIG="$(command -v "$ZIG" || true)"
fi
if [ -z "$ZIG" ] || [ ! -x "$ZIG" ]; then
  echo "[!] zig не найден (ZIG='${ZIG:-}'). Задайте ZIG=/путь/к/zig" >&2
  exit 2
fi
QEMU_VER="v7.2.0-1"
BASE="https://github.com/multiarch/qemu-user-static/releases/download/$QEMU_VER"

# ДЕФЕКТ N2: кэш эмулятора лежал в `/tmp/qemu-<arch>-static` и вычищался вместе с
# `/tmp`. Постоянный кэш пользователя переживает уборку.
QEMU_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/kern/qemu"

fetch_qemu() { # $1 = arch (aarch64|ppc64|s390x)
  # ДЕФЕКТ N2: кэш эмулятора лежал в `/tmp/qemu-<arch>-static` (~10 МБ на arch), а
  # `/tmp` вычищается правилом гигиены — значит качался заново при каждом вызове.
  # Перенесён в ПОСТОЯННЫЙ кэш пользователя. Это ОБЩИЙ кэш, а не рабочий файл
  # прогона: он НЕ получает `$$` и НЕ удаляется в `trap` — иначе каждый процесс
  # качал бы свою копию и мы вернулись бы к той же проблеме.
  local q="$QEMU_CACHE/qemu-$1-static"
  mkdir -p "$QEMU_CACHE"
  if [ ! -x "$q" ]; then
    if [ -x "/tmp/qemu-$1-static" ]; then
      cp -f "/tmp/qemu-$1-static" "$q"   # совместимость: не качаем заново
    else
      curl -sL -o "$q" "$BASE/qemu-$1-static" && chmod +x "$q"
    fi
  fi
  echo "$q"
}

run_arch() { # $1 = zig target, $2 = qemu arch, $3 = описание
  local target="$1" qarch="$2" desc="$3"
  echo "=== $desc ($target) ==="
  local q; q="$(fetch_qemu "$qarch")"
  # Zig 0.17: `compat` — именованный модуль, поэтому `zig test` запускаем с
  # `--dep compat -Mcompat=...`, а сам бинарник исполняем через QEMU
  # (`--test-cmd … --test-cmd-bin`), иначе Zig отказывается запускать
  # чужую архитектуру.
  # KERN_FAST=1: под эмуляцией потоки/таймеры идут в 10-50 раз медленнее,
  # поэтому стрессовые итерации (литмус, замеры времени) уменьшаются.
  #
  # 🔴 ДЕФЕКТ #74: почему QEMU ЗАВИСАЛ намертво.
  # `z3` — нативный x86_64 бинарник. Когда он оказывается в PATH, тесты
  # Z3-моста внутри эмуляции пытаются его запустить: qemu-user перехватывает
  # fork+execve чужой архитектуры, а фоновый поток-убийца (std.Thread) ждёт
  # на futex. Эмуляция futex + waitpid при живых потоках в qemu-user — это
  # известная точка дедлока: эмулируемый `waitpid` и поток-убийца ждут друг
  # друга бесконечно, и прогон не завершается НИКОГДА.
  #
  # РЕШЕНИЕ: запускаем эмулируемый тест с ЧИСТЫМ PATH без `.venv/bin`, где
  # лежит z3. Тогда `solverAvailable()` мгновенно получает ToolError, и все
  # 4 теста решателя штатно уходят в `error.SkipZigTest` (~1 с вместо дедлока),
  # а остальные 200 тестов (выравнивание, big-endian, BLAKE3, KERNFS, Belnap,
  # KERN-X) проходят полностью. Проверять выравнивание и порядок байт
  # эмуляцией чужого бинарника смысла нет — это не предмет кросс-арх теста.
  # ДЕФЕКТ (найден при пересъёмке на базе 436 тестов): `| tail -3` отбрасывал
  # ДЕТАЛИ падения. В логе оставалось «427 passed; 8 skipped; 1 failed» — БЕЗ
  # имени упавшего теста, и найти его можно было только ручным воспроизведением.
  # Инструмент, который скрывает причину отказа, бесполезен ровно тогда, когда
  # нужен. Теперь при провале печатается ВЕСЬ вывод, при успехе — краткая сводка.
  local log; log="$(mktemp -t kern_cross_XXXXXX.log)"
  ( cd "$ROOT" && KERN_FAST=1 PATH="/usr/bin:/bin" "$ZIG" test \
      -target "$target" \
      --dep compat \
      -Mroot=src/test_root.zig \
      -Mcompat=src/compat.zig \
      --test-cmd "$q" --test-cmd-bin >"$log" 2>&1
    rc=$?
    if [ "$rc" -ne 0 ]; then
      cat "$log"
      echo "  [!] прогон $target: rc=$rc — печатаю ВЕСЬ вывод, чтобы имя упавшего теста не терялось"
    else
      tail -3 "$log"
    fi
    rm -f "$log"
    exit "$rc"
  ) | sed 's/^/  /'
}

run_arch aarch64-linux-musl aarch64 "ARM64 (little-endian, строгое выравнивание)"
run_arch powerpc64-linux-musl ppc64 "POWERPC64 (BIG-ENDIAN, порядок байт)"
