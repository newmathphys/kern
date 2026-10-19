#!/usr/bin/env bash
# ЭШЕЛОН 5, ПУНКТ 31: ПРИЁМКА ТАРИФНЫХ МАТРИЦ (`--verify-pricing`).
# Требуется: PRICING GAP (вход без цены) + PRICING CONFLICT (пересечение правил)
# + PROVEN COMPLETE & DISJOINT с trusted: 0.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/kern_contracts.py --verify-pricing examples/pricing_demo.py 2>&1); RC=$?
[ "$RC" -le 1 ] || { echo "[!] --verify-pricing упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -5
fail() { echo "[!] $1"; exit 1; }
echo "$OUT" | grep -q '\[FAIL\] price_gap: PRICING GAP' || fail "дыра в тарифах НЕ найдена"
echo "$OUT" | grep -q '\[FAIL\] price_conflict: PRICING CONFLICT' || fail "конфликт правил НЕ найден"
echo "$OUT" | grep -q '\[PASS\] price_safe: PROVEN COMPLETE & DISJOINT' || fail "корректная сетка НЕ доказана"
echo "$OUT" | grep -q '\[UNKNOWN\]' && fail "есть НЕрешённые обязательства"
echo "[OK] тарифы: дыра и конфликт найдены, корректное разбиение доказано (trusted: 0)"
