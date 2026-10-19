#!/usr/bin/env bash
# ЭШЕЛОН 7, ПУНКТ 37: ПРИЁМКА ДЕТЕКТОРА ПРОТИВОРЕЧИЙ В ДОКУМЕНТАХ.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY=${PYTHON:-python3}
fail() { echo "[!] $1"; exit 1; }
A=$(timeout 300 "$PY" tools/kern_contracts.py --verify-doc examples/doc_consistent.json 2>&1)
echo "$A" | grep -q 'DOCUMENT CONSISTENT' || fail "непротиворечивый документ НЕ принят"
B=$(timeout 300 "$PY" tools/kern_contracts.py --verify-doc examples/doc_conflict.json 2>&1)
echo "$B" | grep -q 'CONFLICT B(1,1)' || fail "противоречие НЕ найдено"
echo "$B" | grep -q 'Minimal conflicting clauses' || fail "ядро конфликта НЕ названо"
echo "$B" | grep -q 'clause_1' || fail "ядро не содержит пунктов"
echo "[OK] RAG: документ непротиворечив ИЛИ найдено ядро конфликтующих пунктов"
