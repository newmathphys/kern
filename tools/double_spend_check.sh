#!/usr/bin/env bash
# ЭШЕЛОН 5, ПУНКТ 28: ПРИЁМКА ДЕТЕКТОРА ДВОЙНОГО СПИСАНИЯ.
# Требуется: REFUTED (гонка по устаревшему снимку) + PROVEN с trusted: 0 (серия).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/kern_contracts.py --presets examples/double_spend_demo.py 2>&1); RC=$?
[ "$RC" -le 1 ] || { echo "[!] --presets упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -4
fail() { echo "[!] $1"; exit 1; }
echo "$OUT" | grep -q '\[FAIL\] withdraw_race: no_double_spend REFUTED' \
  || fail "гонка двойного списания НЕ поймана"
echo "$OUT" | grep -q '\[PASS\] withdraw_serial_safe: no_double_spend PROVEN по всем' \
  || fail "последовательная модель НЕ доказана на trusted: 0"
echo "$OUT" | grep -q '\[UNKNOWN\]' && fail "есть НЕрешённые обязательства"
echo "[OK] двойное списание: гонка поймана, серийная модель доказана (trusted: 0)"
