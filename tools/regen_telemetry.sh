#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# Перегенерация ОДНОГО свидетельства: телеметрия (tools/measure_all_kern.py).
# Запускается в фоне, чтобы не упираться в лимит длительности команды.
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/opt/zig-x86_64-linux-0.17.0:$PWD/.venv/bin:$PATH"
LOG=docs/evidence/telemetry.log
{
  echo "=== KERN EVIDENCE: telemetry ==="
  echo "=== команда: python3 tools/measure_all_kern.py --out telemetry_report.json ==="
  echo "=== дата: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  echo
  python3 tools/measure_all_kern.py --out telemetry_report.json
  echo "RC=$?"
} > "$LOG" 2>&1
