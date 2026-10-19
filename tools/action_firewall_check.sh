#!/usr/bin/env bash
# ЭШЕЛОН 7, ПУНКТ 36: ПРИЁМКА ACTION/FINOPS FIREWALL.
# Требуется ТРИ кода: 200 (T), 422 (F), 409 (B: allow и forbid истинны).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
fail() { echo "[!] $1"; exit 1; }
A=$(timeout 200 "$PY" tools/kern_contracts.py --verify-action examples/action_ok.json examples/policy_transfer.json 2>&1)
echo "$A" | grep -q '\[PASS\] Firewall: PROVEN' || fail "безопасный вызов НЕ разрешён (нет 200)"
B=$(timeout 200 "$PY" tools/kern_contracts.py --verify-action examples/action_over.json examples/policy_transfer.json 2>&1)
echo "$B" | grep -q '\[FAIL\] Firewall: ALLOW VIOLATED' || fail "превышение бюджета НЕ поймано (нет 422)"
C=$(timeout 200 "$PY" tools/kern_contracts.py --verify-action examples/action_conflict.json examples/policy_conflict.json 2>&1)
echo "$C" | grep -q '\[FAIL\] Firewall: POLICY CONFLICT' || fail "конфликт политик НЕ пойман (нет 409)"
echo "[OK] firewall: 200 (T) / 422 (F) / 409 (B) — все три вердикта"
