#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
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
QEMU_VER="v7.2.0-1"
BASE="https://github.com/multiarch/qemu-user-static/releases/download/$QEMU_VER"

fetch_qemu() { # $1 = arch (aarch64|ppc64|s390x)
  local q="/tmp/qemu-$1-static"
  [ -x "$q" ] || curl -sL -o "$q" "$BASE/qemu-$1-static" && chmod +x "$q"
  echo "$q"
}

run_arch() { # $1 = zig target, $2 = qemu arch, $3 = описание
  local target="$1" qarch="$2" desc="$3"
  local bin="/tmp/kern_test_${qarch}"
  echo "=== $desc ($target) ==="
  ( cd "$ROOT" && "$ZIG" test src/test_root.zig -target "$target" -femit-bin="$bin" ) >/dev/null 2>&1
  if [ ! -x "$bin" ]; then echo "  [SKIP] сборка не удалась"; return; fi
  local q; q="$(fetch_qemu "$qarch")"
  # KERN_FAST=1: под эмуляцией потоки/таймеры идут в 10-50 раз медленнее,
  # поэтому стрессовые итерации (литмус, замеры времени) уменьшаются.
  local out; out="$(KERN_FAST=1 "$q" "$bin" 2>&1 | tail -3)"
  echo "$out" | sed 's/^/  /'
}

run_arch aarch64-linux-musl aarch64 "ARM64 (little-endian, строгое выравнивание)"
run_arch powerpc64-linux-musl ppc64 "POWERPC64 (BIG-ENDIAN, порядок байт)"
