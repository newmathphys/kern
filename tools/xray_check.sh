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
