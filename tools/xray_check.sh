#!/usr/bin/env bash
# ЭШЕЛОН 3, ПУНКТ 13: ПРИЁМКА --xray. Требуем НАСТОЯЩИЕ находки на фикстуре
# examples/xray_demo.py: мёртвая ветка, избыточный гард и краш-путь.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT=$(timeout 300 python3 tools/kern_contracts.py --xray examples/xray_demo.py 2>&1) || { echo "[!] --xray упал"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -12
fail=0
for pat in 'DEAD BRANCH' 'REDUNDANT GUARD' 'CRASH PATH' '[XRAY SUMMARY]'; do
  if echo "$OUT" | grep -q "$pat"; then echo "  [OK] найдено: $pat"; else echo "  [ПРОВАЛ] нет: $pat"; fail=1; fi
done
if [ "$fail" != 0 ]; then echo "[!] --xray не нашёл ожидаемых находок"; exit 1; fi
echo "[OK] --xray: все три класса находок подтверждены"

# ЭШЕЛОН 4, ПУНКТ 21: ГРАНИЦЫ МАССИВОВ (`arr[i]` -> `0 <= i < len`).
# Ключевое — ОТСУТСТВИЕ ЛОЖНОГО СРАБАТЫВАНИЯ: функция с гардами (`get_safe`)
# НЕ должна обвиняться, а функция без гардов (`get_unsafe`) — должна.
BOUNDS=$(timeout 300 python3 tools/kern_contracts.py --xray examples/array_bounds.py 2>&1) || { echo "[!] xray на array_bounds упал"; exit 1; }
echo "$BOUNDS" | grep -q 'BOUNDS PATH\] get_unsafe' || { echo "[!] get_unsafe НЕ обвинён — детектор границ слеп"; exit 1; }
if echo "$BOUNDS" | grep -q 'BOUNDS PATH\] get_safe'; then echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ get_safe (гарды не учтены)"; exit 1; fi
echo "$BOUNDS" | grep -q 'BOUNDS\] get_unknown_len' || { echo "[!] нет честного 'длина неизвестна'"; exit 1; }
echo "[OK] границы: get_unsafe обвинён, get_safe НЕ обвинён, неизвестная длина честно помечена"
