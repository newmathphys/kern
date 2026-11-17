#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# 35-Я СТАДИЯ: НАТИВНОЕ ЯДРО НЕСОВМЕСТНОСТИ НА ПРОИЗВОЛЬНОМ ФАЙЛЕ (`kernc unsat-core`).
#
# ЧТО ДОКАЗЫВАЕТСЯ (каждое — реальный прогон, не обещание):
#   1) файл с противоречием + ШУМОВЫЕ ассерты: ядро = ровно конфликтующие,
#      шум в ядро НЕ попадает; коды: UNSAT -> rc=1, SAT -> rc=0, мусор -> rc=2;
#   2) НЕПРИВОДИМОСТЬ проверяется физически: для КАЖДОГО элемента ядра
#      строится файл без него и ОБЯЗАН получиться SAT (rc=0);
#   3) печатаются НОМЕРА СТРОК исходного файла (`[CORE_LINES]`), а не абстракции.
#
# НЕВАКУУМНОСТЬ (двусторонняя): `KERN_CANFAIL_MUTATE=1` портит ОДНО ожидание
# (ядро `a1` вместо `a2 a3 a4`) -> гейт ОБЯЗАН упасть; `--selftest` прогоняет
# оба режима и краснеет, если мутация не ломает проверку. Реальная мутация
# движка зарегистрирована в `tools/canfail.py` (кейс `unsat-core`).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
KERNC=${KERNC:-zig-out/bin/kernc}
MUTATE=${KERN_CANFAIL_MUTATE:-0}

# ДВУСТОРОННЯЯ НЕВАКУУМНОСТЬ: норма -> 0, испорченное ожидание -> != 0.
if [ "${1:-}" = "--selftest" ]; then
  bash "$0" >/dev/null 2>&1; ok_rc=$?
  KERN_CANFAIL_MUTATE=1 bash "$0" >/dev/null 2>&1; mut_rc=$?
  if [ "$ok_rc" -eq 0 ] && [ "$mut_rc" -ne 0 ]; then
    echo "[OK] unsat-core-check --selftest: норма -> rc=0, испорченное ядро -> rc=$mut_rc"
    exit 0
  fi
  echo "[FAIL] unsat-core-check --selftest: ok_rc=$ok_rc mut_rc=$mut_rc (мутация не ломает гейт)"
  exit 1
fi

# z3 нужен НАТИВНОМУ мосту (Python-модуль не считается): ищем в PATH и в .venv.
if ! command -v z3 >/dev/null 2>&1; then
  if [ -x .venv/bin/z3 ]; then
    PATH="$PWD/.venv/bin:$PATH"; export PATH
  else
    echo "[!] нет бинаря z3 (ни в PATH, ни в .venv/bin) — нативное ядро не посчитать"
    exit 2
  fi
fi
[ -x "$KERNC" ] || { echo "[!] нет $KERNC — сначала zig build"; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/kern_ucore_XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# ИСТОЧНИК: 5 пунктов, из них 2 шумовых (a1, a5). Конфликт — a2/a3/a4.
cat > "$WORK/unsat.smt2" <<'SMT'
(set-logic ALL)
(declare-const min_fee Int)
(declare-const max_fee Int)
(declare-const tier Int)
(assert (>= tier 0))
(assert (>= min_fee 10))
(assert (<= max_fee 5))
(assert (<= min_fee max_fee))
(assert (<= max_fee 1000))
(check-sat)
SMT

fails=0
run_case() { # $1=файл, печатает stdout+stderr, возвращает rc
  "$KERNC" unsat-core "$1" 2>&1
}

OUT=$(run_case "$WORK/unsat.smt2"); RC=$?
[ "$RC" -eq 1 ] || { echo "[FAIL] UNSAT-файл: rc=$RC, ожидалось 1"; fails=$((fails+1)); }
echo "$OUT" | grep -q '\[UNSAT CORE\]' || { echo "[FAIL] нет маркера [UNSAT CORE]"; fails=$((fails+1)); }
CORE=$(echo "$OUT" | sed -n 's/^\[CORE\] //p')
LINES=$(echo "$OUT" | sed -n 's/^\[CORE_LINES\] //p')
WANT='a2 a3 a4'
[ "$MUTATE" = "1" ] && WANT='a1 a3 a4'   # ИСПОРЧЕННОЕ ожидание
[ "$CORE" = "$WANT" ] || { echo "[FAIL] ядро '$CORE', ожидалось '$WANT'"; fails=$((fails+1)); }
[ "$LINES" = "6 7 8" ] || { echo "[FAIL] строки ядра '$LINES', ожидалось '6 7 8'"; fails=$((fails+1)); }
echo "$CORE" | grep -qE '(^| )a1( |$)' && { echo "[FAIL] ШУМ a1 попал в ядро"; fails=$((fails+1)); }
echo "$CORE" | grep -qE '(^| )a5( |$)' && { echo "[FAIL] ШУМ a5 попал в ядро"; fails=$((fails+1)); }

# НЕПРИВОДИМОСТЬ: без любого элемента ядра набор обязан стать SAT.
"$PY" - "$WORK" <<'PYEOF'
import sys, pathlib
w = pathlib.Path(sys.argv[1])
text = (w / "unsat.smt2").read_text(encoding="utf-8").splitlines()
asserts = [i for i, l in enumerate(text) if l.startswith("(assert")]
for k, idx in enumerate(asserts, 1):
    subset = [l for j, l in enumerate(text) if j != idx]
    (w / ("drop_a%d.smt2" % k)).write_text("\n".join(subset) + "\n", encoding="utf-8")
PYEOF
for k in 1 2 3 4 5; do
  OUTK=$(run_case "$WORK/drop_a$k.smt2"); RCK=$?
  if echo " $CORE " | grep -q " a$k "; then
    # элемент ЯДРА: без него обязателен SAT
    [ "$RCK" -eq 0 ] || { echo "[FAIL] ядро НЕ неприводимо: без a$k rc=$RCK (ожидался SAT)"; fails=$((fails+1)); }
  else
    # шумовой элемент: без него конфликт обязан СОХРАНИТЬСЯ
    [ "$RCK" -eq 1 ] || { echo "[FAIL] шум a$k влияет на конфликт (без него rc=$RCK)"; fails=$((fails+1)); }
  fi
done

# SAT-файл и мусор
sed 's/(>= min_fee 10)/(>= min_fee 1)/' "$WORK/unsat.smt2" > "$WORK/sat.smt2"
OUTS=$(run_case "$WORK/sat.smt2"); RCS=$?
[ "$RCS" -eq 0 ] || { echo "[FAIL] SAT-файл: rc=$RCS, ожидалось 0"; fails=$((fails+1)); }
echo "$OUTS" | grep -q '\[SAT\]' || { echo "[FAIL] SAT-файл без маркера [SAT]"; fails=$((fails+1)); }
printf '(set-logic ALL)\n' > "$WORK/empty.smt2"
OUTE=$(run_case "$WORK/empty.smt2"); RCE=$?
[ "$RCE" -eq 2 ] || { echo "[FAIL] файл без assert: rc=$RCE, ожидалось 2"; fails=$((fails+1)); }

if [ "$fails" -ne 0 ]; then
  echo "[FAIL] unsat-core-check: провалов $fails"
  exit 1
fi
echo "[OK] unsat-core-check: нативное ядро {a2 a3 a4} (строки 6 7 8), шум отброшен, снятие любого элемента -> SAT, rc 1/0/2"
exit 0
