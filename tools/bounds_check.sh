#!/usr/bin/env bash
# ЭШЕЛОН 4, ПУНКТ 21: ПРИЁМКА ГРАНИЦ МАССИВОВ (`arr[i]` -> `0 <= i < len`).
#
# Ключевое — ОТСУТСТВИЕ ЛОЖНОГО СРАБАТЫВАНИЯ (Дефект #134): функция с гардами
# (`get_safe`) НЕ должна обвиняться, а функция без гардов (`get_unsafe`) — должна.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT=$(timeout 300 python3 tools/kern_contracts.py --xray examples/array_bounds.py 2>&1) \
  || { echo "[!] --xray на examples/array_bounds.py упал"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | grep -q 'BOUNDS PATH\] get_unsafe' \
  || { echo "[!] get_unsafe НЕ обвинён — детектор границ слеп"; exit 1; }
if echo "$OUT" | grep -q 'BOUNDS PATH\] get_safe'; then
  echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ get_safe (гарды не учтены) — Дефект #134 вернулся"; exit 1
fi
echo "$OUT" | grep -q 'BOUNDS\] get_unknown_len' \
  || { echo "[!] нет честного «длина неизвестна»"; exit 1; }
echo "[OK] границы: get_unsafe обвинён, get_safe НЕ обвинён, неизвестная длина помечена честно"
