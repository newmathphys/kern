#!/usr/bin/env bash
# ЭШЕЛОН 5, ПУНКТ 30: ПРИЁМКА RLS-ПОЛИТИК (`--verify-sql`).
# Требуется СТРОГО: BYPASS пойман на небезопасной политике И `[PASS] PROVEN` с
# trusted: 0 на безопасной (Дефект #145: покомпонентная проверка инварианта
# сняла 4 atom-heavy доверенных шага). Поблажки `or UNKNOWN` БОЛЬШЕ НЕТ.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/kern_contracts.py --verify-sql examples/sql_policy_demo.py 2>&1); RC=$?
[ "$RC" -le 1 ] || { echo "[!] --verify-sql упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -4
fail() { echo "[!] $1"; exit 1; }
echo "$OUT" | grep -q '\[FAIL\] rls_buggy: RLS POLICY BYPASS FOUND' || fail "обход изоляции тенантов НЕ пойман"
echo "$OUT" | grep -q '\[PASS\] rls_safe: PROVEN (tenant isolation on all' \
  || fail "безопасная политика НЕ доказана (нужен PROVEN с trusted: 0, без UNKNOWN)"
if echo "$OUT" | grep -q '\[UNKNOWN\]'; then
  fail "есть НЕрешённые обязательства — приёмка неполна"
fi
echo "[OK] RLS: обход пойман с контрпримером; безопасная политика ДОКАЗАНА (trusted: 0), 0 unknown"
