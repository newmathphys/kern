#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. PolyForm Noncommercial License 1.0.0.
#
# СКВОЗНОЙ СТЕНД «KERN против ИИ» (`make ai-demo`).
#
# Три акта на одном экране, всё — реальный вывод инструментов:
#   1) что видит обычный CI (pytest зелёный на тестах, которые не могут упасть);
#   2) что находит KERN в том же коде (чит, дыра в контракте, арбитраж,
#      регрессия «улучшения», инъекция в MCP-схеме, опасный вызов агента);
#   3) как KERN лечит, доказывает (`trusted: 0`) и открывает ворота (`e = 1`).
#
# Приёмка: скрипт сам проверяет, что каждая ожидаемая строка реально появилась.
# Если инструмент перестал ловить обман — `make ai-demo` падает (rc=1), а не
# печатает красивую ложь. Фикстуры лежат в `examples/ai_vs_kern/`.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=${PYTHON:-python3}
EX=${KERNC_EXTRACTOR:-tools/kern_contracts.py}
FIX="examples/ai_vs_kern"
fail=0

# pytest может стоять в отдельном venv, а не в системном python
# (тот же класс, что Дефект #110: окружение ≠ код). Ищем сами; если нигде
# нет — акт 1 честно помечается [SKIP], а не засчитывается ни в OK, ни в FAIL.
PYTEST_OK=0
if "$PY" -c 'import pytest' >/dev/null 2>&1; then
  PYTEST_OK=1
else
  for c in "$HOME/ai_lab/.venv/bin/python" "$ROOT/.venv/bin/python" \
           "$ROOT/.venv-evalplus/bin/python"; do
    if [ -x "$c" ] && "$c" -c 'import pytest' >/dev/null 2>&1; then
      PY="$c"; PATH="$(dirname "$c"):$PATH"; PYTEST_OK=1; break
    fi
  done
fi
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
note() { printf '   %s\n' "$1"; }
expect() {  # expect <описание> <подстрока> <вывод>
  if printf '%s' "$3" | grep -qF -- "$2"; then
    printf '   \033[32m[OK]\033[0m %s\n' "$1"
  else
    printf '   \033[31m[FAIL]\033[0m %s (не найдено: %s)\n' "$1" "$2"
    fail=1
  fi
}

printf '============================================================\n'
printf ' KERN vs AI: что видит CI и что видит KERN\n'
printf '============================================================\n'
if ! command -v z3 >/dev/null 2>&1; then
  for c in "$HOME/ai_lab/.venv/bin/z3" "$HOME/.local/bin/z3" /usr/bin/z3; do
    [ -x "$c" ] && PATH="$(dirname "$c"):$PATH" && break
  done
fi
command -v z3 >/dev/null 2>&1 \
  || { echo "[!] z3 не найден в PATH — акты 2.2/2.3/3 требуют решатель"; exit 2; }

step 'АКТ 1. ИИ написал код и тесты. Обычный CI — зелёный.'
if [ "$PYTEST_OK" -eq 1 ]; then
  echo "  \$ pytest -q $FIX/test_ai_generated.py"
  PYTEST_OUT=$("$PY" -m pytest -q "$FIX/test_ai_generated.py" 2>&1 | tail -2)
  echo "$PYTEST_OUT" | sed 's/^/  /'
  note 'Оба теста не могут упасть: в первом нет assert, во втором assert проглочен.'
  note '«2 passed» — это не про корректность, это про отсутствие проверок.'
  expect 'pytest отчитался «passed»' 'passed' "$PYTEST_OUT"
else
  printf '   \033[33m[SKIP]\033[0m pytest не найден ни в одном окружении — акт 1 не проверен\n'
  note 'Это не «зелёный результат»: акт 1 остаётся НЕ подтверждённым.'
fi

step 'АКТ 2. KERN вскрывает обман в том же коде.'

echo
echo ' [2.1] Чит в тестах агента (--anti-cheat)'
echo "  \$ kern_contracts.py --anti-cheat $FIX/test_ai_generated.py"
CHEAT=$(timeout 300 "$PY" "$EX" --anti-cheat "$FIX/test_ai_generated.py" 2>&1)
echo "$CHEAT" | grep -E 'CHEAT DETECTED|ANTI-CHEAT SUMMARY' | sed 's/^/  /'
expect 'найден проглоченный assert' 'CHEAT DETECTED: swallowed assert' "$CHEAT"
RLVR_BAD=$(timeout 300 "$PY" "$EX" --rlvr-reward "$FIX/test_ai_generated.py" 2>&1)
echo "$RLVR_BAD" | grep '\[REWARD\]' | sed 's/^/  /'
expect 'оракул обучения оштрафовал чит' 'R=-2.0' "$RLVR_BAD"

echo
echo ' [2.2] Дыра в логике: контракт агента нарушен (Z3 + живой вызов)'
echo "  \$ kern_contracts.py $FIX/ai_generated.py"
CONTR=$(timeout 600 "$PY" "$EX" "$FIX/ai_generated.py" 2>&1)
echo "$CONTR" | grep -E '\[FAIL\]|\[КОНТРПРИМЕР\]|\[RUNTIME CONFIRMED\]|ИТОГО' | sed 's/^/  /'
expect 'найдено 2 нарушения' 'нарушено 2' "$CONTR"
expect 'контрпример подтверждён рантаймом' '[RUNTIME CONFIRMED]' "$CONTR"
expect 'ложных тревог нет' 'ЛОЖНЫХ ТРЕВОГ 0' "$CONTR"

echo
echo ' [2.3] Финансовый арбитраж: комиссию обходят дроблением платежа'
echo "  \$ kern_contracts.py --presets $FIX/fees.py"
ARB=$(timeout 300 "$PY" "$EX" --presets "$FIX/fees.py" 2>&1)
echo "$ARB" | grep -E '\[FAIL\]|\[PASS\]|PRESETS SUMMARY' | sed 's/^/  /'
expect 'арбитраж пойман контрпримером' 'fee_threshold: no_arbitrage REFUTED' "$ARB"
expect 'субаддитивная комиссия доказана' 'fee_proportional: no_arbitrage PROVEN (trusted: 0' "$ARB"

echo
echo ' [2.4] «Улучшение» агента изменило поведение на границе'
echo "  \$ kern_contracts.py --diff-equiv $FIX/refactor_before.py $FIX/refactor_after.py"
DEQ=$(timeout 300 "$PY" "$EX" --diff-equiv "$FIX/refactor_before.py" "$FIX/refactor_after.py" 2>&1)
echo "$DEQ" | grep -E '\[DIVERGED\]|\[КОНТРПРИМЕР\]|ИТОГО' | sed 's/^/  /'
expect 'расхождение доказано контрпримером' '[DIVERGED] charge' "$DEQ"

echo
echo ' [2.5] MCP-схема с промпт-инъекцией и невидимым Unicode'
echo "  \$ kern_contracts.py --audit-mcp examples/mcp_schema_poisoned.json"
MCP=$(timeout 300 "$PY" "$EX" --audit-mcp examples/mcp_schema_poisoned.json 2>&1)
echo "$MCP" | grep -E 'PROMPT INJECTION|INVISIBLE UNICODE|MCP SUMMARY' | sed 's/^/  /'
expect 'инъекция найдена' 'PROMPT INJECTION' "$MCP"
expect 'невидимый символ найден' 'INVISIBLE UNICODE' "$MCP"

echo
echo ' [2.6] Действие агента до вызова API (FinOps / Action Firewall)'
echo "  \$ kern_contracts.py --verify-action examples/action_conflict.json examples/policy_conflict.json"
FW=$(timeout 300 "$PY" "$EX" --verify-action examples/action_conflict.json examples/policy_conflict.json 2>&1)
echo "$FW" | grep -E '\[FAIL\]|\[PASS\]' | sed 's/^/  /'
expect 'конфликт политик даёт 409' '409 Conflict' "$FW"

step 'АКТ 3. KERN лечит, доказывает и открывает ворота (e = 1).'

echo
echo ' [3.1] Авто-хирург: краш устранён, патч перепроверен, бэкап сохранён'
TMPD=$(mktemp -d)
TMP="$TMPD/crash.py"
cp "$FIX/ai_crash.py" "$TMP"
echo "  \$ coreutils cp $FIX/ai_crash.py <tmp> && kern_contracts.py --heal <tmp>"
HEAL=$(timeout 300 "$PY" "$EX" --heal "$TMP" 2>&1)
echo "$HEAL" | grep -E '\[HEAL\]' | sed 's/^/  /'
expect 'краш найден и устранён' '[HEAL] найдено крашей: 1 | после патча: 0' "$HEAL"
expect 'патч доказан (Belnap T, e=1)' '[T (1,0)] файл вылечен' "$HEAL"
if [ -f "$TMP.bak" ]; then
  printf '   \033[32m[OK]\033[0m бэкап оригинала сохранён (.bak)\n'
else
  printf '   \033[31m[FAIL]\033[0m бэкап не создан\n'
  fail=1
fi
rm -rf "$TMPD"

echo
echo ' [3.2] Исправленный код: математический допуск (PROVEN, trusted: 0 | holes: 0)'
echo "  \$ kern_contracts.py $FIX/fixed.py"
PROOF=$(timeout 600 "$PY" "$EX" "$FIX/fixed.py" 2>&1)
echo "$PROOF" | grep -E '\[PASS\]|PROOF VERIFIED|ИТОГО' | sed 's/^/  /'
expect 'контракт доказан' '[PASS] transfer_with_fee: ДОКАЗАНО' "$PROOF"
expect 'ни одного доверенного шага' 'trusted: 0 | holes: 0' "$PROOF"
expect 'ложных тревог нет' 'ЛОЖНЫХ ТРЕВОГ 0' "$PROOF"

echo
echo ' [3.3] Верифицируемый оракул: награда только за доказанный и чистый код'
echo "  \$ kern_contracts.py --rlvr-reward $FIX/fixed.py"
RLVR_OK=$(timeout 300 "$PY" "$EX" --rlvr-reward "$FIX/fixed.py" 2>&1)
echo "$RLVR_OK" | grep '\[REWARD\]' | sed 's/^/  /'
expect 'оракул выдал +1.0' 'R=+1.0' "$RLVR_OK"
expect 'ворота открыты (e=1)' 'e=1' "$RLVR_OK"

printf '\n============================================================\n'
if [ "$fail" -eq 0 ]; then
  printf ' ИТОГ: обман пойман, исправление доказано. Ворота открыты (e = 1)\n'
else
  printf ' ИТОГ: ЕСТЬ ПРОВАЛЫ — демонстрация НЕВАЛИДНА (см. FAIL выше)\n'
fi
printf '============================================================\n'
exit "$fail"

