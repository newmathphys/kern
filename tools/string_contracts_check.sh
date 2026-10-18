#!/usr/bin/env bash
# ЭШЕЛОН 4, ПУНКТ 23: ПРИЁМКА СТРОКОВЫХ КОНТРАКТОВ (QF_S).
#
# Требуется ЧИСТЫЙ ноль доверенных шагов: `trusted: 0 | holes: 0`.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
F=tests/fixtures/qfs_sanitizer.smt2
[ -f "$F" ] || { echo "[!] нет фикстуры $F"; exit 1; }
OUT=$(timeout 120 ./zig-out/bin/kernc prove "$F" 2>&1) || { echo "[!] kernc prove упал"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | grep -E 'ПРУФ-ЧЕКЕР|PROOF VERIFIED' | head -2
echo "$OUT" | grep -q 'trusted: 0 | holes: 0' \
  || { echo "[!] НЕ чистый ноль: ожидалось trusted: 0 | holes: 0"; exit 1; }
echo "$OUT" | grep -q 'PROOF VERIFIED' || { echo "[!] нет [PROOF VERIFIED]"; exit 1; }
echo "[OK] QF_S строки: trusted: 0 | holes: 0 (iff-true/iff-false, де Морган, unitImpliesLit)"
