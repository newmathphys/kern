#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# 36-Я СТАДИЯ (окно №7): РЕМОНТ СДВИНУТОГО ГАРДА ГРАНИЦЫ (`--heal`).
#
# ЧТО ДОКАЗЫВАЕТСЯ (дуга целиком, каждый шаг — реальный прогон):
#   ДО:     `--xray` печатает `[BOUNDS PATH]`, а функция ФИЗИЧЕСКИ падает
#           `IndexError` на `i == len(xs)` (сдвиг `>` вместо `>=`);
#   РЕМОНТ: `--heal` правит ТОЛЬКО оператор гарда (`>` -> `>=`) и печатает
#           `T (1,0)` + `сдвинутых гардов индекса: 1`; бэкап = оригинал;
#   ПОСЛЕ:  `[BOUNDS PATH]` ноль, физический прогон даёт `None` на краю и
#           ПРЕЖНИЕ значения на валидных входах (семантика не изменилась).
#   ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: файл с ПРАВИЛЬНЫМ гардом `>=` не меняется ни на байт
#           (иначе heal «лечил» бы всё подряд).
#
# ЧЕСТНАЯ ГРАНИЦА: срез узкий и названный — правится сравнение `i > len(b)` над
# доступом `b[i]`, где гард терминирует путь. `return 0` НЕ выдумывается,
# индекс НЕ подменяется; `None`-разыменование не входит (в SMT-модели нет Optional).
#
# НЕВАКУУМНОСТЬ: `KERN_CANFAIL_MUTATE=1` портит ОЖИДАНИЕ (гардов 2 вместо 1) ->
# rc!=0; `--selftest` прогоняет оба режима; реальный кейс — в tools/canfail.py.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
MUTATE=${KERN_CANFAIL_MUTATE:-0}

if ! "$PY" -c 'import z3' >/dev/null 2>&1; then
  if [ -x .venv/bin/python ] && .venv/bin/python -c 'import z3' >/dev/null 2>&1; then
    PY=.venv/bin/python
  else
    echo "[!] z3 недоступен для $PY — --xray без символической половины не проверить"
    exit 2
  fi
fi

if [ "${1:-}" = "--selftest" ]; then
  bash "$0" >/dev/null 2>&1; ok_rc=$?
  KERN_CANFAIL_MUTATE=1 bash "$0" >/dev/null 2>&1; mut_rc=$?
  if [ "$ok_rc" -eq 0 ] && [ "$mut_rc" -ne 0 ]; then
    echo "[OK] heal-index-check --selftest: норма -> rc=0, испорченное ожидание -> rc=$mut_rc"
    exit 0
  fi
  echo "[FAIL] heal-index-check --selftest: ok_rc=$ok_rc mut_rc=$mut_rc (мутация не ломает гейт)"
  exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/kern_heal_idx_XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/pick.py" <<'PY'
def pick(xs, i):
    if i < 0:
        return None
    if i > len(xs):
        return None
    return xs[i]
PY
cp "$WORK/pick.py" "$WORK/orig.py"

fails=0
# --- ДО ---
BEFORE=$("$PY" tools/kern_contracts.py --xray "$WORK/pick.py" 2>&1 | grep -c '\[BOUNDS PATH\]' || true)
[ "${BEFORE:-0}" -ge 1 ] || { echo "[FAIL] ДО: --xray не увидел выход за границу (BOUNDS PATH 0)"; fails=$((fails+1)); }
cat > "$WORK/probe_before.py" <<'PYPROBE'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("m", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
try:
    m.pick([1, 2, 3], 3)
except IndexError:
    raise SystemExit(0)
raise SystemExit(1)
PYPROBE
if "$PY" "$WORK/probe_before.py" "$WORK/pick.py" >/dev/null 2>&1; then
  :  # IndexError воспроизведён — это и требовалось
else
  echo "[FAIL] ДО: IndexError НЕ воспроизведён физически"; fails=$((fails+1))
fi

# --- РЕМОНТ ---
HEAL=$("$PY" tools/kern_contracts.py --heal "$WORK/pick.py" 2>&1); RC=$?
[ "$RC" -eq 0 ] || { echo "[FAIL] --heal rc=$RC"; fails=$((fails+1)); }
echo "$HEAL" | grep -q 'T (1,0)' || { echo "[FAIL] --heal не подтвердил лечение"; fails=$((fails+1)); }
WANT=${WANT_GUARDS:-1}; [ "$MUTATE" = "1" ] && WANT=2   # ИСПОРЧЕННОЕ ожидание
GOT=$(echo "$HEAL" | grep -o 'сдвинутых гардов индекса: [0-9]*' | grep -o '[0-9]*' | tail -1)
[ "${GOT:-0}" = "$WANT" ] || { echo "[FAIL] гардов индекса ${GOT:-0}, ожидалось $WANT"; fails=$((fails+1)); }
[ -f "$WORK/pick.py.bak" ] || { echo "[FAIL] бэкап .bak не создан"; fails=$((fails+1)); }
cmp -s "$WORK/pick.py.bak" "$WORK/orig.py" || { echo "[FAIL] бэкап не равен оригиналу"; fails=$((fails+1)); }
grep -q 'if i >= len(xs):' "$WORK/pick.py" || { echo "[FAIL] гард не исправлен на >="; fails=$((fails+1)); }

# --- ПОСЛЕ ---
AFTER=$("$PY" tools/kern_contracts.py --xray "$WORK/pick.py" 2>&1 | grep -c '\[BOUNDS PATH\]' || true)
[ "${AFTER:-0}" -eq 0 ] || { echo "[FAIL] ПОСЛЕ: остались BOUNDS PATH (${AFTER:-0})"; fails=$((fails+1)); }
PHYS=$("$PY" - "$WORK/pick.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("m", sys.argv[1]); m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print("edge=%s" % m.pick([1, 2, 3], 3))
print("normal=%s" % m.pick([1, 2, 3], 2))
print("negative=%s" % m.pick([1, 2, 3], -1))
PY
)
echo "$PHYS" | grep -q 'edge=None' || { echo "[FAIL] ПОСЛЕ: край i=len не вернул None"; fails=$((fails+1)); }
echo "$PHYS" | grep -q 'normal=3' || { echo "[FAIL] ПОСЛЕ: сломана семантика валидного входа"; fails=$((fails+1)); }
echo "$PHYS" | grep -q 'negative=None' || { echo "[FAIL] ПОСЛЕ: отрицательный индекс не отсечён"; fails=$((fails+1)); }

# --- ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: правильный гард не трогаем ---
sed 's/if i > len(xs):/if i >= len(xs):/' "$WORK/orig.py" > "$WORK/ok.py"
cp "$WORK/ok.py" "$WORK/ok_before.py"
OKOUT=$("$PY" tools/kern_contracts.py --heal "$WORK/ok.py" 2>&1)
echo "$OKOUT" | grep -q 'патчить нечего' || { echo "[FAIL] правильный гард: ожидалось «патчить нечего»"; fails=$((fails+1)); }
cmp -s "$WORK/ok.py" "$WORK/ok_before.py" || { echo "[FAIL] правильный гард ИЗМЕНЁН (ложное лечение)"; fails=$((fails+1)); }

if [ "$fails" -ne 0 ]; then
  echo "[FAIL] heal-index-check: провалов $fails"
  exit 1
fi
echo "[OK] heal-index-check: BOUNDS PATH ${BEFORE:-0}->0, IndexError снят, валидные входы целы, правильный гард не тронут"
exit 0
