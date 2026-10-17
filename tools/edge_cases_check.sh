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
echo "───────────────────────────────────────────────────────────────────────"
if [ "$fail" = 0 ]; then
  echo "[OK] все крайние случаи воспроизведены"
else
  echo "[!] КРАЙНИЕ СЛУЧАИ СЛОМАНЫ — парсер потерял поддержку формы"
fi
exit $fail
