#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
#
# `build_kerna.sh` — сборка Zero-Dependency Appliance `kerna` (#494).
#
# ЧТО СОБИРАЕТСЯ. Один бинарник, который НЕ требует Python у клиента.
# Внутрь вшивается `server.json` (RESOURCE_ROOT), рядом кладутся `kernc` и `z3`
# (HOST_ROOT) — это ДВА РАЗНЫХ корня, см. tools/env_resolver.py.
#
# ЗАМЕР (спайк, ~/.cache/kern/kerna-spike): PyInstaller onefile → 9.8 МБ,
# старт 253 мс, сборка ~40 с. Nuitka → 9.6 МБ, 162 мс, но сборка ~9 мин и
# `sys.frozen` не выставляется (нужен `__compiled__`) — для 90 мс не окупается.
#
# Использование:
#   tools/build_kerna.sh [OUTDIR]        # по умолчанию dist/kerna
# Переменные: PYTHON (интерпретатор с pyinstaller), KERNA_NAME.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
OUT="${1:-$ROOT/dist}"
NAME="${KERNA_NAME:-kerna}"
PYTHON="${PYTHON:-python3}"

cd "$ROOT"

if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "[!] PyInstaller не установлен для $PYTHON" >&2
  echo "    uv pip install pyinstaller   (или: python3 -m venv .venv && .venv/bin/pip install pyinstaller)" >&2
  exit 3
fi

echo "[i] сборка $NAME из tools/kerna_main.py (onefile)"
rm -rf "$OUT"
mkdir -p "$ROOT/.build-kerna"
"$PYTHON" -m PyInstaller --onefile --noconfirm \
  --name "$NAME" \
  --paths "$ROOT/tools" \
  --add-data "$ROOT/server.json:." \
  --hidden-import audit_delta --hidden-import sema_probe \
  --hidden-import kerna_doctor --hidden-import env_resolver --hidden-import kern_scan \
  --distpath "$OUT" \
  --workpath "$ROOT/.build-kerna/work" \
  --specpath "$ROOT/.build-kerna" \
  "$ROOT/tools/kerna_main.py" >"$ROOT/.build-kerna/build.log" 2>&1 || {
    echo "[!] сборка упала, лог: $ROOT/.build-kerna/build.log" >&2
    tail -20 "$ROOT/.build-kerna/build.log" >&2
    exit 1
  }

BIN="$OUT/$NAME"
[ -x "$BIN" ] || { echo "[!] бинарник не создан: $BIN" >&2; exit 1; }
echo "[OK] $BIN ($(du -h "$BIN" | cut -f1))"
echo "    рядом нужны: server.json (вшит), zig-out/bin/kernc, .venv/bin/z3"
