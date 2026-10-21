#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
#
# KERN CI: ЕДИНЫЙ КОНТУР ПРОВЕРКИ. Один скрипт — весь обязательный набор.
#
# ЗАЧЕМ: за одну сессию найдено 21 дефект, из них 11 «молчаливо сломанных
# проверок» (#18, #23, #25, #26, #30, #32, #33, #34, #35, #36, #37). Всё это
# обнаружилось ТОЛЬКО потому, что контур гоняли вручную. Без автоматизации
# те же поломки вернутся при первом же рефакторинге.
#
# Запуск:  ./tools/ci.sh            (весь контур)
#          ./tools/ci.sh --fast     (без Lean и canfail — быстрая проверка)
#          ./tools/ci.sh --list     (показать стадии)
#
# Код возврата: 0 — всё зелёное; 1 — есть провал (см. сводку).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

# Тулейн: Zig 0.17 + venv (z3, python-обёртки).
#
# 🔴 ДЕФЕКТ #75 (найден по логу CI, раны #48-#51): путь к Zig был ЗАШИТ под
# локальную раскладку ($HOME/opt/zig-x86_64-linux-0.17.0). На GitHub Actions
# `mlugg/setup-zig` кладёт бинарник в PATH, а не в ~/opt, поэтому каждый прогон
# падал на шаге 7 с «[!] нет Zig по пути /home/runner/opt/... — задайте ZIG_DIR=».
#
# Теперь порядок поиска: ZIG_DIR -> zig из PATH -> локальная раскладка.
if [ -n "${ZIG_DIR:-}" ]; then
  export PATH="$ZIG_DIR:$ROOT/.venv/bin:$HOME/.elan/bin:$PATH"
elif command -v zig >/dev/null 2>&1; then
  # GitHub Actions и любой CI: zig уже в PATH.
  # ⚠️ ZIG_DIR ОБЯЗАН идти ПЕРВЫМ и здесь: `make venv` кладёт в .venv/bin
  # собственную копию Zig 0.13, и без явного приоритета она перехватывает
  # 0.17 -> сборка падает на `no field named 'root_module'` (проверено
  # локальным прогоном ci.sh: 6 провалов из 6).
  ZIG_DIR="$(dirname "$(command -v zig)")"
  export PATH="$ZIG_DIR:$ROOT/.venv/bin:$HOME/.elan/bin:$PATH"
elif [ -x "$HOME/opt/zig-x86_64-linux-0.17.0/zig" ]; then
  ZIG_DIR="$HOME/opt/zig-x86_64-linux-0.17.0"
  export PATH="$ZIG_DIR:$ROOT/.venv/bin:$HOME/.elan/bin:$PATH"
else
  echo "[!] zig не найден: ни ZIG_DIR, ни в PATH, ни в ~/opt." >&2
  echo "    Установите Zig 0.17.0 или задайте ZIG_DIR=/путь/к/zig" >&2
  exit 2
fi

# Контроль версии: 0.13 и 0.17 несовместимы (в 0.17 `addExecutable` требует
# `root_module`, в 0.13 — `root_source_file`). Лучше упасть здесь с понятным
# сообщением, чем получить 6 невнятных провалов ниже.
ZIG_VER="$("$ZIG_DIR/zig" version 2>/dev/null || echo '?')"
case "$ZIG_VER" in
  0.17*) : ;;
  *) echo "[!] найден Zig $ZIG_VER, а проекту нужен 0.17.x (ZIG_DIR=$ZIG_DIR)" >&2
     echo "    Задайте ZIG_DIR=/путь/к/zig-0.17" >&2
     exit 2 ;;
esac

export KERN_FAST="${KERN_FAST:-1}"
FAILED=()
PASSED=()
START=$(date +%s)

stage() { # $1 = имя, $2... = команда
  local name="$1"; shift
  local t0; t0=$(date +%s)
  printf '\n\033[1m=== %s ===\033[0m\n' "$name"
  if "$@"; then
    local dt=$(( $(date +%s) - t0 ))
    printf '\033[32m[OK]\033[0m %s (%d с)\n' "$name" "$dt"
    PASSED+=("$name")
  else
    local dt=$(( $(date +%s) - t0 ))
    printf '\033[31m[ПРОВАЛ]\033[0m %s (%d с)\n' "$name" "$dt"
    FAILED+=("$name")
  fi
}

FAST=0
for a in "$@"; do
  case "$a" in
    --fast) FAST=1 ;;
    --list) printf 'стадии: build test test-next test-align test-pool test-fault lean canfail mutate\n'; exit 0 ;;
  esac
done

if [ ! -x "$ZIG_DIR/zig" ]; then
  echo "[!] нет Zig по пути $ZIG_DIR/zig — задайте ZIG_DIR=" >&2
  exit 2
fi

# --- 1. Инструментальная проверка самого CI ---------------------------------
stage "инструменты (zig/python/z3)" bash -c 'zig version && python3 --version >/dev/null && (z3 --version || echo "[i] z3 нет в PATH")'

# --- 1b. РЕЕСТР ЦЕЛЕЙ + ПРЕДОХРАНИТЕЛЬ (K5) ----------------------------------
# Падает, если появилась неклассифицированная цель: новая проверка не может
# появиться «молча», не решив, как её проверять.
stage "реестр целей (K5)" python3 tools/registry.py

# --- 2. Сборка --------------------------------------------------------------
stage "build" zig build

# --- 2b. ВЕРСИИ: один проект — одна версия (дефект #97/#239) ----------------
# Гейт `make version-check` существовал, но НЕ был подключён к CI: `kernx`
# печатал v2.4.0 при теге v2.5.0, и зелёный CI этого не замечал.
stage "версии согласованы (kernc/kernx/C-ABI/README)" bash tools/version_check.sh

# --- 3. Тесты ядра ----------------------------------------------------------
stage "test (ядро, полный)" bash -c 'out=$(zig test --dep compat -Mroot=src/test_root.zig -Mcompat=src/compat.zig 2>&1); echo "$out" | tail -3; echo "$out" | grep -q "0 failed" || echo "$out" | grep -q "All .* tests passed"'

# --- 4. KERN-Next -----------------------------------------------------------
stage "test-next" zig build test-next

# --- 5. Эшелоны -------------------------------------------------------------
stage "эшелон 1 (выравнивание)" zig build test-align
stage "эшелон 3 (пул потоков)" zig build test-pool
stage "инъекция сбоев (SIGBUS)" zig build test-fault

# --- 6. Демонстратор атак (обязан вернуть 0 в норме) ------------------------
stage "attack (нет уязвимости)" bash -c './zig-out/bin/kern-attack >/dev/null 2>&1'

# --- 7. Формальные доказательства -------------------------------------------
if [ "$FAST" = "0" ]; then
  # ДЕФЕКТ #49: было `./formal/check.sh 2>&1 | tail -3` — RC брался от `tail`,
  # поэтому ПРОВАЛ check.sh (например, найденный `sorry`) НЕ ронял стадию.
  # Именно так `sorry` в formal/KernAllMath.lean дожил до коммита f418c87,
  # а CI оставался зелёным. Теперь RC берётся от самого check.sh.
  stage "Lean 4 (0 errors, 0 sorry)" bash -c 'out=$(./formal/check.sh 2>&1); rc=$?; echo "$out" | tail -3; exit $rc'
fi

# --- 8. CAN-FAIL: доказательство, что проверки СПОСОБНЫ упасть ---------------
if [ "$FAST" = "0" ]; then
  # ⚠️ ПРЕДОХРАНИТЕЛЬ ПЕРЕД харнессом: дерево обязано быть чистым.
  # Урок (дефекты #38/#46/#48/#52): если предыдущий прогон ПРЕРВАТЬ, файл
  # остаётся с диверсией, и дальше всё ломается — вплоть до ложных падений
  # тестов и порчи коммитов. Проверяем ДО, а не только ПОСЛЕ.
  stage "дерево чистое ПЕРЕД харнессом" bash -c '
    d=$(git status --porcelain | grep -v "kern.intoto.jsonl" || true)
    if [ -n "$d" ]; then
      echo "[!] дерево ГРЯЗНОЕ до запуска canfail — сначала закоммитьте:"; echo "$d" | head -10
      exit 1
    fi'
  stage "canfail --selftest (мета)" python3 tools/canfail.py --selftest
  stage "canfail (полный контур)" python3 tools/canfail.py

  # --- 8c. ДОКУМЕНТАЦИЯ НЕ ОТСТАЛА ОТ КОДА -------------------------------
  # `docs/TEST_CATALOG.md` заявлял 213 тестов, когда в коде было 218:
  # не учтены `src/compat.zig` и 4 теста `src/tests/os_stress_test.zig`.
  # Документ, расходящийся с кодом, создаёт ЛОЖНУЮ картину полноты.
  stage "каталог тестов синхронен с кодом" python3 tools/gen_test_catalog.py --check

  # --- Дефект #224: ЧИСЛА НА ВИТРИНЕ ПРОТИВ ИЗМЕРИМЫХ ФАКТОВ -----------------
  # ЗАЧЕМ: каталог проверялся (#216/#220), а остальные обещания — нет. Так в
  # README.md жило «114 proven non-vacuous / 95 cases» при факте 125/141, а в
  # PROJECT.md — «279» тестов при 401. Источник истины здесь — свидетельства
  # (`core_tests.log`, `kern_next_tests.log`, `cross_arch.log`), пересчёт
  # каталога и `registry.py --json`, а НЕ текст документа.
  stage "числа витрины == факты (#224)" python3 tools/check_metrics_consistency.py
  stage "мета-тест стража чисел (#239)" python3 tools/check_metrics_consistency.py --selftest
  stage "якоря чисел == факты (#240)" python3 tools/sync_state.py --check
  stage "sync selftest (#240)" python3 tools/sync_state.py --selftest
  stage "EN/RU паритет фактов (#241)" make docs-parity
  stage "нет ИИ-шаблонов (#241)" make ai-traces-check

  # --- Дефект #222/#223: ЛИЦЕНЗИЯ И СЧЁТЧИК ТЕОРЕМ --------------------------
  stage "лицензия согласована (#222)" python3 tools/check_license_consistency.py
  stage "счётчик теорем Lean 4 (#223)" python3 tools/check_lean_counter.py
  stage "экосистема MCP + диапазон реестра (#221)" bash tools/ecosystem_check.sh

  # --- 0K.2: аттестат проверяется ВНЕШНИМ ключом (ключ в репо, без $HOME) ---
  # До 0K.2 подпись проверялась ключом из $HOME, то есть только на
  # машине владельца; снаружи «attestation ✓» было непроверяемо.
  stage "аттестат внешним ключом (0K.2)" python3 tools/verify_attestation.py
  # 0K.4: секреты в отслеживаемых файлах (ключи провайдеров, PEM).
  stage "нет секретов в дереве (0K.4)" python3 tools/secrets_check.py
  # 0K.6/0K.7/0K.8: воспроизводимость вердикта и тулчейна.
  stage "детерминизм вердикта (0K.6)" python3 tools/determinism_check.py
  stage "CHANGELOG == версия (0K.8)" python3 tools/changelog_check.py
  stage "пин Lean/Mathlib (0K.7)" python3 tools/lean_pin_check.py

  # --- Дефект #232: ГЕЙТ ЕСТЬ, НО CI ЕГО НЕ ЗАПУСКАЛ ------------------------
  # `make scorecard-check` существовал и сверял опубликованный
  # `docs/evidence/scorecard.json` с пересчётом (137 теорем, 126 CHECK, 8/8
  # MCP). Но в этом контуре стадии не было — и устаревший паспорт (125 теорем,
  # 125 CHECK) спокойно жил на сайте. Гейт, которого нет в CI, равен его
  # отсутствию: сверка выполняется только там, где её нельзя забыть.
  stage "паспорт Trust Scorecard == факты (#232)" bash tools/scorecard_check.sh
  stage "SVG: геометрия подписей" python3 tools/svg_check.py
  stage "SVG: карта потока доказательства" python3 tools/svg_check.py docs/kern-proof-flow.svg
  # ДЕФЕКТ #244: витрина показывает граф импортов и метки модулей. Если
  # JSON отстанет от src/, страница начнёт врать про связи. Гейт сверяет
  # граф с пересборкой и проверяет, что страница ссылается на данные.
  stage "витрина: граф == src/ (#244)" make showcase-check

  # --- 9. АТТЕСТАЦИОННЫЙ МАНИФЕСТ (10 строк, каждая — реальный прогон) ------
  # ДЕФЕКТ #56: манифест искал шаблон «All N tests passed» (синтаксис 0.13),
  # а в 0.17 тест-раннер печатает «N passed; M skipped; K failed» — при живых
  # свидетельствах строка Target Systems показывала ЛОЖНЫЙ FAIL. Исправлено;
  # теперь манифест в CI и его падение = красный CI.
  stage "аттестационный манифест (10 строк)" bash -c '
    out=$(./tools/audit_manifest.sh 2>&1); rc=$?
    echo "$out" | grep -aE ": (PASS|FAIL|NOT RUN)"
    echo "$out" | tail -2
    exit $rc'

  # --- 8b. НЕТ СЛЕДОВ ХАРНЕССА (дефекты #38/#46/#48) ----------------------
  # Харнесс ломает файлы и обязан их откатывать. Если он оставит след,
  # `git add -A` закоммитит ДИВЕРСИЮ. Так уже было трижды:
  #   #38 — диверсия в z3_bridge.zig ушла в коммит 8c1e540;
  #   #46 — удаление TRACEABILITY_MATRIX.md ушло в 92bf484;
  #   #48 — `theorem CANFAIL_PROBE : True := by sorry` ушёл в f418c87
  #         (и CI был зелёным, потому что стадия Lean глушила RC — #49).
  stage "нет следов харнесса в дереве" bash -c '
    bad=0
    # ⚠️ `kern.intoto.jsonl` — ГЕНЕРИРУЕМЫЙ SLSA-аттестат (содержит хэши
    # бинарников), поэтому он законно меняется при любой пересборке.
    # Проверяем остальные файлы: харнесс не должен оставлять следов.
    dirt=$(git status --porcelain | grep -v "kern.intoto.jsonl" || true)
    if [ -n "$dirt" ]; then
      echo "[!] дерево ГРЯЗНОЕ после харнесса:"; echo "$dirt" | head -10; bad=1
    fi
    # Сканируем ТОЛЬКО отслеживаемые git файлы и исключаем тех, где маркеры
    # встречаются ЗАКОННО: сам харнесс, этот скрипт и документация (в ней
    # маркер цитируется при описании дефектов #38/#46/#48/#52).
    # ⚠️ Первая версия сканировала рабочий каталог целиком и ловила
    # ЛОЖНЫЕ срабатывания на untracked `tools/__pycache__/*.pyc`.
    scan=$(git ls-files | grep -vE "^(tools/canfail\.py|tools/ci\.sh)$" | grep -vE "\.md$")
    if echo "$scan" | xargs -r grep -ln "CANFAIL_PROBE" 2>/dev/null | grep -q .; then
      echo "[!] найден след харнесса CANFAIL_PROBE:"
      echo "$scan" | xargs -r grep -ln "CANFAIL_PROBE" 2>/dev/null
      bad=1
    fi
    # ДЕФЕКТ #52 (критичный): маркер диверсии «ЛОМАЕМ» остался в
    # tools/mutate_zig.py и был ЗАКОММИЧЕН (3915e76) — мутационное
    # тестирование стало всегда возвращать «выжил» (score 0%).
    if echo "$scan" | xargs -r grep -ln "ЛОМАЕМ" 2>/dev/null | grep -q .; then
      echo "[!] найден МАРКЕР ДИВЕРСИИ «ЛОМАЕМ» в отслеживаемых файлах:"
      echo "$scan" | xargs -r grep -ln "ЛОМАЕМ" 2>/dev/null
      bad=1
    fi
    exit $bad
  '
fi

# --- СВОДКА -----------------------------------------------------------------
TOTAL=$(( $(date +%s) - START ))
echo
echo "============================================================"
printf 'СВОДКА CI: зелёных %d, провалов %d, всего %d с\n' "${#PASSED[@]}" "${#FAILED[@]}" "$TOTAL"
if [ "${#FAILED[@]}" -gt 0 ]; then
  printf 'ПРОВАЛЕНО: %s\n' "${FAILED[*]}"
  echo "============================================================"
  exit 1
fi
echo "ВСЁ ЗЕЛЁНОЕ"
echo "============================================================"
exit 0
