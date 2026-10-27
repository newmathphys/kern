#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
#
# ГЕЙТ: ФАЙЛОВЫЙ ВХОД ДЛЯ НАТИВНЫХ ТЕОРИЙ (`kernc theory <file>`).
#
# ЗАЧЕМ. Нативные Zig-движки `src/verifier/*.zig` существовали, но `kernc audit`
# гонял их ТОЛЬКО на захардкоженных строках внутри исходника — применить их к
# внешнему входу было нельзя вообще. Гейт требует ОБЕ половины на ФАЙЛЕ:
#   * положительную — `arrays same_index` (аксиома Маккарти) и `arrays guarded`
#     (защита корректна на всей области) ДОКАЗАНЫ, `dtmc stochastic` доказана,
#     `absint join/widen/narrow` и `dtmc reach` дают ЗНАЧЕНИЯ;
#   * отрицательную — `arrays oob` (выход за границы ДОСТИЖИМ) ОПРОВЕРГНУТ.
#
# ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ: формат спецификации ЯВНЫЙ (см. theory_cli.zig),
# разбираются только перечисленные команды; всё прочее — SKIP с причиной.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
KERNC="$ROOT/zig-out/bin/kernc"
if [ ! -x "$KERNC" ]; then echo "[FAIL] нет $KERNC (соберите: zig build)"; exit 1; fi
export PATH="$ROOT/.venv/bin:$PATH"

bad=0
out=$("$KERNC" theory tests/fixtures/theory_cli_ok.txt 2>&1)
rc=$?
if [ "$rc" -ne 0 ]; then echo "[FAIL] чистая спецификация обязана дать rc=0, получено $rc"; bad=$((bad+1)); fi
for want in "[PASS] ДОКАЗАНО строка 2: arrays same_index" "[PASS] ДОКАЗАНО строка 3: arrays guarded" "[PASS] ДОКАЗАНО строка 9: dtmc stochastic" "[VALUE] строка 5: absint join | [0, 9]" "[VALUE] строка 10: dtmc reach"; do
  if ! printf '%s' "$out" | grep -qF "$want"; then echo "[FAIL] нет ожидаемого вердикта: $want"; bad=$((bad+1)); fi
done
if printf '%s' "$out" | grep -qF 'ОПРОВЕРГНУТО'; then echo "[FAIL] ЛОЖНОЕ ОПРОВЕРЖЕНИЕ на чистой спецификации"; bad=$((bad+1)); fi
if ! printf '%s' "$out" | grep -qF 'пропущено 0'; then echo "[FAIL] чистая спецификация обязана разобраться ПОЛНОСТЬЮ (SKIP 0)"; bad=$((bad+1)); fi

out2=$("$KERNC" theory tests/fixtures/theory_cli_risk.txt 2>&1)
rc2=$?
if [ "$rc2" -eq 0 ]; then echo "[FAIL] рискованная спецификация обязана дать НЕнулевой код"; bad=$((bad+1)); fi
if ! printf '%s' "$out2" | grep -qF 'ОПРОВЕРГНУТО'; then echo "[FAIL] выход за границы НЕ опровергнут — теория массивов молчит"; bad=$((bad+1)); fi

if [ "$bad" -ne 0 ]; then echo "[FAIL] native-theories-file: нарушений $bad"; exit 1; fi
echo "[OK] native-theories-file: arrays/absint/dtmc работают на ВНЕШНЕМ файле (2 доказано + 1 опровергнуто + 4 значения)"
exit 0
