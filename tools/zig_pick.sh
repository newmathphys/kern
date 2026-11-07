#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
#
# `zig_pick.sh` — выбрать компилятор Zig, НЕ принадлежащий `.venv` (#509).
#
# ЗАЧЕМ. `.venv/bin` добавляется в PATH ради `z3`, и лежащий там pip-пакет
# `ziglang` 0.13 перекрывает системный Zig 0.17. Тогда `zig-guard` законно
# отказывает, но КРАСНЕЮТ не дефекты проекта: измерено витриной — 15 строк из 16
# (`make showcase-live-all`, Zig 0.17 стоял ВТОРЫМ в PATH).
#
# ПРАВИЛО. Идём по PATH слева направо и берём ПЕРВЫЙ `zig` вне `.venv`.
# Если такого нет — печатаем пусто (Makefile возьмёт $(ZIG) и честный отказ #392).
set -uo pipefail
name="${1:-zig}"
IFS=':' read -r -a dirs <<< "${PATH:-}"
for d in "${dirs[@]}"; do
  case "$d" in
    */.venv/bin|*/.venv/bin/) continue ;;
  esac
  if [ -n "$d" ] && [ -x "$d/$name" ]; then
    printf '%s\n' "$d/$name"
    exit 0
  fi
done
exit 0
