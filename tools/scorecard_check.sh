#!/usr/bin/env bash
# N2: рабочие файлы прогона живут в СВОЁМ каталоге, а не в общем /tmp
# (гонка двух прогонов уже портила вердикты). Каталог снимается по выходу.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/kern_work.XXXXXX")"; export WORK
trap 'rm -rf "$WORK"' EXIT INT TERM
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
#
# ПРИЁМКА TRUST SCORECARD: карточка на сайте обязана соответствовать фактам.
# Проверяем ПЕРЕСЧЁТ (не «на слово»): recompute -> пороги -> сверка с
# опубликованным docs/evidence/scorecard.json -> секция на сайте.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
ok()  { printf '  [OK] %s\n' "$1"; }
bad() { printf '  [FAIL] %s\n' "$1"; fail=1; }

TMP=$WORK/kern_scorecard_recheck.json
echo "== 1) пересчёт паспорта (8 языков + формальные метрики) =="
if python3 tools/trust_scorecard.py --repo . --json "$TMP" --quiet; then
  ok "пересчёт выполнен"
else
  bad "пересчёт упал"
fi

echo "== 2) пороги и состав =="
if python3 - "$TMP" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
w, f, mcp, m = d['what_we_read'], d['formal'], d['mcp'], d['metrics']
problems = []
if d['score'] < 95: problems.append(f"score={d['score']} < 95")
if d['grade'] not in ('A+', 'A'): problems.append(f"grade={d['grade']}")
if w['by_category']['zig'] <= 0: problems.append('не прочитан ни один .zig')
if f['lean_files'] < 8: problems.append(f"lean_files={f['lean_files']} < 8")
if f['sorry'] != 0: problems.append(f"sorry={f['sorry']}")
if mcp['tools'] != 8: problems.append(f"mcp tools={mcp['tools']} != 8")
if not mcp['annotations']: problems.append('нет tool annotations')
if m['check_targets'] == 0 or m['check_covered'] != m['check_targets']:
    problems.append(f"can-fail {m['check_covered']}/{m['check_targets']}")
if problems:
    print('  [FAIL] ' + '; '.join(problems)); sys.exit(1)
print(f"  [OK] score={d['score']} grade={d['grade']} · .zig={w['by_category']['zig']} "
      f".lean={w['by_category']['lean']} · Lean {f['theorems']} теорем, sorry=0 · "
      f"MCP {mcp['tools']}/8 · can-fail {m['check_covered']}/{m['check_targets']}")
PY
then :; else bad "пороги не выполнены"; fi

echo "== 3) опубликованный паспорт не устарел =="
if python3 - "$TMP" <<'PY'
import json, sys
from pathlib import Path
cur = json.load(open(sys.argv[1], encoding='utf-8'))
pub_path = Path('docs/evidence/scorecard.json')
if not pub_path.is_file():
    print('  [FAIL] нет docs/evidence/scorecard.json (сайт покажет «card unavailable»)')
    sys.exit(1)
pub = json.loads(pub_path.read_text(encoding='utf-8'))
bad = [k for k in ('score', 'grade') if pub.get(k) != cur.get(k)]
if pub.get('mcp', {}).get('tools') != cur['mcp']['tools']:
    bad.append('mcp.tools')
if pub.get('formal', {}).get('theorems') != cur['formal']['theorems']:
    bad.append('formal.theorems')
if pub.get('metrics', {}).get('check_covered') != cur['metrics']['check_covered']:
    bad.append('metrics.check_covered')
if pub.get('code_hash') != cur.get('code_hash'):
    bad.append('code_hash')
# ПРИМЕЧАНИЕ: `commit` НЕ сравнивается намеренно — карточка генерируется ДО
# коммита и всегда отставала бы на один (класс дефекта #87: артефакт хеширует
# сам себя). Поле `commit` в паспорте — информационное («на каком коммите снят»).
if bad:
    print(f"  [FAIL] опубликованный scorecard устарел: {bad}")
    print('         перегенерируйте: python3 tools/trust_scorecard.py --json docs/evidence/scorecard.json')
    sys.exit(1)
print(f"  [OK] docs/evidence/scorecard.json совпадает с пересчётом "
      f"({pub['score']}/100, Grade {pub['grade']}, commit {pub.get('commit')})")
PY
then :; else bad "опубликованный паспорт расходится с фактами"; fi

echo "== 4) секция и кнопки на сайте =="
for needle in 'id="scorecard"' 'View raw JSON' 'Copy Markdown badge' 'Copy shareable link'; do
  if grep -q "$needle" docs/index.html; then ok "docs/index.html: $needle"; else bad "docs/index.html: нет $needle"; fi
done

echo "----------------------------------------------------------------------"
if [ "$fail" -eq 0 ]; then echo "[OK] scorecard-check: паспорт соответствует фактам"; else echo "[FAIL] scorecard-check: расхождения"; fi
exit "$fail"
