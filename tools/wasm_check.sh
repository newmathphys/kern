#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
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
         'kern_wasm_admission_valid','kern_wasm_lia_unsat2',
         'kern_wasm_verify_proof')
miss = [n for n in names if n.encode() not in d]
if miss:
    print('  [FAIL] нет экспортов:', miss); ok = False
else:
    print('  [OK] все 5 экспортов присутствуют')
sys.exit(0 if ok else 1)
PY
[ $? -ne 0 ] && fail=1

# Прямой `zig test src/wasm_api.zig` НЕ работает: модуль `compat` передаётся
# только сборочной системой. Поэтому семантику гоняем ШТАТНЫМ раннером —
# `src/test_root.zig` импортирует wasm_api (правило №10 Кодекса).
if $ZIG build test --summary all >/tmp/wasm_test.log 2>&1; then
  echo "  [OK] семантика: zig build test rc=0 (тесты wasm_api входят в test_root)"
else
  echo '  [FAIL] zig build test'; tail -8 /tmp/wasm_test.log; fail=1
fi

# ДЕФЕКТ #462 (ИЗМЕРЕНО): файл, который раздаётся на сайте
# (`docs/kernc.wasm`), НИКОГДА не собирался и не сверялся с кодом: он был
# 86 953 Б от 19 окт, тогда как текущая сборка — 104 557 Б (разные sha256).
# Теперь паритет ПРОВЕРЯЕТСЯ: раздаваемый модуль обязан совпадать с текущей
# сборкой, иначе гейт краснеет и называет команду обновления.
if [ -f docs/kernc.wasm ]; then
  if cmp -s zig-out/bin/kernc.wasm docs/kernc.wasm; then
    echo '  [OK] паритет: docs/kernc.wasm == zig-out/bin/kernc.wasm'
  else
    echo '  [FAIL] docs/kernc.wasm РАСХОДИТСЯ с текущей сборкой (#462)'
    echo '         обновите: cp zig-out/bin/kernc.wasm docs/kernc.wasm'
    fail=1
  fi
else
  echo '  [FAIL] docs/kernc.wasm отсутствует — сайт раздаёт нечего (#462)'; fail=1
fi

# ФУНКЦИОНАЛЬНЫЙ ПРОГОН (Испытание 5): модуль РЕАЛЬНО исполняется и
# сверяется с независимым оракулом (таблица Белнапа + звучие свойства LIA).
# Без `node` это НАЗВАНО, а не выдаётся за проверку.
if command -v node >/dev/null 2>&1; then
  if node tools/wasm_parity_check.js; then
    echo '  [OK] функциональный паритет: вердикты раздаваемого модуля == оракул'
  else
    echo '  [FAIL] функциональный паритет wasm нарушен (#462)'; fail=1
  fi
else
  echo '  [i] функциональный паритет НЕ ПРОВЕРЕН: нет node (не выдаётся за проверку)'
fi

if [ "$fail" -eq 0 ]; then echo '[OK] wasm-check: сборка + байты + семантика + паритет сайта'; exit 0; fi
echo '[FAIL] wasm-check'; exit 1
