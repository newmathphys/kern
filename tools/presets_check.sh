#!/usr/bin/env bash
# ЭШЕЛОН 5, ПУНКТ 26: ПРИЁМКА ОДНОСЛОВНЫХ ПРЕСЕТОВ.
# Требуется:
#   * PROVEN с trusted: 0 — non_negative, bounded, idempotent (ПУТЕВАЯ проверка),
#     monotonic;
#   * REFUTED — percentage (выход > 100), monotonic (обратная ступенька),
#     non_negative (отрицательный вход);
#   * НИ ОДНОГО [UNKNOWN]: нерешённое не выдаётся за доказанное;
#   * `--spec-gaps` находит неполные спецификации ([SPEC GAP]).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=${PYTHON:-python3}
# rc=1 здесь ОЖИДАЕМ (в фикстуре есть намеренно сломанные функции -> FAIL);
# rc>=2 означает настоящий сбой инструмента.
OUT=$(timeout 600 "$PY" tools/kern_contracts.py --presets examples/presets_demo.py 2>&1)
RC=$?
[ "$RC" -le 1 ] || { echo "[!] --presets упал (rc=$RC)"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -6

fail() { echo "[!] $1"; exit 1; }

echo "$OUT" | grep -q '\[PASS\] clamp_nonneg: non_negative PROVEN (trusted: 0' \
  || fail "non_negative не доказан на trusted: 0"
echo "$OUT" | grep -q '\[PASS\] discount: bounded(0, x) PROVEN (trusted: 0' \
  || fail "bounded(0, x) не доказан на trusted: 0"
echo "$OUT" | grep -q '\[PASS\] clamp_idem: idempotent PROVEN по всем' \
  || fail "idempotent не доказан по всем путям (trusted: 0)"
echo "$OUT" | grep -q '\[PASS\] tax_smooth: monotonic PROVEN (trusted: 0' \
  || fail "monotonic не доказан на trusted: 0"
echo "$OUT" | grep -q '\[FAIL\] pct_buggy: percentage REFUTED' \
  || fail "процент > 100 НЕ пойман"
echo "$OUT" | grep -q '\[FAIL\] tax_step: monotonic REFUTED' \
  || fail "обратная ступенька НЕ поймана"
echo "$OUT" | grep -q '\[FAIL\] price: non_negative REFUTED' \
  || fail "отрицательный результат НЕ пойман"
if echo "$OUT" | grep -q '\[UNKNOWN\]'; then
  fail "есть НЕрешённые обязательства — приёмка неполна"
fi

# `--spec-gaps` — ОТДЕЛЬНЫЙ режим: обязан находить неполные спецификации.
GAPS=$(timeout 300 "$PY" tools/kern_contracts.py --presets examples/presets_demo.py \
  --spec-gaps 2>&1)
N=$(echo "$GAPS" | grep -c '\[SPEC GAP\]' || true)
[ "$N" -ge 2 ] || fail "(--spec-gaps) неполные спецификации НЕ найдены (найдено $N)"

echo "[OK] пресеты: 4 PROVEN (trusted: 0) | 3 REFUTED | 0 unknown | SPEC GAP $N"
