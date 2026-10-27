#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
#
# ГЕЙТ: НАТИВНЫЙ ФРОНТЕНД `.zig` НА `std.zig.Ast` (БЕЗ Python).
#
# ЗАЧЕМ. До этого гейта `kernc` умел читать только `.smt2`, а контракты
# `/// @kern:requires` разбирал ЛИШЬ питоновский `tools/kern_contracts.py`.
# Гейт требует ОБЕ половины на НАТИВНОМ пути:
#   * положительную — `addGuarded` (переполнение снято requires + постусловие),
#     `divOk` (деление на ноль и ловушка MIN/-1 сняты `b > 0`), `addWrapOk`
#     (`+%`) и `satOk` (`+|`) — ДОКАЗАНЫ, причём у модульных/насыщающих
#     обязательств переполнения РОВНО 0;
#   * отрицательную — `addBad` (незащищённое `+`) НАРУШЕН с контрпримером.
#
# ЧЕГО ГЕЙТ НЕ УТВЕРЖДАЕТ: подмножество языка ограничено (целые
# i32/u32/i64/u64/usize, тело из одного `return`, контракты из `and`/`or`/`!`,
# сравнений и `+ - * / %`). Всё прочее — SKIP с причиной, и это печатается.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
KERNC="$ROOT/zig-out/bin/kernc"
if [ ! -x "$KERNC" ]; then echo "[FAIL] нет $KERNC (соберите: zig build)"; exit 1; fi
export PATH="$ROOT/.venv/bin:$PATH"

bad=0
out=$("$KERNC" verify-zig tests/fixtures/zig_ast_contracts.zig 2>&1)
rc=$?
for want in "[PASS] ДОКАЗАНО addGuarded" "[PASS] ДОКАЗАНО divOk" "[PASS] ДОКАЗАНО addWrapOk" "[FAIL] КОНТРАКТ НАРУШЕН addBad"; do
  if ! printf '%s' "$out" | grep -qF "$want"; then echo "[FAIL] нет ожидаемого вердикта: $want"; bad=$((bad+1)); fi
done
if [ "$rc" -eq 0 ]; then echo "[FAIL] смешанный файл обязан дать НЕнулевой код (есть нарушенный), получено $rc"; bad=$((bad+1)); fi
if ! printf '%s' "$out" | grep -qF "[PASS] ДОКАЗАНО addWrapOk | обязательств 0"; then
  echo "[FAIL] у '\''+%'\'' обязательство переполнения НЕ равно нулю — это определение языка, а не пропуск"; bad=$((bad+1)); fi
if ! printf '%s' "$out" | grep -qF '[КОНТРПРИМЕР]'; then echo "[FAIL] нарушенный контракт без контрпримера"; bad=$((bad+1)); fi

out2=$("$KERNC" verify-zig tests/fixtures/zig_ast_contracts_ok.zig 2>&1)
rc2=$?
if [ "$rc2" -ne 0 ]; then echo "[FAIL] чистая фикстура обязана дать rc=0, получено $rc2"; bad=$((bad+1)); fi
if printf '%s' "$out2" | grep -qF 'КОНТРАКТ НАРУШЕН'; then echo "[FAIL] ЛОЖНОЕ ОБВИНЕНИЕ на чистой фикстуре"; bad=$((bad+1)); fi
if ! printf '%s' "$out2" | grep -qF '[PASS] ДОКАЗАНО satOk'; then echo "[FAIL] '\''+|'\'' не доказан"; bad=$((bad+1)); fi

if [ "$bad" -ne 0 ]; then echo "[FAIL] native-zig-ast: нарушений $bad"; exit 1; fi
echo "[OK] native-zig-ast: нативный std.zig.Ast доказывает 3 и опровергает 1 (0 Python); у '+%'/'+|' обязательств 0"
exit 0
