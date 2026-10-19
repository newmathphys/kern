#!/usr/bin/env bash
# ЭШЕЛОН 5, ПУНКТ 25: ПРИЁМКА ПОЛИГЛОТ-ЭКСТРАКТОРА (7 языков).
# .py .zig .c .rs (уже были) + .ts .js .go (новые) + Sorbet-вывод из типов.
# Требуется:
#   * PROVEN — clampTs/clampJs/clampGo (гард) и pctTs (диапазон из типа `Percent`);
#   * REFUTED — badTs/badGo (переполнение int32), badJs (нарушение контракта)
#     с КОНТРПРИМЕРОМ и [RUNTIME CONFIRMED];
#   * ЧЕСТНЫЙ ОТКАЗ — `number` (float64) уходит в SKIP с ЯВНОЙ причиной, а не
#     получает диапазон `int`.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 600 "$PY" tools/kern_contracts.py \
        examples/polyglot_demo.ts examples/polyglot_demo.js examples/polyglot_demo.go 2>&1)
RC=$?
[ "$RC" -le 1 ] || { echo "[!] экстрактор упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -3

fail() { echo "[!] $1"; exit 1; }

for fn in clampTs clampJs clampGo; do
  echo "$OUT" | grep -q "\[PASS\] $fn: ДОКАЗАНО" || fail "$fn ($fn) НЕ доказан"
done
echo "$OUT" | grep -q '\[PASS\] pctTs: ДОКАЗАНО' \
  || fail "Sorbet-вывод диапазона (Percent -> 0..100) не работает"
echo "$OUT" | grep -q '\[FAIL\] badTs: ПЕРЕПОЛНЕНИЕ типа `int32`' \
  || fail "TS: переполнение int32 НЕ поймано"
echo "$OUT" | grep -q '\[FAIL\] badGo: ПЕРЕПОЛНЕНИЕ типа `int32`' \
  || fail "Go: переполнение int32 НЕ поймано"
echo "$OUT" | grep -q '\[FAIL\] badJs: КОНТРАКТ НАРУШЕН' \
  || fail "JS: нарушение контракта НЕ поймано"
echo "$OUT" | grep -q '\[RUNTIME CONFIRMED\]' \
  || fail "контрпример НЕ подтверждён рантаймом"
echo "$OUT" | grep -q 'numTs (стр. 33): SKIP — float64' \
  || fail "`number` (float64) НЕ получил честного отказа"
if echo "$OUT" | grep -q '\[UNKNOWN\]\|НЕ РЕШЕНО [1-9]'; then
  fail "есть НЕрешённые обязательства — приёмка неполна"
fi
echo "[OK] полиглот: 7 языков; PROVEN 4 | REFUTED 3 | honest SKIP 1 (float64) | 0 unknown"
