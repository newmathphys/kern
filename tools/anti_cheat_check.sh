#!/usr/bin/env bash
# ЭШЕЛОН 6, ПУНКТ 32: ПРИЁМКА АНТИ-ЧИТА.
# Требуется: ВСЕ 5 классов читов пойманы; чистый код с --import-lock проходит.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
OUT=$(timeout 300 "$PY" tools/kern_contracts.py --anti-cheat examples/anti_cheat_demo.py 2>&1)
echo "$OUT" | tail -8
fail() { echo "[!] $1"; exit 1; }
# ДЕФЕКТ #426: требование расширено с ЛИТЕРАЛЬНЫХ форм на СМЫСЛОВЫЕ ЭКВИВАЛЕНТЫ.
# ИЗМЕРЕНО до правки: буквальные формы ловились, а замаскированные двойники — нет
# (`setattr(C, "__eq__", …)`, `mod.fn = lambda …`, безусловный `pytest.skip`),
# поэтому гейт был ЗЕЛЁНЫМ при 3 из 5 пропущенных обходов.
for k in "always-true __eq__" "exit inside tested code" "swallowed assert" "mock in production" "test-case overfitting" \
         "dynamic dunder override (setattr)" "monkeypatch of imported module attribute" "unconditional skip inside a test"; do
  echo "$OUT" | grep -q "CHEAT DETECTED: .*$k" || fail "чит НЕ пойман: $k"
done
CLEAN=$(timeout 300 "$PY" tools/kern_contracts.py --anti-cheat examples/presets_demo.py \
  --import-lock examples/import_allowlist.json 2>&1)
echo "$CLEAN" | grep -q '\[OK\] чисто' || fail "чистый код ошибочно помечен"
echo "[OK] анти-чит: 5 классов + 3 ЗАМАСКИРОВАННЫХ двойника пойманы, чистый код проходит"
