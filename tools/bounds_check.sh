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

# ZERO-ANNOTATION (архитектурная ревизия): в этом файле НЕТ ни одной аннотации
# `@kern:` — длина берётся из САМОГО КОДА (литерал списка / `len(arr)`).
if grep -qE '@kern:[a-z]' examples/bounds_zero_annot.py; then
  echo "[!] в bounds_zero_annot.py появились аннотации @kern: — режим перестал быть zero-annotation"; exit 1
fi
Z=$(timeout 300 python3 tools/kern_contracts.py --xray examples/bounds_zero_annot.py 2>&1)   || { echo "[!] --xray на bounds_zero_annot.py упал"; exit 1; }
echo "$Z" | grep -q 'BOUNDS PATH\] get_literal.*из литерала'   || { echo "[!] длина литерала списка НЕ извлечена из AST"; exit 1; }
echo "$Z" | grep -q 'BOUNDS PATH\] get_symbolic_bad'   || { echo "[!] символическая длина (len(arr)) не поймала пропуск i<0"; exit 1; }
if echo "$Z" | grep -q 'BOUNDS PATH\] get_symbolic_safe'; then
  echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ get_symbolic_safe (гарды с len(arr) не учтены)"; exit 1
fi
echo "$Z" | grep -q 'checked 3 / 3 functions, skipped 0'   || { echo "[!] есть отсеянные функции — zero-annotation неполон"; exit 1; }
echo "[OK] zero-annotation: длина из литерала AST + символическая len(arr), 0 пропусков"
