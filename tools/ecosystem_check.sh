#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
#
# ЭКОСИСТЕМНАЯ ПРИЁМКА (внешние каталоги MCP + AI-краулеры + Code Scanning).
#
# ЗАЧЕМ. Внешние сканеры (m8ven.ai, Smithery, Glama, Official MCP Registry)
# читают ДЕКЛАРАТИВНЫЕ манифесты, а не код. Проверяем, что манифесты не
# «нарисованы», а ГЕНЕРИРУЮТСЯ из сервера и совпадают с ним байт-в-байт,
# лицензия консистентна с LICENSE, llms.txt на месте, а SARIF валиден.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0

ok()   { printf '  [OK] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }

echo "== 1) манифесты MCP == код (генератор + --check) =="
if python3 tools/gen_mcp_manifests.py --check; then ok "server.json / mcp.json / .well-known/mcp.json / glama.json + smithery.yaml синхронны с tools/list"; else bad "манифесты расходятся с examples/kern_mcp_server.py"; fi

echo "== 2) llms.txt (стандарт llmstxt.org) =="
[ -s llms.txt ] && ok "llms.txt ($(wc -c < llms.txt) Б)" || bad "нет llms.txt"
cmp -s llms.txt docs/llms.txt && ok "docs/llms.txt идентичен корневому (раздаётся Pages)" || bad "docs/llms.txt расходится с llms.txt"

echo "== 3) action.yml (GitHub Marketplace, режим xray) =="
if python3 - <<'PY'
import yaml
d = yaml.safe_load(open('action.yml', encoding='utf-8'))
assert d['inputs']['version']['default'] == 'v2.5.0', d['inputs']['version']
assert d['inputs']['mode']['default'] == 'verify'
assert 'sarif-file' in d['outputs'], list(d['outputs'])
assert any('sha256sum -c' in str(s.get('run', '')) for s in d['runs']['steps']), 'нет проверки SHA256'
print('  [OK] action.yml: version=v2.5.0, mode=xray|verify, sha256-проверка, sarif-file-выход')
PY
then :; else bad "action.yml невалиден или потерял sha256/mode/sarif"; fi

echo "== 4) обязательные файлы экосистемы =="
for f in CITATION.cff SECURITY.md server.json mcp.json .well-known/mcp.json glama.json smithery.yaml mcp.lock.json; do
  [ -s "$f" ] && ok "$f" || bad "нет/пуст $f"
done

echo "== 4b) замок MCP: mcp.lock.json == server.json (rug-pull) =="
if python3 tools/kern_contracts.py --audit-mcp server.json --mcp-lock mcp.lock.json >/tmp/kern_mcp_lock.log 2>&1; then
  ok "mcp.lock.json сверен: $(python3 -c "import json;print(len(json.load(open('mcp.lock.json'))['tools']))") инструментов, 0 rug-pull"
else
  bad "mcp.lock.json не совпал со схемой (rug-pull / инъекция) — см. /tmp/kern_mcp_lock.log"
fi

echo "== 5) SARIF 2.1.0 (GitHub Code Scanning) =="
# ВАЖНО: `kern_contracts.py` возвращает 1, когда НАШЁЛ нарушения (демо намеренно
# сломано) — это ожидаемый код, а не сбой. Поэтому rc не проверяем «на ноль»,
# а проверяем САМ ФАКТ генерации и валидность структуры.
python3 tools/kern_contracts.py examples/contracts_demo.py --sarif /tmp/kern_eco.sarif >/dev/null 2>&1
rc_gen=$?
if [ -s /tmp/kern_eco.sarif ] && python3 tools/check_sarif.py /tmp/kern_eco.sarif >/dev/null 2>&1; then
  ok "SARIF валиден (генератор rc=$rc_gen: 1 = нарушения найдены, это норма): $(python3 -c "import json;d=json.load(open('/tmp/kern_eco.sarif'));print(len(d['runs'][0]['results']),'находок,',len(d['runs'][0]['tool']['driver']['rules']),'правил')")"
else
  bad "SARIF не сгенерирован или невалиден"
fi

echo "== 6) страж дубликатов определений (дефект #174: ratchet) =="
if python3 tools/dup_defs_guard.py; then ok "долг дубликатов не вырос"; else bad "появился новый дублирующийся def (правка в первой копии молча не работает)"; fi

echo "== 7) страж диапазона реестра (дефект #221: повтор класса #178) =="
MAXNUM=$(grep -oE '^\| \*\*[0-9]+\*\* \|' docs/CAPABILITY_STATUS.md | grep -oE '[0-9]+' | sort -n | tail -1)
RANGE_BAD=0
for f in README.md README.ru.md docs/index.html docs/README.md; do
  for got in $(grep -oE '#1[–-]#[0-9]{2,3}' "$f" | grep -oE '[0-9]+$' | sort -u); do
    if [ "$got" != "$MAXNUM" ]; then
      echo "  [FAIL] $f: диапазон #1–#$got, а максимум реестра #$MAXNUM"
      RANGE_BAD=1
    fi
  done
done
if [ "$RANGE_BAD" -eq 0 ]; then ok "диапазоны #1–#$MAXNUM в README/сайте совпадают с реестром"; else bad "диапазон реестра на витрине отстал от факта"; fi

echo "== 8) страж лицензионной согласованности (дефект #222: LICENSE + манифесты) =="
if python3 tools/check_license_consistency.py; then ok "лицензия согласована (LICENSE == server.json == CITATION.cff)"; else bad "лицензия в манифестах расходится с LICENSE"; fi

echo "== 9) страж счётчика теорем Lean 4 (дефект #223) =="
if python3 tools/check_lean_counter.py; then ok "счётчик теорем Lean 4 на витрине совпадает с formal/*.lean"; else bad "счётчик теорем Lean 4 на витрине отстал"; fi

echo "----------------------------------------------------------------------"
if [ "$fail" -eq 0 ]; then
  echo "[OK] ecosystem-check: манифесты, llms.txt, action.yml, SARIF, ratchet — всё сходится"
else
  echo "[FAIL] ecosystem-check: есть расхождения (см. выше)"
fi
exit "$fail"
