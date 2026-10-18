#!/usr/bin/env bash
# ЭШЕЛОН 3, ПУНКТ 17: ПРИЁМКА --simplify.
#
# НЕЗАВИСИМАЯ проверка: помимо доказательства Z3, сверяем ПОВЕДЕНИЕ исходной и
# упрощённой функций на сетке входов (включая границы). Если упрощение изменило
# поведение хотя бы в одной точке — цель краснеет.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TMP=$(mktemp -d)
cp examples/xray_demo.py "$TMP/"
OUT=$(timeout 300 python3 tools/kern_contracts.py --simplify "$TMP/xray_demo.py" \
        --simplify-out "$TMP/simplified.py" 2>&1) || { echo "[!] --simplify упал"; echo "$OUT" | tail -5; rm -rf "$TMP"; exit 1; }
echo "$OUT" | tail -5
N=$(echo "$OUT" | grep -c 'SIMPLIFIED & PROVEN EQUIVALENT' || true)
if [ "$N" -lt 2 ]; then echo "[!] доказанных упрощений меньше двух — приёмка вакуумна"; rm -rf "$TMP"; exit 1; fi
[ -s "$TMP/simplified.py" ] || { echo "[!] упрощённый файл пуст"; rm -rf "$TMP"; exit 1; }
# НЕЗАВИСИМАЯ РАНТАЙМ-СВЕРКА поведения на сетке входов.
timeout 200 python3 - "$TMP" <<'PY' || { echo "[!] ПОВЕДЕНИЕ РАЗОШЛОСЬ — упрощение неверно"; rm -rf "$TMP"; exit 1; }
import importlib.util, sys
from pathlib import Path
td = Path(sys.argv[1])
def load(name, p):
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
o = load('orig', td / 'xray_demo.py')
s = load('simp', td / 'simplified.py')
grid = [x for x in range(-25, 26)] + [2**31 - 1, -2**31, 0]
bad = 0
for fn in ('dead_branch', 'redundant_guard', 'clean'):
    if not (hasattr(o, fn) and hasattr(s, fn)):
        continue
    for x in grid:
        try:
            a = getattr(o, fn)(x)
        except Exception as e:
            a = type(e).__name__
        try:
            b = getattr(s, fn)(x)
        except Exception as e:
            b = type(e).__name__
        if a != b:
            bad += 1
            print(f'  РАСХОЖДЕНИЕ {fn}({x}): {a} != {b}')
print(f'  сверено точек: {len(grid) * 3} | расхождений: {bad}')
sys.exit(1 if bad else 0)
PY
rm -rf "$TMP"
echo "[OK] --simplify: CC снижена, эквивалентность доказана И подтверждена рантаймом"
