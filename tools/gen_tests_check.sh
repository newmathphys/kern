#!/usr/bin/env bash
# ЭШЕЛОН 3, ПУНКТ 14: ПРИЁМКА --gen-tests. Генерируем pytest и РЕАЛЬНО его гоняем.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TMP=$(mktemp -d)
cp examples/xray_demo.py "$TMP/"
OUT=$(timeout 300 python3 tools/kern_contracts.py --gen-tests "$TMP/xray_demo.py" "$TMP/gen_test_demo.py" 2>&1) || { echo "[!] --gen-tests упал"; echo "$OUT" | tail -5; rm -rf "$TMP"; exit 1; }
echo "$OUT" | tail -2
if [ ! -s "$TMP/gen_test_demo.py" ]; then echo "[!] файл тестов пуст"; rm -rf "$TMP"; exit 1; fi
N=$(grep -c '^def test_' "$TMP/gen_test_demo.py" || true)
D=$(grep -c 'НЕДОСТИЖИМА' "$TMP/gen_test_demo.py" || true)
echo "  сгенерировано тестов: $N | помечено недостижимых: $D"
if [ "$N" -lt 2 ]; then echo "[!] тестов меньше двух — приёмка вакуумна"; rm -rf "$TMP"; exit 1; fi
# pytest может отсутствовать в PATH у make: тогда запускаем тем же раннером,
# что и pytest (импорт модуля + вызов всех test_*), и ГОВОРИМ об этом честно.
if python3 -c 'import pytest' 2>/dev/null; then
  ( cd "$TMP" && timeout 200 python3 -m pytest -q gen_test_demo.py ) || { echo "[!] сгенерированные тесты НЕ проходят"; rm -rf "$TMP"; exit 1; }
  echo "  (прогон: pytest)"
else
  ( cd "$TMP" && timeout 200 python3 -c "
import importlib.util, sys, traceback
spec = importlib.util.spec_from_file_location('g', 'gen_test_demo.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fns = [n for n in dir(m) if n.startswith('test_')]
bad = 0
for n in sorted(fns):
    try:
        getattr(m, n)()
    except Exception:
        bad += 1; traceback.print_exc()
print(f'выполнено тестов: {len(fns)} | провалов: {bad}')
sys.exit(1 if bad else 0)
" ) || { echo "[!] сгенерированные тесты НЕ проходят"; rm -rf "$TMP"; exit 1; }
  echo "  (прогон: встроенный раннер — pytest в PATH отсутствует)"
fi
rm -rf "$TMP"
echo "[OK] --gen-tests: сгенерированные pytest-тесты проходят, мёртвые ветки помечены"
