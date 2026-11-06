#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ЭШЕЛОН 6, ПУНКТ 34: ПРИЁМКА НЕИНТЕРФЕРЕНЦИИ (`@kern:secret`, 2-Safety).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 400 "$PY" tools/kern_contracts.py --noninterference examples/noninterference_demo.py 2>&1); RC=$?
[ "$RC" -le 1 ] || { echo "[!] --noninterference упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -4
fail() { echo "[!] $1"; exit 1; }
echo "$OUT" | grep -q '\[FAIL\] check_pin_leaky: SECRET LEAK' || fail "утечка секрета НЕ поймана"
echo "$OUT" | grep -q '\[PASS\] constant_time_op: PROVEN NON-INTERFERENT (trusted: 0' || fail "константная функция НЕ доказана"
echo "$OUT" | grep -q '\[UNKNOWN\]' && fail "есть НЕрешённые обязательства"
echo "[OK] неинтерференция: утечка поймана, константная функция доказана (trusted: 0)"
