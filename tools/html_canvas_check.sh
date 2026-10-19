#!/usr/bin/env bash
# ЭШЕЛОН 8, ПУНКТ 40Б: ПРИЁМКА ИНТЕРАКТИВНОГО ХОЛСТА.
# Требуется: автономность (0 внешних ссылок), ползунки, квадрат Белнапа,
# встроенные данные функций и корректный HTML.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}; OUT=/tmp/kern_canvas.html; rm -f "$OUT"
OUTPUT=$(timeout 300 "$PY" tools/kern_contracts.py examples/presets_demo.py --html "$OUT" 2>&1)
echo "$OUTPUT" | tail -1
fail() { echo "[!] $1"; exit 1; }
[ -f "$OUT" ] || fail "холст НЕ создан"
SZ=$(stat -c%s "$OUT"); [ "$SZ" -gt 4000 ] || fail "холст слишком мал ($SZ байт)"
grep -q 'Explorable Proof Canvas' "$OUT" || fail "нет заголовка холста"
grep -q 'Belnap\|B<sub>4</sub>' "$OUT" || fail "нет квадрата Белнапа"
grep -q "rng.type='range'" "$OUT" || fail "нет ползунков (input range)"
grep -q 'const DATA =' "$OUT" || fail "данные функций НЕ встроены"
grep -q '</html>' "$OUT" || fail "HTML не закрыт"
if grep -qE 'https?://' "$OUT"; then fail "ВНЕШНИЕ ссылки (CDN) найдены — холст не автономен"; fi
echo "[OK] холст: $SZ байт, ползунки + B4 + данные, 0 внешних ссылок"
