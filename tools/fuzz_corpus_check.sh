#!/usr/bin/env bash
# ЭШЕЛОН 8, ПУНКТ 40Д: ПРИЁМКА КОРПУСА ФАЗЗИНГА + install.sh.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/fuzz_corpus_check.py 2>&1); RC=$?
[ "$RC" -eq 0 ] || { echo "[!] корпус КРАСНЫЙ (rc=$RC)"; echo "$OUT" | tail -6; exit 1; }
echo "$OUT" | tail -2
echo "$OUT" | grep -q '0 паник' || { echo "[!] нет подтверждения 0 паник"; exit 1; }
echo "$OUT" | grep -q 'файлов [1-9]' || { echo "[!] корпус пуст"; exit 1; }
INST=$(timeout 120 bash install.sh --check 2>&1) || { echo "[!] install.sh --check упал"; exit 1; }
echo "$INST" | grep -q 'бинарник запускается' || { echo "[!] бинарник не запускается"; exit 1; }
echo "[OK] корпус фаззинга: 0 паник/0 segfault, детерминизм; install.sh --check проходит"
