#!/usr/bin/env bash
# ЭШЕЛОН 7, ПУНКТ 38: ПРИЁМКА ОРАКУЛА ВОЗНАГРАЖДЕНИЯ.
# Требуется: +1.0 (verified) / -1.0 (refuted) / -2.0 (reward hacking).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
fail() { echo "[!] $1"; exit 1; }
G=$(timeout 300 "$PY" tools/kern_contracts.py --rlvr-reward examples/rlvr_candidates/good.py 2>&1)
echo "$G" | grep -q 'R=+1.0' || fail "честный кандидат НЕ награждён (+1.0)"
B=$(timeout 300 "$PY" tools/kern_contracts.py --rlvr-reward examples/rlvr_candidates/buggy.py 2>&1)
echo "$B" | grep -q 'R=-1.0' || fail "опровергнутый кандидат НЕ наказан (-1.0)"
C=$(timeout 300 "$PY" tools/kern_contracts.py --rlvr-reward examples/rlvr_candidates/cheater.py 2>&1)
echo "$C" | grep -q 'R=-2.0' || fail "чит НЕ наказан (-2.0)"
echo "[OK] RLVR: +1.0 за доказанное, -1.0 за контрпример, -2.0 за чит"
