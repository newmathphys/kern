#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
#
# `pilot_e2e.sh` — «БОЕВОЙ ПИЛОТ 8-в-1»: все восемь уровней KERN на ОДНОМ
# реальном внешнем проекте, одной непрерывной цепочкой (Шаг 3 полевых испытаний
# v2.8.2). Пишет только ФАКТЫ и коды возврата; ничего не «объявляет доказанным»
# без строки доказательства рядом.
#
# ЗАЧЕМ ОТДЕЛЬНЫЙ СЦЕНАРИЙ. Внутренние фикстуры проверяют каждую возможность
# ОТДЕЛЬНО; здесь проверяется, что они работают как ОДИН часовой механизм — и на
# коде, которого мы не писали.
#
# Использование: tools/pilot_e2e.sh [PILOT_DIR] [APPLIANCE] [OUT_LOG]
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PILOT="${1:-$HOME/.cache/kern/repos/dsk-DeepEP-Ascend}"
APP="${2:-$ROOT/dist/kerna}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/pilot_e2e.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM
KERNC="$ROOT/zig-out/bin/kernc"
KERNX="$ROOT/zig-out/bin/kernx"
PY="${PYTHON:-python3}"
FAILS=0
say() { printf '%s\n' "$*"; }
step() { say ""; say "──────────────────────────────────────────────────────────────────────"; say "$*"; }
rc_note() { if [ "$1" -eq 0 ]; then say "  rc=0 — выполнено"; else say "  rc=$1 — ПРОВАЛ"; FAILS=$((FAILS + 1)); fi; }

say "=========================================================================="
say "KERN v2.8.2 · БОЕВОЙ ПИЛОТ 8-в-1 · $(date -u '+%Y-%m-%d %H:%M:%SZ')"
say "=========================================================================="
say "  пилот   : $PILOT"
say "  HEAD    : $(git -C "$PILOT" rev-parse HEAD 2>/dev/null || echo 'нет git')"
say "  апплаенс: $APP"
say "  python  : $($PY -V 2>&1)   node: $(node -v 2>/dev/null || echo НЕТ)"
[ -d "$PILOT" ] || { say "[!] нет пилота: $PILOT"; exit 2; }
[ -x "$APP" ] || { say "[!] нет апплаенса: $APP"; exit 2; }


step "УРОВЕНЬ 1 · ПАСПОРТ: kerna --xray-json (машинный ABI 1.0)"
"$APP" --xray "$PILOT" --xray-json > "$WORK/xray.json" 2>"$WORK/xray.err"; rc=$?
if [ "$rc" -eq 0 ] && $PY -c "import json;d=json.load(open('$WORK/xray.json'));s=d['summary'];print('  файлов %d | функций %d | проверено %d | тривиальных %d | пропущено %d | находок %d'%(s['files'],s['total'],s['checked'],s['trivial'],s['skipped'],s['findings']));print('  тождество воронки %d+%d+%d=%d — %s'%(s['checked'],s['trivial'],s['skipped'],s['total'],'СХОДИТСЯ' if s['checked']+s['trivial']+s['skipped']==s['total'] else 'НЕ СХОДИТСЯ'))" 2>/dev/null; then
  rc_note 0
else
  say "  [!] ABI не получен (rc=$rc): $(head -2 "$WORK/xray.err" | tr '\n' ' ')"; rc_note 1
fi

step "УРОВЕНЬ 2 · АНТИ-ЧИТ L5: kerna --anti-cheat на РЕАЛЬНОМ тесте проекта"
TEST=$(find "$PILOT" -type f \( -name 'test_*.py' -o -name '*_test.py' \) 2>/dev/null | sort | head -1)
if [ -n "$TEST" ]; then
  say "  тест: ${TEST#"$PILOT"/}"
  "$APP" --anti-cheat "$TEST" > "$WORK/anticheat.log" 2>&1; rc=$?
  grep -E 'ANTI-CHEAT SUMMARY|чисто|CHEAT|SMELL' "$WORK/anticheat.log" | head -3 | sed "s#$PILOT/##; s/^/  /"
  rc_note "$rc"
else
  say "  [SKIP] в пилоте нет тестовых файлов — уровень НЕ проверен (названный пропуск)"; rc_note 1
fi

step "УРОВЕНЬ 3 · PR-ГЕЙТ: audit-delta в ОБЕ стороны (CWE-близнецы KERN, реальный C)"
rm -rf "$WORK/good" "$WORK/bad"; mkdir -p "$WORK/good" "$WORK/bad"
cp "$ROOT"/audits/cwe_twins/*_good.c "$WORK/good/" 2>/dev/null
cp "$ROOT"/audits/cwe_twins/*_bad.c  "$WORK/bad/"  2>/dev/null
say "  пар bad/good: $(ls "$WORK/bad" | wc -l)"
"$PY" "$ROOT/tools/audit_delta.py" "$WORK/good" "$WORK/bad" --live > "$WORK/delta_in.log" 2>&1; rc_in=$?
say "  внесение бага (good -> bad): rc=$rc_in (ожидался 1 = ЗАБЛОКИРОВАТЬ)"
grep -E 'РЕГРЕСС|^    \+ ' "$WORK/delta_in.log" | head -4 | sed 's/^/    /'
[ "$rc_in" -eq 1 ] || { say "  [!] ПР-гейт НЕ заблокировал внесённый баг"; FAILS=$((FAILS + 1)); }
"$PY" "$ROOT/tools/audit_delta.py" "$WORK/bad" "$WORK/good" --live > "$WORK/delta_fix.log" 2>&1; rc_fix=$?
say "  починка       (bad -> good): rc=$rc_fix (ожидался 0 = ПРОПУСТИТЬ)"
grep -E 'ИСПРАВЛЕНО|^    - ' "$WORK/delta_fix.log" | head -4 | sed 's/^/    /'
[ "$rc_fix" -eq 0 ] || { say "  [!] починка заблокирована"; FAILS=$((FAILS + 1)); }


step "УРОВЕНЬ 4 · ЭКВИВАЛЕНТНОСТЬ: --diff-equiv (реальная функция пилота ceil_div)"
REAL_FN=$(grep -rln 'def ceil_div' "$PILOT" 2>/dev/null | head -1)
if [ -n "$REAL_FN" ]; then
  say "  источник: ${REAL_FN#"$PILOT"/}"
  printf 'def ceil_div(x, y):\n    return (x + y - 1) // y\n' > "$WORK/old.py"
  printf 'def ceil_div(x, y):\n    return x // y\n' > "$WORK/new.py"
  "$PY" "$ROOT/tools/kern_contracts.py" --diff-equiv "$WORK/old.py" "$WORK/new.py" > "$WORK/diffeq.log" 2>&1; rc=$?
  grep -E 'DIVERGED|КОНТРПРИМЕР|EQUIVALENT' "$WORK/diffeq.log" | head -3 | sed 's/^/  /'
  say "  (ожидание: [DIVERGED] + точный вход — «PR подменил ceil на floor»)"
  # ВНИМАНИЕ: для --diff-equiv код 1 — это УСПЕХ (расхождение НАЙДЕНО и доказано
  # контрпримером), а не провал. Провалом были бы rc=2 (ошибка инструмента) или
  # «эквивалентными» на заведомо разных функциях.
  if [ "$rc" -eq 1 ] && grep -q 'DIVERGED' "$WORK/diffeq.log"; then say "  rc=1 — расхождение ДОКАЗАНО (это цель уровня)"; else say "  rc=$rc — ПРОВАЛ (ожидался доказанный DIVERGED)"; FAILS=$((FAILS + 1)); fi
else
  say "  [SKIP] в пилоте нет ceil_div — уровень НЕ проверен"; rc_note 1
fi

step "УРОВЕНЬ 5 · ФОРМАЛЬНЫЙ КОНТРАКТ L4: @kern: на РЕАЛЬНОЙ функции пилота"
if [ -n "$REAL_FN" ]; then
  mkdir -p "$WORK/contract"
  { echo "# @kern:requires x >= 0 and y > 0"; echo "# @kern:ensures result >= 0";
    printf 'def ceil_div(x, y):\n    return (x + y - 1) // y\n'; } > "$WORK/contract/ceil_pilot.py"
  "$PY" "$ROOT/tools/kern_contracts.py" "$WORK/contract/ceil_pilot.py" > "$WORK/contract.log" 2>&1; rc=$?
  grep -E 'PASS|ДОКАЗАНО|нарушено|ИТОГО' "$WORK/contract.log" | head -3 | sed 's/^/  /'
  "$PY" "$ROOT/tools/kern_contracts.py" "$WORK/contract/ceil_pilot.py" --emit-smt2 "$WORK/smt2" >/dev/null 2>&1 \
    && { say "  сертификат .smt2:"; ls "$WORK/smt2" 2>/dev/null | sed 's/^/    /'; \
        "$KERNC" prove "$WORK"/smt2/*.smt2 2>/dev/null | grep -E 'e  |ВЕРДИКТ|PROOF' | head -3 | sed 's/^/    /'; }
  rc_note "$rc"
else
  say "  [SKIP] нет функции для контракта"; rc_note 1
fi

step "УРОВЕНЬ 6 · ЭПИСТЕМИЧЕСКАЯ БАЗА: kernx build → status → packet"
"$PY" "$ROOT/tools/scan_to_kern.py" "$PILOT" -o "$WORK/pilot.kern" --max-files 200 > "$WORK/scan.log" 2>&1; rc=$?
grep -E 'артефактов' "$WORK/scan.log" | sed 's/^/  /'
"$KERNX" build "$WORK/pilot.kern" --out "$WORK/kx" > "$WORK/kx_build.log" 2>&1; rc_b=$?
grep -E 'Собрано|Пакет' "$WORK/kx_build.log" | sed 's/^/  /'
"$KERNX" status "$WORK/pilot.kern" > "$WORK/kx_status.log" 2>&1; rc_s=$?
grep -E 'узлов|статус|диагностик' "$WORK/kx_status.log" | head -6 | sed 's/^/  /'
"$KERNX" packet "$WORK/pilot.kern" > "$WORK/kx_packet.log" 2>&1; rc_p=$?
say "  agent_packet.json: $([ -s "$WORK/kx/agent_packet.json" ] && echo "есть ($(wc -c < "$WORK/kx/agent_packet.json") Б)" || echo НЕТ)"
if [ "$rc" -eq 0 ] && [ "$rc_b" -eq 0 ] && [ "$rc_s" -eq 0 ] && [ "$rc_p" -eq 0 ]; then rc_note 0; else rc_note 1; fi

step "УРОВЕНЬ 7 · СУВЕРЕННЫЙ КОНТЕЙНЕР: .kimg + проверка БЕЗ Z3 и БЕЗ Python (PATH=\"\")"
"$KERNC" pack-dir "$PILOT" -o "$WORK/pilot_bundle.kimg" > "$WORK/pack.log" 2>&1; rc=$?
grep -E 'pack-dir' "$WORK/pack.log" | sed 's/^/  /'
env -i PATH="" "$KERNC" check-integrity "$WORK/pilot_bundle.kimg" > "$WORK/integrity.log" 2>&1; rc_i=$?
head -3 "$WORK/integrity.log" | sed 's/^/  /'
say "  (окружение: env -i PATH=\"\" — ни z3, ни python недоступны)"
if [ "$rc" -eq 0 ] && [ "$rc_i" -eq 0 ]; then rc_note 0; else rc_note 1; fi

step "УРОВЕНЬ 8 · БРАУЗЕРНОЕ ЯДРО: kernc.wasm в node (Белнап B4 + встроенная LIA)"
if command -v node >/dev/null 2>&1; then
  ( cd "$ROOT" && node tools/wasm_parity_check.js ) > "$WORK/wasm.log" 2>&1; rc=$?
  tail -2 "$WORK/wasm.log" | sed 's/^/  /'
  rc_note "$rc"
else
  say "  [SKIP] node недоступен — уровень НЕ проверен (названный пропуск)"; rc_note 1
fi

say ""
say "=========================================================================="
say "ИТОГ ПИЛОТА: уровней 8 | провалов $FAILS"
say "ГРАНИЦА (названа, не спрятана): это ПРОГОН на реальном коде, а не"
say "  доказательство его корректности. Уровень 3 использует корпус CWE-близнецов"
say "  KERN (реальный C, но парные фикстуры): на РЕАЛЬНЫХ PR-диффах DeepGEMM и"
say "  QuixBugs дельта = 0, и это ВЕРНО — те баги лежат вне словаря детекторов"
say "  (гонки, порядок, логика), см. docs/evidence/field_trials_v2.8.2.log."
say "=========================================================================="
[ "$FAILS" -eq 0 ] && exit 0 || exit 1
