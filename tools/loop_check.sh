#!/usr/bin/env bash
# ЭШЕЛОН 4, ПУНКТ 20: ПРИЁМКА ТОТАЛЬНОЙ КОРРЕКТНОСТИ ЦИКЛОВ (Флойд - Хоар).
#
# Требуется ВСЕ ТРИ исхода:
#   count_up             -> [PASS]  (инвариант сохранён, вариант убывает)
#   count_up_bad_inv     -> [FAIL]  LOOP INVARIANT VIOLATED
#   count_up_no_terminate-> [FAIL]  NON-TERMINATING LOOP
# Если хотя бы один исход отсутствует — приёмка ВАКУУМНА.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT=$(timeout 300 python3 tools/kern_contracts.py --loops examples/loops.py 2>&1) \
  || { echo "[!] --loops упал"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -6
echo "$OUT" | grep -q '\[PASS\] count_up: PROVEN' \
  || { echo "[!] корректный цикл НЕ доказан — анализатор слеп"; exit 1; }
echo "$OUT" | grep -q '\[FAIL\] count_up_bad_inv: LOOP INVARIANT VIOLATED' \
  || { echo "[!] нарушение инварианта НЕ поймано"; exit 1; }
echo "$OUT" | grep -q '\[FAIL\] count_up_no_terminate: NON-TERMINATING LOOP' \
  || { echo "[!] незавершающийся цикл НЕ пойман"; exit 1; }
if echo "$OUT" | grep -q '\[UNKNOWN\]'; then
  echo "[!] есть НЕрешённые обязательства — приёмка неполна"; exit 1
fi
echo "[OK] циклы: PROVEN / INVARIANT VIOLATED / NON-TERMINATING — все три исхода"
