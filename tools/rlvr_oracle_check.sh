#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ЭШЕЛОН 7, ПУНКТ 38: ПРИЁМКА ОРАКУЛА ВОЗНАГРАЖДЕНИЯ.
# Требуется: +1.0 (verified) / -1.0 (refuted) / -2.0 (reward hacking) / 0.0 (граница).
#
# ЧЕСТНАЯ ГРАНИЦА (измерена, окно №6): `--rlvr-reward` доказывает только ЛИНЕЙНЫЙ
# фрагмент. Тело `x * 2` корректно, но даёт 0.0 ABSTAIN — гейт ОБЯЗАН требовать
# именно 0.0: иначе «+1.0» можно было бы выдать за доказательство нелинейного
# кода, которого решатель не проверял.
# Линейный кандидат создаётся в mktemp (не в дереве): в репозитории не появляется
# новых запечатанных контрактов, и замок остаётся ровно на 28 файлах.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
fail() { echo "[!] $1"; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/kern_rlvr_XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/linear.py" <<'PYEOF'
# @kern:requires x >= 0
# @kern:ensures result >= 0
def inc(x):
    return x + 1
PYEOF

G=$(timeout 300 "$PY" tools/kern_contracts.py --rlvr-reward "$TMP/linear.py" 2>&1)
echo "$G" | grep -q 'R=+1.0' || fail "линейный доказанный кандидат НЕ награждён (+1.0)"
B=$(timeout 300 "$PY" tools/kern_contracts.py --rlvr-reward examples/rlvr_candidates/buggy.py 2>&1)
echo "$B" | grep -q 'R=-1.0' || fail "опровергнутый кандидат НЕ наказан (-1.0)"
C=$(timeout 300 "$PY" tools/kern_contracts.py --rlvr-reward examples/rlvr_candidates/cheater.py 2>&1)
echo "$C" | grep -q 'R=-2.0' || fail "чит НЕ наказан (-2.0)"
N=$(timeout 300 "$PY" tools/kern_contracts.py --rlvr-reward examples/rlvr_candidates/good.py 2>&1)
echo "$N" | grep -q 'R=0.0' || fail "нелинейное тело НЕ воздержалось (0.0) — граница фрагмента потеряна"
echo "[OK] RLVR: +1.0 за доказанное, -1.0 за контрпример, -2.0 за чит, 0.0 за нелинейный фрагмент"
