#!/usr/bin/env bash
# ГОМЕОСТАТИЧЕСКАЯ ПЕТЛЯ: F -> патч -> перепроверка -> T.
# Приёмка проверяет ВСЮ ДУГУ, а не только печать рецепта:
#   1) ДО: краш есть;  2) --heal: файл вылечен;  3) ПОСЛЕ: крашей нет.
set -u
PY=${PYTHON:-python3}
EX=${KERNC_EXTRACTOR:-tools/kern_contracts.py}
TMP=$(mktemp /tmp/heal_XXXX.py)
cp examples/xray_demo.py "$TMP"
fail=0

before=$($PY "$EX" --xray "$TMP" 2>&1 | grep -c '\[CRASH PATH\]' || true)
[ "$before" -ge 1 ] && echo "  [OK] ДО: крашей $before (есть что лечить)" \
  || { echo "  [FAIL] ДО: крашей $before — нечего лечить"; fail=1; }

out=$($PY "$EX" --heal "$TMP" 2>&1); rc=$?
echo "$out" | grep -q 'T (1,0)' && echo '  [OK] --heal: файл вылечен (T (1,0))' \
  || { echo '  [FAIL] --heal не подтвердил лечение'; echo "$out" | tail -3; fail=1; }
[ "$rc" -eq 0 ] || { echo "  [FAIL] --heal rc=$rc"; fail=1; }

after=$($PY "$EX" --xray "$TMP" 2>&1 | grep -c '\[CRASH PATH\]' || true)
[ "$after" -eq 0 ] && echo '  [OK] ПОСЛЕ: крашей 0 (перепроверка машинная)' \
  || { echo "  [FAIL] ПОСЛЕ: крашей $after"; fail=1; }

grep -q 'KERN HEAL' "$TMP" && echo '  [OK] патч реально ВСТАВЛЕН в исходник' \
  || { echo '  [FAIL] патч не вставлен'; fail=1; }

# Д7: бэкап обязан существовать и содержать ИСХОДНЫЙ (багованный) код.
if [ -f "$TMP.bak" ]; then
  echo '  [OK] бэкап <file>.bak создан'
  grep -q 'KERN HEAL' "$TMP.bak" && { echo '  [FAIL] бэкап содержит патч (должен — оригинал)'; fail=1; } \
    || echo '  [OK] бэкап содержит ОРИГИНАЛ (без патча)'
else
  echo '  [FAIL] бэкап <file>.bak отсутствует'; fail=1
fi
[ -f "$TMP.kern_tmp" ] && { echo '  [FAIL] временный .kern_tmp не убран'; fail=1; } \
  || echo '  [OK] временный .kern_tmp убран (атомарная замена)'

rm -f "$TMP.bak"

rm -f "$TMP"
[ "$fail" -eq 0 ] && { echo '[OK] homeostatic-heal-check'; exit 0; }
echo '[FAIL] homeostatic-heal-check'; exit 1
