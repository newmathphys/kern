#!/usr/bin/env bash
# РАЗДЕЛ 5: конколическое исполнение (Concrete + Symbolic).
# Приёмка требует РЕАЛЬНОГО покрытия всех достижимых ветвей и нулевых мёртвых.
set -u
PY=${PYTHON:-python3}
EX=${KERNC_EXTRACTOR:-tools/kern_contracts.py}
out=$($PY "$EX" --concolic examples/concolic_demo.py 2>&1); rc=$?
fail=0
echo "$out" | grep -q 'covered 6/6' && echo '  [OK] покрытие 6/6 (все достижимые ветви исполнены ВЖИВУЮ)' \
  || { echo '  [FAIL] неполное покрытие'; echo "$out" | tail -3; fail=1; }
echo "$out" | grep -q 'dead 0' && echo '  [OK] мёртвых ветвей 0 (нет скрытых UNSAT-веток)' \
  || { echo '  [FAIL] найдены мёртвые ветви'; fail=1; }
runs=$(echo "$out" | grep -oE 'concrete runs [0-9]+' | grep -oE '[0-9]+' | head -1)
[ "${runs:-0}" -ge 5 ] && echo "  [OK] реальных запусков $runs (не статический перебор)'" \
  || { echo "  [FAIL] запусков ${runs:-0} — слишком мало"; fail=1; }
[ "$rc" -eq 0 ] || { echo "  [FAIL] rc=$rc"; fail=1; }
[ "$fail" -eq 0 ] && { echo '[OK] concolic-check'; exit 0; }
echo '[FAIL] concolic-check'; exit 1
