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

# ПУНКТ 3: 4 БОЕВЫХ СЦЕНАРИЯ v2.5 (Bloch · PR-диф · DeFi · stdlib 0 FP).
# Каждый требует ПОЗИТИВНЫЙ и НЕГАТИВНЫЙ исход (8 проверок). Если детектор
# перестанет ловить баг ИЛИ начнёт обвинять корректный код — цель краснеет.
TOUT=$(timeout 900 "$PY" tools/bug_hunter.py --trophies 2>&1); TRC=$?
echo "$TOUT" | tail -14
[ "$TRC" -eq 0 ] || { echo "[!] трофеи: есть провалившиеся сценарии (rc=$TRC)"; exit 1; }
echo "$TOUT" | grep -q 'TROPHIES.*проверок 8/8' || { echo "[!] трофеи: не все 8 проверок прошли"; exit 1; }

echo "[OK] охота: контроль пройден, воронка охвата напечатана, трофеи 8/8"
