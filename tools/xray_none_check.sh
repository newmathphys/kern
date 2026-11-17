#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# 37-Я СТАДИЯ (окно №9): ДЕТЕКЦИЯ РАЗЫМЕНОВАНИЯ None (`--xray-none`) + LIVE REPLAY.
#
# ЧТО ДОКАЗЫВАЕТСЯ (каждый пункт — реальный прогон):
#   1) НЕЗАЩИЩЁННАЯ арифметика на nullable-параметре -> [CRASH PATH] И физический
#      TypeError при вызове с None (Live Replay: без подтверждения — нет находки);
#   2) АТРИБУТ на nullable -> [CRASH PATH] и физический AttributeError;
#   3) None-ГАРД снимает находку (`if x is None: return 0`);
#   4) ПЕРЕПРИСВАИВАНИЕ в ветке (`if x is None: x = 0`) снимает находку —
#      ИЗМЕРЕНО как ложное срабатывание первой версии детектора;
#   5) `v = d.get(k)` НЕ проверяется (граница: `dict.get` вне SMT-подмножества) —
#      детектор обязан молчать, а не гадать;
#   6) `x = x + 1` ловится (разыменование ДО переприсваивания).
#
# ЗАКОН LIVE REPLAY: находка засчитывается, только если вызов с НАСТОЯЩИМ None
# даёт ровно тот тип исключения, который обещан в маркере.
#
# НЕВАКУУМНОСТЬ: KERN_CANFAIL_MUTATE=1 портит ожидание -> rc!=0; --selftest; canfail.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
MUTATE=${KERN_CANFAIL_MUTATE:-0}
if ! "$PY" -c 'import z3' >/dev/null 2>&1; then
  if [ -x .venv/bin/python ] && .venv/bin/python -c 'import z3' >/dev/null 2>&1; then
    PY=.venv/bin/python
  else
    echo "[!] z3 недоступен — обязательство None требует решателя"; exit 2
  fi
fi
if [ "${1:-}" = "--selftest" ]; then
  bash "$0" >/dev/null 2>&1; ok_rc=$?
  KERN_CANFAIL_MUTATE=1 bash "$0" >/dev/null 2>&1; mut_rc=$?
  if [ "$ok_rc" -eq 0 ] && [ "$mut_rc" -ne 0 ]; then
    echo "[OK] xray-none-check --selftest: норма -> rc=0, испорченное ожидание -> rc=$mut_rc"
    exit 0
  fi
  echo "[FAIL] xray-none-check --selftest: ok_rc=$ok_rc mut_rc=$mut_rc"
  exit 1
fi
WORK="$(mktemp -d "${TMPDIR:-/tmp}/kern_none_XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
fails=0

# --- фикстуры ---
printf 'def f(x):\n    if x is not None:\n        return 0\n    return x + 1\n' > "$WORK/arith.py"
printf 'def g(x=None):\n    return x.bit_length()\n' > "$WORK/attr.py"
printf 'def f(x=None):\n    if x is None:\n        return 0\n    return x + 1\n' > "$WORK/guarded.py"
printf 'def f(x=None):\n    if x is None:\n        x = 0\n    return x + 1\n' > "$WORK/reset.py"
printf 'def h(d, k):\n    v = d.get(k)\n    if v is not None:\n        return 0\n    return v * 2\n' > "$WORK/getlocal.py"
printf 'def f(x=None):\n    x = x + 1\n    return x\n' > "$WORK/reassign.py"

count() { "$PY" tools/kern_contracts.py --xray-none "$1" 2>/dev/null | tail -1 | grep -o 'находок [0-9]*' | grep -o '[0-9]*'; }
WANT_ARITH=1; WANT_ATTR=1; WANT_GUARD=0; WANT_RESET=0; WANT_GET=0; WANT_REAS=1
[ "$MUTATE" = "1" ] && WANT_GUARD=1   # ИСПОРЧЕННОЕ ожидание
expect() { # $1 файл, $2 ожидание, $3 метка
  got=$(count "$1"); got=${got:-0}
  [ "$got" = "$2" ] || { echo "[FAIL] $3: находок $got, ожидалось $2"; fails=$((fails+1)); }
}
expect "$WORK/arith.py"   "$WANT_ARITH" "арифметика на None"
expect "$WORK/attr.py"    "$WANT_ATTR"  "атрибут на None"
expect "$WORK/guarded.py" "$WANT_GUARD" "None-гард снимает находку"
expect "$WORK/reset.py"   "$WANT_RESET" "переприсваивание в ветке снимает находку"
expect "$WORK/getlocal.py" "$WANT_GET"  "dict.get-локал — граница (молчим)"
expect "$WORK/reassign.py" "$WANT_REAS" "разыменование ДО переприсваивания"

# --- LIVE REPLAY: находка засчитывается только с ФИЗИЧЕСКИМ исключением ---
"$PY" - "$WORK" <<'PYEOF'
import sys, pathlib
w = pathlib.Path(sys.argv[1])
def load(p):
    ns = {}
    exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), ns)
    return ns
for name, fn_name, args, want in (
    ("arith.py", "f", (None,), "TypeError"),
    ("attr.py", "g", (None,), "AttributeError"),
    ("reassign.py", "f", (None,), "TypeError"),
):
    ns = load(w / name)
    try:
        ns[fn_name](*args)
    except Exception as exc:
        got = type(exc).__name__
        if got != want:
            print("[FAIL] Live Replay %s: %s, ожидалось %s" % (name, got, want))
            raise SystemExit(1)
        print("[OK] Live Replay %s -> %s" % (name, got))
    else:
        print("[FAIL] Live Replay %s: НЕ упал на None" % name)
        raise SystemExit(1)
PYEOF
[ "$?" -eq 0 ] || fails=$((fails+1))

if [ "$fails" -ne 0 ]; then
  echo "[FAIL] xray-none-check: провалов $fails"
  exit 1
fi
echo "[OK] xray-none-check: None-разыменование найдено, гард/переприсваивание снимают находку, Live Replay подтверждает TypeError/AttributeError"
exit 0
