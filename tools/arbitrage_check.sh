#!/usr/bin/env bash
# ЭШЕЛОН 5, ПУНКТ 27: ПРИЁМКА ФИНАНСОВОГО АНТИ-АРБИТРАЖА (`@kern:no_arbitrage`).
# Требуется:
#   * REFUTED — комиссия с порогом (`fee_threshold`) и потолок с floor
#     (`fee_floor_capped`): клиент ДРОБИТ платёж и платит меньше;
#   * PROVEN с trusted: 0 — линейная (пропорциональная) комиссия;
#   * НИ ОДНОГО [UNKNOWN].
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/kern_contracts.py --presets examples/arbitrage_demo.py 2>&1)
RC=$?
[ "$RC" -le 1 ] || { echo "[!] --presets упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -6

fail() { echo "[!] $1"; exit 1; }

echo "$OUT" | grep -q '\[FAIL\] fee_threshold: no_arbitrage REFUTED' \
  || fail "арбитраж по порогу НЕ пойман"
echo "$OUT" | grep -q '\[FAIL\] fee_floor_capped: no_arbitrage REFUTED' \
  || fail "арбитраж по потолку/округлению НЕ пойман"
echo "$OUT" | grep -q '\[PASS\] fee_proportional: no_arbitrage PROVEN (trusted: 0' \
  || fail "линейная (субаддитивная) комиссия НЕ доказана на trusted: 0"
if echo "$OUT" | grep -q '\[UNKNOWN\]'; then
  fail "есть НЕрешённые обязательства — приёмка неполна"
fi
echo "[OK] анти-арбитраж: 2 арбитража поймано, линейная комиссия доказана (trusted: 0)"
