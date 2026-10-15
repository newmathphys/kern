#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
#
# KERN: smoke-тест Guardrail-прокси. ПРОВЕРЯЕТ коды ответов и ПАДАЕТ при
# неверных. Раньше Makefile-цель только печатала коды — то есть не могла
# упасть (вакуумная проверка; найдено can-fail кейсом `guardrail-verdict`).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${GUARDRAIL_PORT:-8733}"
FAIL=0

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
check() { # $1 = имя, $2 = ожидаем, $3 = факт
  if [ "$2" = "$3" ]; then printf '  [OK]   %-22s HTTP %s\n' "$1" "$3"
  else printf '  [ПРОВАЛ] %-20s ждали %s, получили %s\n' "$1" "$2" "$3"; FAIL=1; fi
}

python3 examples/guardrail_proxy.py --port "$PORT" >/tmp/kern_guardrail_smoke.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT
for _ in $(seq 1 30); do code "localhost:$PORT/health" >/dev/null 2>&1 && break; sleep 0.3; done

echo "=== KERN Guardrail smoke (порт $PORT) ==="
check "health"  "200" "$(code localhost:$PORT/health)"
check "баг"     "409" "$(code -X POST localhost:$PORT/verify -d '{"label":"buggy"}')"
check "доказано" "200" "$(code -X POST localhost:$PORT/verify \
  -d '{"smt":"(set-logic QF_LIA)(declare-const x Int)(assert (> x 10))(assert (< x 5))(check-sat)"}')"

if [ "$FAIL" -ne 0 ]; then echo "ПРОВАЛ: прокси не различает вердикты"; exit 1; fi
echo "ВСЁ ПРОЙДЕНО: 409 для опровергнутого, 200 для доказанного"
