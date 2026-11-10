#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later.
# РЕГРЕССИИ «PROVEN»: двусторонний контроль для случаев, которые ЛОМАЛИСЬ.
#   #593/#596 — длина: len(x) >= 0 и ОДИН символ длины
#   #604       — len(x) в теле против len(x) в контракте
# Требуется ВСЕ ЧЕТЫРЕ исхода; иначе приёмка вакуумна и дефект вернётся.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
P="python3 tools/kern_contracts.py"
F=tests/fixtures/proven
fail=0
chk() { # $1=вывод $2=ожидаемая строка $3=человеческое имя
  if ! printf '%s' "$1" | grep -q "$2"; then
    echo "[FAIL] $3: ожидалось «$2»"; fail=1
  else
    echo "[OK]   $3"
  fi
}
chk "$(timeout 200 $P --loops $F/loops_len_ok.py 2>&1)" \
    '\[PASS\] scan: PROVEN' 'цикл с len(x) доказан'
chk "$(timeout 200 $P --loops $F/loops_len_bad.py 2>&1)" \
    '\[FAIL\] bump: LOOP INVARIANT VIOLATED' 'нарушение инварианта поймано'
chk "$(timeout 200 $P --state-inv $F/state_len_ok.py 2>&1)" \
    '\[PASS\] clamp_index: PROVEN' 'постусловие с len(x) доказано'
chk "$(timeout 200 $P --state-inv $F/state_len_bad.py 2>&1)" \
    '\[FAIL\] grow: STATE INVARIANT VIOLATED' 'нарушение постусловия поймано'
for f in loops_len_ok state_len_ok; do
  case $f in
    loops_len_ok) out=$(timeout 200 $P --loops $F/$f.py 2>&1);;
    *)            out=$(timeout 200 $P --state-inv $F/$f.py 2>&1);;
  esac
  if printf '%s' "$out" | grep -q '\[UNKNOWN\]'; then
    echo "[FAIL] $f: есть UNKNOWN — доказательство неполно"; fail=1
  fi
done
[ $fail -eq 0 ] && echo "[OK] регрессии PROVEN: 4 двусторонних контроля, 0 unknown"
exit $fail
