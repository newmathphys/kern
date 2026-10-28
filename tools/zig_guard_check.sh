#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# =============================================================================
#  ДЕФЕКТ #392: отказ из-за НЕВЕРНОГО компилятора обязан быть НАЗВАННЫМ.
#
#  Симптом (измерен): при pip-пакете `ziglang` 0.13.0 в PATH (он лежит в
#  `.venv/bin` НАМЕРЕННО — для цели `portable-bench`) `make build` падал
#  ошибкой ВНУТРИ нашего `build.zig`:
#      build.zig:12:54: error: no field named 'root_module' in struct
#                       'Build.ExecutableOptions'
#  То есть сообщение обвиняло НАШ код, а причина — неверный компилятор.
#  59 целей зависят от `build` (включая витрину `showcase-live`), поэтому
#  цена ложного обвинения — не косметика.
#
#  Класс тот же, что #381 (молчаливый фильтр расширений): отказ без имени
#  отправляет читателя искать проблему не там, где она есть.
#
#  Проверяются ТРИ исхода — и все три обязаны быть НАЗВАННЫМИ:
#    1) верный Zig 0.17  -> сборка ПРОХОДИТ (иначе проверка вакуумна);
#    2) неверный Zig 0.13 -> `[ОТКАЗ]`, rc=2, названа требуемая версия,
#       и НИ ОДНОЙ ошибки, обвиняющей наш `build.zig`;
#    3) Zig отсутствует  -> тоже `[ОТКАЗ]`, а не «command not found».
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

REAL_ZIG="${REAL_ZIG:-$HOME/opt/zig-x86_64-linux-0.17.0/zig}"
bad=0
fail() { echo "[FAIL] $*"; bad=$((bad+1)); }

# --- 1. Верный компилятор обязан собрать (анти-вакуум: иначе «отказ» тривиален)
if [ ! -x "$REAL_ZIG" ]; then
  fail "нет верного Zig по пути $REAL_ZIG — проверка невакуумности невозможна"
else
  timeout 900 make build ZIG="$REAL_ZIG" >/tmp/zg_ok.log 2>&1
  rc=$?
  [ "$rc" -eq 0 ] || fail "верный Zig ($REAL_ZIG) НЕ собрался (rc=$rc) — проверка вакуумна"
fi

# --- 2. Неверный компилятор (pip-ziglang 0.13) обязан быть отвергнут ПО ИМЕНИ
if [ -x .venv/bin/zig ]; then
  timeout 300 make build ZIG=.venv/bin/zig >/tmp/zg_bad.log 2>&1
  rc=$?
  [ "$rc" -eq 2 ] || fail "неверный Zig: ожидался rc=2 (названный отказ), получен $rc"
  grep -qF '[ОТКАЗ]' /tmp/zg_bad.log || fail "отказ НЕ назван: нет строки '[ОТКАЗ]'"
  grep -qF 'требуется Zig' /tmp/zg_bad.log || fail "отказ не называет требуемую версию"
  # ГЛАВНОЕ: отказ не имеет права обвинять наш код
  if grep -q 'error: no field named' /tmp/zg_bad.log; then
    fail "отказ обвиняет наш build.zig ('no field named'), а не неверный компилятор"
  fi
else
  fail "нет .venv/bin/zig — случай «неверный компилятор» не проверен (вакуум)"
fi

# --- 3. Отсутствующий компилятор: тоже названный отказ, а не «command not found»
timeout 120 env PATH=/usr/bin:/bin make build ZIG=definitely-not-zig >/tmp/zg_none.log 2>&1
rc=$?
[ "$rc" -eq 2 ] || fail "отсутствующий Zig: ожидался rc=2, получен $rc"
grep -qF '[ОТКАЗ]' /tmp/zg_none.log || fail "отсутствующий Zig: отказ не назван"

if [ "$bad" -ne 0 ]; then
  echo "[FAIL] zig-guard: нарушений $bad"
  exit 1
fi
echo "[OK] zig-guard: верный Zig собирает; неверный и отсутствующий отвергнуты НАЗВАННО (rc=2), без обвинения build.zig"
exit 0
