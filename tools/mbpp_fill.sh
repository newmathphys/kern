#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
#
# Устойчивое дозаполнение сэмплов MBPP+ при жёстких лимитах API (HTTP 429).
#
# Почему нужен цикл: внешний API отдаёт 429 после серии запросов. Генератор
# пишет ПУСТОЙ completion для упавших задач и больше их не повторяет, поэтому
# между проходами пустые записи удаляются (tools/mbpp_retry.py), а следующий
# проход дозаполняет только недостающие.
#
# Использование:  ./tools/mbpp_fill.sh <out.jsonl> [max_passes] [workers]
set -uo pipefail
OUT="${1:-samples_mbpp.jsonl}"
PASSES="${2:-40}"
WORKERS="${3:-4}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${HERE}/../.venv-evalplus/bin/python"
[ -x "$PY" ] || PY=python3

count() { if [ -f "$1" ]; then wc -l < "$1" | tr -d ' '; else echo 0; fi; }

for i in $(seq 1 "$PASSES"); do
  python3 "${HERE}/mbpp_retry.py" "$OUT" >/dev/null 2>&1 || true
  n=$(count "$OUT")
  echo "[pass $i] валидных: $n / 378"
  if [ "$n" -ge 378 ]; then
    echo "[OK] все 378 сэмплов собраны"
    exit 0
  fi
  "$PY" "${HERE}/humaneval_api.py" --dataset mbpp \
      --model "${MODEL_NAME:?задайте MODEL_NAME}" \
      --out "$OUT" --workers "$WORKERS" --max-tokens 1024 >/dev/null 2>&1 || true
  sleep 45   # пауза, чтобы лимит API частично восстановился
done
echo "[i] достигнут лимит проходов; валидных: $(wc -l < "$OUT" 2>/dev/null || echo 0)"
