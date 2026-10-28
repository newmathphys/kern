#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# =============================================================================
#  ВОСПРОИЗВОДЯЩИЕ КОМАНДЫ ДЛЯ ДВУХ ЧУЖИХ ДЕФЕКТОВ (пункт 2 передачи дел).
#
#  Проблема, которую закрывает гейт: у двух из десяти доказательств в
#  `docs/TEN_PROOFS.md` была только ССЫЛКА НА СНИМОК (`docs/evidence/…log`),
#  но не команда, которая этот вердикт ПОВТОРЯЕТ. Читатель не мог проверить
#  утверждение сам — он мог только поверить снимку. Это класс «доказательство
#  без воспроизведения».
#
#  Теперь теневые контракты лежат в репозитории, и вердикт воспроизводится:
#    • `lcm_numerator.c`      — арифметическое ядро `a * b` из `TheAlgorithms/C`
#                               `math/lcm.c` (PR #1596). Ожидание: НАРУШЕН.
#    • `binom_step.rs`        — выражение `n - i` из `TheAlgorithms/Rust`
#                               `binomial_coefficient.rs` (PR #1075). Ожидание:
#                               ПЕРЕПОЛНЕНИЕ типа u64.
#
#  ПОЧЕМУ ПРОВЕРКА ДВУСТОРОННЯЯ. «REFUTED» само по себе ничего не доказывает:
#  его может дать и сломанный инструмент. Поэтому рядом стоят ГАРДИРОВАННЫЕ
#  близнецы с тем же телом: они обязаны быть ДОКАЗАНЫ. Если доказан и
#  незащищённый вариант — ворота краснеют, значит вердикт был не о переполнении.
#
#  Точные значения контрпримеров НЕ проверяются (модель решателя между
#  версиями Z3 меняется) — проверяется КЛАСС: нарушение + предъявленный
#  контрпример + ноль ложных тревог.
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

PY="./.venv/bin/python"
[ -x "$PY" ] || PY="python3"
bad=0
fail() { echo "[FAIL] $*"; bad=$((bad + 1)); }

run_contracts() { timeout 300 "$PY" tools/kern_contracts.py "$1" 2>&1; }

# --- A. Незащищённые ядра обязаны быть ОПРОВЕРГНУТЫ с контрпримером ---------
LCM=docs/evidence/example_why_kern/lcm_numerator.c
BIN=docs/evidence/thealgorithms_rust/binom_step.rs

out=$(run_contracts "$LCM")
echo "$out" | grep -qF '[FAIL] lcm_numerator' \
  || fail "lcm_numerator: не опровергнут (переполнение a*b должно ловиться)"
echo "$out" | grep -qF '[КОНТРПРИМЕР]' \
  || fail "lcm_numerator: нет контрпримера — опровержение без улики"
echo "$out" | grep -qF 'ЛОЖНЫХ ТРЕВОГ 0' \
  || fail "lcm_numerator: ложные тревоги на корректных контрактах"
echo "$out" | grep -qF '[BV]' \
  || fail "lcm_numerator: не названа теория (нелинейное умножение обязано идти в QF_BV)"

out=$(run_contracts "$BIN")
echo "$out" | grep -qF '[FAIL] binom_step' \
  || fail "binom_step: не опровергнут (вычитание n-i в u64 при i > n)"
echo "$out" | grep -qF 'ПЕРЕПОЛНЕНИЕ типа `u64`' \
  || fail "binom_step: назван не тот класс нарушения (ожидалось переполнение u64)"
echo "$out" | grep -qF '[КОНТРПРИМЕР]' \
  || fail "binom_step: нет контрпримера — опровержение без улики"
echo "$out" | grep -qF 'ЛОЖНЫХ ТРЕВОГ 0' \
  || fail "binom_step: ложные тревоги на корректных контрактах"

# --- B. Гардированные близнецы обязаны быть ДОКАЗАНЫ (анти-вакуум) ----------
for f in docs/evidence/example_why_kern/lcm_numerator_guarded.c \
         docs/evidence/thealgorithms_rust/binom_step_guarded.rs; do
  out=$(run_contracts "$f")
  echo "$out" | grep -qF 'ДОКАЗАНО' \
    || fail "$f: гардированный близнец НЕ доказан — тогда опровержение выше вакуумно"
  echo "$out" | grep -qF 'ЛОЖНЫХ ТРЕВОГ 0' \
    || fail "$f: ложные тревоги на доказанном близнеце"
done

if [ "$bad" -ne 0 ]; then
  echo "[FAIL] foreign-verdicts: нарушений $bad"
  exit 1
fi
echo "[OK] foreign-verdicts: два чужих дефекта воспроизводятся ИЗ РЕПОЗИТОРИЯ (lcm a*b — нарушен; binom n-i в u64 — переполнение), гардированные близнецы доказаны, ложных тревог 0"
exit 0
