#!/usr/bin/env bash
# ЭШЕЛОН 5, ПУНКТ 29: ПРИЁМКА FFI-МОСТА (`@kern:calls_i32` / `calls_u32`).
# Требуется: REFUTED (усечение при передаче в C-ABI) + 2 PROVEN с trusted: 0.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/kern_contracts.py --presets examples/ffi_bridge_demo.py 2>&1); RC=$?
[ "$RC" -le 1 ] || { echo "[!] --presets упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -5
fail() { echo "[!] $1"; exit 1; }
echo "$OUT" | grep -q '\[FAIL\] to_c_u32_unsafe: calls_u32 REFUTED' || fail "усечение u32 НЕ поймано"
echo "$OUT" | grep -q '\[PASS\] to_c_u32_safe: calls_u32 PROVEN по всем' || fail "u32-клемма НЕ доказана"
echo "$OUT" | grep -q '\[PASS\] to_c_i32_safe: calls_i32 PROVEN по всем' || fail "i32-клемма НЕ доказана"
echo "$OUT" | grep -q '\[UNKNOWN\]' && fail "есть НЕрешённые обязательства"
echo "[OK] FFI-мост: усечение поймано, клеммы i32/u32 доказаны (trusted: 0)"
