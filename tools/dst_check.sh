#!/usr/bin/env bash
# РАЗДЕЛ 7 ЭНЦИКЛОПЕДИИ: Deterministic Simulation Testing (TigerBeetle-style).
# Приёмка: 10 сидов x 50 шагов, 4 инварианта, детерминизм, НЕНУЛЕВЫЕ перехваты.
set -u
ZIG=${ZIG:-zig}
fail=0
if ! $ZIG build dst >/tmp/dst_build.log 2>&1; then
  echo '  [FAIL] zig build dst'; tail -6 /tmp/dst_build.log; exit 1
fi
out=$(./zig-out/bin/kern-dst --seeds 10 --steps 50 2>&1); rc=$?
echo "$out" | grep -q 'инварианты=OK' && echo '  [OK] инварианты (gate/contradiction/stale/tamper) не нарушены' \
  || { echo '  [FAIL] инварианты нарушены'; fail=1; }
echo "$out" | grep -q 'детерминизм=ДА' && echo '  [OK] детерминизм: один seed -> побитово та же трасса' \
  || { echo '  [FAIL] детерминизм не подтверждён'; fail=1; }
caught=$(echo "$out" | grep -oE 'перехватов=[0-9]+' | grep -oE '[0-9]+')
if [ "${caught:-0}" -gt 0 ]; then
  echo "  [OK] сбои реально перехватывались: $caught (цель не вакуумна)"
else
  echo '  [FAIL] перехватов 0 — симулятор не создаёт сбоев'; fail=1
fi
[ "$rc" -eq 0 ] || { echo "  [FAIL] kern-dst rc=$rc"; fail=1; }
[ "$fail" -eq 0 ] && { echo '[OK] dst-check'; exit 0; }
echo '[FAIL] dst-check'; exit 1
