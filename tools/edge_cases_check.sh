#!/usr/bin/env bash
# KERN: КРАЙНИЕ СЛУЧАИ ЭКСТРАКТОРА КОНТРАКТОВ (цель `make edge-cases`).
#
# ЗАЧЕМ. Крайние случаи синтаксиса были найдены РУЧНОЙ проверкой и дважды
# вскрыли реальные дефекты парсера (`if (c) return X; else return Y;` и
# умножение на локальную константу). Здесь они закреплены как ПРОВЕРКА:
# цель падает, если хоть один ожидаемый вердикт исчез.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
cd "$ROOT" || exit 1

out="$("$PY" tools/kern_contracts.py examples/edge_cases.zig \
        examples/edge_cases.py 2>&1)"
fail=0

chk() { # $1 = ожидаемая подстрока, $2 = что проверяем
  if printf '%s' "$out" | grep -qF "$1"; then
    echo "  [OK]   $2"
  else
    echo "  [FAIL] $2 — нет ожидаемого «$1»"
    fail=1
  fi
}

echo "KERN: крайние случаи экстрактора контрактов"
echo "───────────────────────────────────────────────────────────────────────"
chk "[PASS] absOf"                 "Zig: else-ветвь отдельным оператором"
chk "[PASS] doubleViaConst"        "Zig: умножение на ЛОКАЛЬНУЮ константу"
chk "[PASS] pure_ok"               "Python: чистая функция доказывается"
chk "ПЕРЕПОЛНЕНИЕ типа \`u32\`"     "Zig: u32 underflow ловится"
chk "[IMPURE] impure_random"       "детектор чистоты: модуль random"
chk "[IMPURE] impure_global"       "детектор чистоты: global"
chk "zig-выражение вне подмножества" "Zig: встроенная @mod -> понятная причина SKIP (дефект #117)"
chk "вычисленное значение -1 вне диапазона" "Zig: u32 underflow подтверждён конкретным вычислителем (№14)"
chk "[BV] bitAlignedAgrees"        "Zig: битовые операции (& ~) -> теория QF_BV, доказано (№15)"

# --- ПУНКТ 5 ПЛАНА v2.5: МИНИМИЗАЦИЯ КОНТРПРИМЕРА ---------------------------
# Проверяем ГРАНИЦУ ЗВУЧИМОСТИ, а не «красоту» вывода: суженный SMT обязан
# содержать ВСЕ исходные `(assert ...)` ПЛЮС ровно одно ограничение окна.
# Если сужение потеряет исходные условия, «уменьшенный контрпример» перестанет
# быть контрпримером — и проверка обязана покраснеть.
mini="$("$PY" - <<'PYX'
import importlib.util
spec = importlib.util.spec_from_file_location('kc', 'tools/kern_contracts.py')
kc = importlib.util.module_from_spec(spec); spec.loader.exec_module(kc)
smt = ('(set-logic ALL)\n(declare-const x Int)\n(assert (>= x 1000000))\n'
       '(assert (not (<= x 500)))\n(check-sat)\n')
b = kc._bound_smt(smt, ['x'])
o = [l for l in smt.splitlines() if l.startswith('(assert')]
n = [l for l in b.splitlines() if l.startswith('(assert')]
print('MINIMIZE_OK' if (all(l in n for l in o) and len(n) == len(o) + 1)
      else 'MINIMIZE_BROKEN')
PYX
)"
if printf '%s' "$mini" | grep -qF "MINIMIZE_OK"; then
  echo "  [OK]   минимизация контрпримера: сужение ТОЛЬКО добавляет ограничения (№5)"
else
  echo "  [FAIL] минимизация потеряла исходные ограничения (нарушена звучимость)"
  fail=1
fi
# --- ДЕФЕКТЫ #202/#203 + полевые адаптеры (контрактный аудит 595 функций) -----
# #202: `requires` БЕЗ `ensures` — доказывать нечего; раньше печатался ЛОЖНЫЙ
#       «КОНТРАКТ НАРУШЕН» с бессмысленным контрпримером.
# #203: цепочка `0 <= a < b` (идиома Python/werkzeug) — раньше SKIP.
# raise: `if bad: raise ...` — гард, а не «вне подмножества».
TMP=$(mktemp -d)
cat > "$TMP/a202.py" <<'PYX'
# @kern:requires num != 0
def f202(value: int, num: int) -> int:
    return value % num
PYX
cat > "$TMP/b203.py" <<'PYX'
# @kern:requires length >= 0 and start >= 0
# @kern:ensures result == 0 or (start < stop and stop <= length)
def f203(start: int, stop: int, length: int) -> bool:
    if start >= stop:
        return False
    return 0 <= start < length
PYX
cat > "$TMP/c_raise.py" <<'PYX'
# @kern:requires amount > 0
# @kern:ensures result >= 0
def f_raise(balance: int, amount: int) -> int:
    if amount <= 0:
        raise ValueError(f"bad amount {amount}")
    return balance - amount
PYX
o202=$("$PY" tools/kern_contracts.py "$TMP/a202.py" 2>&1)
o203=$("$PY" tools/kern_contracts.py "$TMP/b203.py" 2>&1)
oras=$("$PY" tools/kern_contracts.py "$TMP/c_raise.py" 2>&1)
if printf '%s' "$o202" | grep -qF "нет @kern:ensures" && \
   ! printf '%s' "$o202" | grep -qF "КОНТРАКТ НАРУШЕН"; then
  echo "  [OK]   #202: requires без ensures -> SKIP (ложного FAIL нет)"
else
  echo "  [FAIL] #202: requires без ensures всё ещё даёт FAIL"; fail=1
fi
if printf '%s' "$o203" | grep -qF "length = 1" && \
   ! printf '%s' "$o203" | grep -qF "цепочка сравнений"; then
  echo "  [OK]   #203: цепочка 0 <= a < b разобрана, контрпример выдан"
else
  echo "  [FAIL] #203: цепочка сравнений снова отбрасывается"; fail=1
fi
if printf '%s' "$oras" | grep -qF "result = -1"; then
  echo "  [OK]   raise-гард: ветка raise отброшена, обязательство доказано/опровергнуто"
else
  echo "  [FAIL] raise-гард: функция с raise не проанализирована"; fail=1
fi
# ДЕФЕКТ #206: havoc-абстракция не имеет права давать DIVERGED.
cat > "$TMP/hv_old.py" <<'PY'
def f(x: int) -> int:
    if x > 0:
        return helper(x)
    return 0
PY
cat > "$TMP/hv_new.py" <<'PY'
def f(x: int) -> int:
    if x > 0:
        return helper(x + 1)
    return 0
PY
ohv=$("$PY" tools/kern_contracts.py --diff-equiv "$TMP/hv_old.py" "$TMP/hv_new.py" 2>&1); rhv=$?
if printf '%s' "$ohv" | grep -qF "[UNKNOWN]" && ! printf '%s' "$ohv" | grep -qF "[DIVERGED]" && [ "$rhv" = 2 ]; then
  echo "  [OK]   #206: вызов (havoc) -> UNKNOWN rc=2, ложного DIVERGED нет"
else
  echo "  [FAIL] #206: havoc снова объявлен расхождением (ложное обвинение)"; fail=1
fi
rm -rf "$TMP"
echo "───────────────────────────────────────────────────────────────────────"
if [ "$fail" = 0 ]; then
  echo "[OK] все крайние случаи воспроизведены"
else
  echo "[!] КРАЙНИЕ СЛУЧАИ СЛОМАНЫ — парсер потерял поддержку формы"
fi
exit $fail
