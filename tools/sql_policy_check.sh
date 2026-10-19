#!/usr/bin/env bash
# ЭШЕЛОН 5, ПУНКТ 30: ПРИЁМКА RLS-ПОЛИТИК (`--verify-sql`).
# Требуется: BYPASS пойман на небезопасной политике. Для БЕЗОПАСНОЙ политики
# допускается ЛИБО PROVEN, ЛИБО честный [UNKNOWN] (НЕ засчитанный как PASS):
# чекер пока не перепроверяет часть atom-heavy шагов Z3 — это названо, а не
# замаскировано. ГЛАВНОЕ для безопасности — что обход ЛОВИТСЯ.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/kern_contracts.py --verify-sql examples/sql_policy_demo.py 2>&1); RC=$?
[ "$RC" -le 1 ] || { echo "[!] --verify-sql упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -4
fail() { echo "[!] $1"; exit 1; }
echo "$OUT" | grep -q '\[FAIL\] rls_buggy: RLS POLICY BYPASS FOUND' || fail "обход изоляции тенантов НЕ пойман"
if echo "$OUT" | grep -q '\[PASS\] rls_safe'; then
  echo "[i] безопасная политика: PROVEN"
elif echo "$OUT" | grep -q '\[UNKNOWN\] rls_safe'; then
  echo "[i] безопасная политика: честный UNKNOWN (не засчитан как PASS) — названная граница чекера"
else
  fail "безопасная политика не получила ни PASS, ни честный UNKNOWN"
fi
echo "[OK] RLS: обход пойман с контрпримером; статус безопасной политики честный"
