#!/usr/bin/env bash
# УНИВЕРСАЛЬНЫЙ АУДИТОР (--audit-repo): приёмка на РЕАЛЬНЫХ чужих каталогах.
# Требуется: паспорт со статистикой по языкам, топ-5 по Маккейбу, HTML-файл
# и НИ ОДНОГО падения на постороннем коде.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
ZSTD="${KERN_ZIG_STD:-/home/mrbritneyxxx/opt/zig-x86_64-linux-0.17.0/lib/std}"
PYLIB=$($PY -c 'import os;print(os.path.dirname(os.__file__))')
OUT=$(timeout 900 "$PY" tools/kern_contracts.py --audit-repo "$PYLIB/urllib" \
        --html-out /tmp/kern_audit_passport.html 2>&1); RC=$?
[ "$RC" -eq 0 ] || { echo "[!] --audit-repo упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -8
echo "$OUT" | grep -q 'AUDIT PASSPORT' || { echo "[!] нет паспорта"; exit 1; }
echo "$OUT" | grep -q 'Python .*проверено' || { echo "[!] нет статистики по языкам"; exit 1; }
echo "$OUT" | grep -q 'ТОП-5 по Маккейбу' || { echo "[!] нет топ-5 по CC"; exit 1; }
[ -s /tmp/kern_audit_passport.html ] || { echo "[!] HTML-паспорт не создан"; exit 1; }

# Второй реальный проект: std Zig (C-like путь, без аннотаций).
OUT2=$(timeout 900 "$PY" tools/kern_contracts.py --audit-repo "$ZSTD/math" 2>&1); RC2=$?
[ "$RC2" -eq 0 ] || { echo "[!] аудит std/math упал (rc=$RC2)"; exit 1; }
echo "$OUT2" | grep -q 'Zig .*файлов' || { echo "[!] нет статистики по Zig"; exit 1; }
ZCK=$(echo "$OUT2" | grep -oE 'Zig +файлов +[0-9]+ \| проверено +[0-9]+' | grep -oE 'проверено +[0-9]+' | grep -oE '[0-9]+')
[ "${ZCK:-0}" -gt 0 ] || { echo "[!] Zig: проверено 0 функций (регрессия C-like пути)"; exit 1; }
echo "[OK] audit-repo: паспорт + HTML + Python (urllib) + Zig (std/math, проверено $ZCK)"
