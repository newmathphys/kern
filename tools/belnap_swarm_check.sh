#!/usr/bin/env bash
# ЭШЕЛОН 6, ПУНКТ 35: ПРИЁМКА АРБИТРАЖА РОЯ В РЕШЁТКЕ БЕЛНАПА.
# Свойство проверяется НАТИВНО тестом в src/next/truth.zig (Bit.join):
#   JOIN_K(T,F) = B  -> Врата ЗАКРЫТЫ;
#   поглощение: 100 голосов T НЕ перезаписывают B;
#   JOIN_K(T,T) = T  -> Врата ОТКРЫТЫ.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
ZIG=${ZIG:-zig}
grep -q 'ПУНКТ 35' src/next/truth.zig || { echo "[!] тест Пункта 35 отсутствует"; exit 1; }
OUT=$(timeout 600 "$ZIG" build test-next --summary all 2>&1); RC=$?
echo "$OUT" | grep -E 'Build Summary' | tail -1
[ "$RC" -eq 0 ] || { echo "[!] test-next КРАСНЫЙ — решётка Белнапа нарушена"; echo "$OUT" | tail -5; exit 1; }
echo "[OK] рой: JOIN_K(T,F)=B, поглощение противоречия, JOIN_K(T,T)=T"
