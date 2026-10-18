#!/usr/bin/env bash
# ЭШЕЛОН 4, ПУНКТ 24: ПРИЁМКА ИНВАРИАНТА СОСТОЯНИЯ.
# Требуется: refund_unsafe -> FAIL (двойной возврат), refund_safe -> PASS,
# и НИ ОДНОГО [UNKNOWN] (нерешённое не выдаётся за доказанное).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT=$(timeout 300 python3 tools/kern_contracts.py --state-inv examples/state_invariant_demo.py 2>&1) \
  || { echo "[!] --state-inv упал"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -4
echo "$OUT" | grep -q '\[FAIL\] refund_unsafe: STATE INVARIANT VIOLATED' \
  || { echo "[!] нарушение инварианта (двойной возврат) НЕ поймано"; exit 1; }
echo "$OUT" | grep -q '\[PASS\] refund_safe: PROVEN' \
  || { echo "[!] безопасный переход НЕ доказан"; exit 1; }
if echo "$OUT" | grep -q '\[UNKNOWN\]'; then
  echo "[!] есть НЕрешённые выходы — приёмка неполна"; exit 1
fi
echo "[OK] инвариант состояния: VIOLATED пойман, SAFE доказан, 0 unknown"
