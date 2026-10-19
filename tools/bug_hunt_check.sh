#!/usr/bin/env bash
# ЭШЕЛОН 7, ПУНКТ 39: ПРИЁМКА ОХОТЫ ЗА БАГАМИ.
# Требуется: КОНТРОЛЬ (детектор видит известные находки) + честная воронка охвата.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/bug_hunter.py --max-files 8 2>&1); RC=$?
[ "$RC" -eq 0 ] || { echo "[!] bug_hunter упал (rc=$RC)"; echo "$OUT" | tail -6; exit 1; }
echo "$OUT" | tail -4
echo "$OUT" | grep -q 'контроль.*находок [2-9]' || { echo "[!] КОНТРОЛЬ не пройден"; exit 1; }
echo "$OUT" | grep -q 'BUG HUNT.*checked [0-9]*' || { echo "[!] нет воронки охвата"; exit 1; }
echo "[OK] охота: контроль пройден, воронка охвата напечатана"
