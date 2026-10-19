#!/usr/bin/env bash
# ЭШЕЛОН 8, ПУНКТ 40А: приёмка WebAssembly-ядра.
# Проверяет ТРИ вещи, иначе гейт был бы вакуумным:
#   1) сборка `zig build wasm` проходит;
#   2) байты модуля: магия WASM + размер < 512 КБ (No-Bloat Gate);
#   3) СЕМАНТИКА экспортов — те же функции прогоняются НАТИВНО (`zig test`).
set -u
ZIG=${ZIG:-zig}
fail=0

if ! $ZIG build wasm >/tmp/wasm_build.log 2>&1; then
  echo '[FAIL] zig build wasm'; tail -5 /tmp/wasm_build.log; exit 1
fi
echo '  [OK] zig build wasm -> rc=0'

python3 - <<'PY'
import sys
d = open('zig-out/bin/kernc.wasm','rb').read()
ok = True
if d[:8] != b'\x00asm\x01\x00\x00\x00':
    print('  [FAIL] магия WASM неверна'); ok = False
else:
    print('  [OK] магия WASM верна')
if len(d) >= 512 * 1024:
    print(f'  [FAIL] No-Bloat: {len(d)} байт >= 512 KB'); ok = False
else:
    print(f'  [OK] No-Bloat: {len(d)} байт < 512 KB')
names = ('kern_wasm_belnap_join','kern_wasm_belnap_allow',
         'kern_wasm_admission_valid','kern_wasm_lia_unsat2')
miss = [n for n in names if n.encode() not in d]
if miss:
    print('  [FAIL] нет экспортов:', miss); ok = False
else:
    print('  [OK] все 4 экспорта присутствуют')
sys.exit(0 if ok else 1)
PY
[ $? -ne 0 ] && fail=1

if $ZIG test src/wasm_api.zig -O ReleaseSmall >/tmp/wasm_test.log 2>&1; then
  n=$(grep -oE 'All [0-9]+ tests passed' /tmp/wasm_test.log | head -1)
  echo "  [OK] семантика экспортов (нативно): ${n:-tests passed}"
else
  echo '  [FAIL] нативные тесты wasm_api.zig'; tail -6 /tmp/wasm_test.log; fail=1
fi

if [ "$fail" -eq 0 ]; then echo '[OK] wasm-check: сборка + байты + семантика'; exit 0; fi
echo '[FAIL] wasm-check'; exit 1
