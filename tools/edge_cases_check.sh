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
echo "───────────────────────────────────────────────────────────────────────"
if [ "$fail" = 0 ]; then
  echo "[OK] все крайние случаи воспроизведены"
else
  echo "[!] КРАЙНИЕ СЛУЧАИ СЛОМАНЫ — парсер потерял поддержку формы"
fi
exit $fail
