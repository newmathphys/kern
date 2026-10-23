#!/usr/bin/env bash
# N2: рабочие файлы прогона живут в СВОЁМ каталоге, а не в общем /tmp
# (гонка двух прогонов уже портила вердикты). Каталог снимается по выходу.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/kern_work.XXXXXX")"; export WORK
trap 'rm -rf "$WORK"' EXIT INT TERM
# УНИВЕРСАЛЬНЫЙ АУДИТОР (--audit-repo): приёмка на РЕАЛЬНЫХ чужих каталогах.
# Требуется: паспорт со статистикой по языкам, топ-5 по Маккейбу, HTML-файл
# и НИ ОДНОГО падения на постороннем коде.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
ZSTD="${KERN_ZIG_STD:-/home/mrbritneyxxx/opt/zig-x86_64-linux-0.17.0/lib/std}"
PYLIB=$($PY -c 'import os;print(os.path.dirname(os.__file__))')
OUT=$(timeout 900 "$PY" tools/kern_contracts.py --audit-repo "$PYLIB/urllib" \
        --html-out $WORK/kern_audit_passport.html 2>&1); RC=$?
[ "$RC" -eq 0 ] || { echo "[!] --audit-repo упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -8
echo "$OUT" | grep -q 'AUDIT PASSPORT' || { echo "[!] нет паспорта"; exit 1; }
echo "$OUT" | grep -q 'Python .*проверено' || { echo "[!] нет статистики по языкам"; exit 1; }
echo "$OUT" | grep -q 'ТОП-5 по Маккейбу' || { echo "[!] нет топ-5 по CC"; exit 1; }
[ -s $WORK/kern_audit_passport.html ] || { echo "[!] HTML-паспорт не создан"; exit 1; }

# Второй реальный проект: std Zig (C-like путь, без аннотаций).
OUT2=$(timeout 900 "$PY" tools/kern_contracts.py --audit-repo "$ZSTD/math" 2>&1); RC2=$?
[ "$RC2" -eq 0 ] || { echo "[!] аудит std/math упал (rc=$RC2)"; exit 1; }
echo "$OUT2" | grep -q 'Zig .*файлов' || { echo "[!] нет статистики по Zig"; exit 1; }
ZCK=$(echo "$OUT2" | grep -oE 'Zig +файлов +[0-9]+ \| проверено +[0-9]+' | grep -oE 'проверено +[0-9]+' | grep -oE '[0-9]+')
[ "${ZCK:-0}" -gt 0 ] || { echo "[!] Zig: проверено 0 функций (регрессия C-like пути)"; exit 1; }
# --- ЗАЩИТА 1: «мина» внутри мусорных каталогов обязана ИГНОРИРОВАТЬСЯ ---------
MINE=$(mktemp -d /tmp/kern_mine_XXXXXX)
mkdir -p "$MINE/node_modules/pkg" "$MINE/src" "$MINE/.venv/lib"
cat > "$MINE/node_modules/pkg/bomb.py" <<'PY'
def bomb(a, b):
    if a > 10:
        return 1
    return a / b
PY
cp "$MINE/node_modules/pkg/bomb.py" "$MINE/.venv/lib/bomb2.py"
cat > "$MINE/src/real.py" <<'PY'
def ok(x):
    if x > 5:
        return 1
    return 0
PY
MOUT=$(timeout 200 "$PY" tools/kern_contracts.py --audit-repo "$MINE" 2>&1)
echo "$MOUT" | tail -5
if echo "$MOUT" | grep -q 'bomb'; then
  echo "[!] МИНА В node_modules НЕ ПРОИГНОРИРОВАНА"; rm -rf "$MINE"; exit 1
fi
rm -rf "$MINE"
echo "[OK] мусорные каталоги (node_modules/.venv) игнорируются"

# --- ЗАЩИТА 2: SIGTERM не оставляет /dev/shm/kern_audit_* ---------------------
BEFORE=$(ls -d /dev/shm/kern_audit_* 2>/dev/null | wc -l)
timeout 30 "$PY" tools/kern_contracts.py --audit-repo "$ZSTD" > /dev/null 2>&1 &
KPID=$!
sleep 3
kill -TERM $KPID 2>/dev/null || true
wait $KPID 2>/dev/null || true
sleep 1
AFTER=$(ls -d /dev/shm/kern_audit_* 2>/dev/null | wc -l)
[ "$AFTER" -le "$BEFORE" ] || { echo "[!] SIGTERM оставил $AFTER временных папок в /dev/shm"; exit 1; }
echo "[OK] SIGTERM: 0 осиротевших каталогов в /dev/shm"

echo "[OK] audit-repo: паспорт + HTML + Python + Zig + фильтр мусора + SIGTERM-уборка"
