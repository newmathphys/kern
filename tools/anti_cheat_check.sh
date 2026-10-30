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
# ДЕФЕКТ #426: гейт требует ОБЕ формы каждого приёма — ЛИТЕРАЛЬНУЮ и ЗАМАСКИРОВАННУЮ
# (соседнюю). ИЗМЕРЕНО до правки: буквальные формы ловились, а замаскированные — нет,
# поэтому гейт был ЗЕЛЁНЫМ при 3 из 5 пропущенных обходов рецензента.
for k in "always-true __eq__" "exit inside tested code" "swallowed assert" "mock in production" "test-case overfitting" \
         "dynamic dunder override (setattr)" "dynamic dunder override (assign)" \
         "monkeypatch of imported module attribute" "monkeypatch via setattr" \
         "unconditional skip inside a test" "test skipped by raise" "test disabled by a decorator"; do
  echo "$OUT" | grep -q "CHEAT DETECTED: .*$k" || fail "чит НЕ пойман: $k"
done

# ДВУСТОРОННИЙ КОНТРОЛЬ (дефект #426): на ЧЕСТНОМ файле находок быть НЕ ДОЛЖНО.
# Фикстура содержит формы, которые новое правило МОГЛО БЫ задеть, но не должно:
# `self.balance = 100` (setUp), `cfg.timeout = 30` (не функция), модульный
# `sys.exit(main())`, условный `@pytest.mark.skipif(sys.platform == "win32")`.
HONEST=$(timeout 300 "$PY" tools/kern_contracts.py --anti-cheat tests/fixtures/anti_cheat_honest.py 2>&1)
echo "$HONEST" | grep -q '\[OK\] чисто' || fail "ЧЕСТНЫЙ файл обвинён: $(echo "$HONEST" | grep 'CHEAT DETECTED' | head -2)"

# ДЕФЕКТ #427: неверный вход обязан быть отвергнут НАЗВАННОЙ ошибкой, без трейсбека.
DIR_OUT=$(timeout 300 "$PY" tools/kern_contracts.py --anti-cheat examples 2>&1)
DIR_RC=$?
if [ "$DIR_RC" = 0 ]; then fail "--anti-cheat на КАТАЛОГЕ вернул rc=0"; fi
if echo "$DIR_OUT" | grep -q 'Traceback'; then fail "--anti-cheat на КАТАЛОГЕ печатает Traceback"; fi
echo "$DIR_OUT" | grep -q 'ожидает ФАЙЛ' || fail "--anti-cheat на КАТАЛОГЕ не назвал причину"
CLEAN=$(timeout 300 "$PY" tools/kern_contracts.py --anti-cheat examples/presets_demo.py \
  --import-lock examples/import_allowlist.json 2>&1)
echo "$CLEAN" | grep -q '\[OK\] чисто' || fail "чистый код ошибочно помечен"
echo "[OK] анти-чит: 5 классов + 7 замаскированных/соседних форм пойманы; честный файл НЕ обвинён; каталог отвергнут без Traceback"
