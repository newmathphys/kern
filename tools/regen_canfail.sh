#!/usr/bin/env bash
# Дождаться окончания `make evidence`, затем ПЕРЕЗАПУСТИТЬ canfail на
# стабильном дереве и записать его свидетельство.
#
# ЗАЧЕМ. Прогон `make evidence` дал canfail RC=1 не из-за дефекта, а потому что
# во время него правился `tools/canfail.py` (дефект #88). Нужен чистый прогон
# при НЕИЗМЕНЯЕМОМ дереве.
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/opt/zig-x86_64-linux-0.17.0:$PWD/.venv/bin:$PATH"

# 1. Дождаться, пока collect_evidence.sh завершится.
while pgrep -f 'collect_evidence.sh' > /dev/null 2>&1; do sleep 5; done
# 2. Дождаться, пока не останется чужих canfail/mutate.
while pgrep -f 'tools/canfail.py' > /dev/null 2>&1; do sleep 5; done
sleep 3

# 3. Чистый прогон canfail с заголовком свидетельства.
LOG=docs/evidence/canfail.log
{
  echo "=== KERN EVIDENCE: canfail ==="
  echo "=== команда: python3 tools/canfail.py ==="
  echo "=== дата: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  echo
  python3 tools/canfail.py
  echo "RC=$?"
} > "$LOG" 2>&1
echo "DONE" >> /tmp/canfail_rerun.log
