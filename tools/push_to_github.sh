#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Use of this source code is governed by a MIT-style license that can be found in the LICENSE file.
#
# Загрузка KERN на GitHub (закрытый репозиторий).
# Использование:  ./tools/push_to_github.sh <TOKEN> [owner] [repo]
set -euo pipefail
TOKEN="${1:-}"
OWNER="${2:-newmathphys}"
REPO="${3:-kern}"
if [ -z "$TOKEN" ]; then
  echo "Использование: $0 <GITHUB_TOKEN> [owner] [repo]" >&2
  exit 1
fi
API="https://api.github.com"
AUTH="Authorization: Bearer $TOKEN"

# 1) кто мы (проверка токена)
LOGIN=$(curl -s -H "$AUTH" "$API/user" | python3 -c "import sys,json;print(json.load(sys.stdin).get('login',''))")
[ -n "$LOGIN" ] && echo "[i] токен принадлежит: $LOGIN" || { echo "[!] токен недействителен"; exit 1; }

# 2) создать ЗАКРЫТЫЙ репозиторий (если ещё нет)
code=$(curl -s -o /tmp/gh_create.json -w '%{http_code}' -X POST "$API/user/repos" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"name\":\"$REPO\",\"private\":true,\"description\":\"KERN — ядро проверки истины (Zig + Lean 4 + SMT)\"}")
echo "[i] создание репозитория: HTTP $code"
[ "$code" = "201" ] && echo "[OK] создан закрытый репозиторий $OWNER/$REPO" || echo "[i] уже существует или ошибка — продолжаем"

# 3) пуш
cd "$(dirname "$0")/.."
git remote remove origin 2>/dev/null || true
git remote add origin "https://${TOKEN}@github.com/${OWNER}/${REPO}.git"
git push -u origin main

# 4) убрать токен из remote (чтобы не утёк в .git/config)
git remote set-url origin "https://github.com/${OWNER}/${REPO}.git"
echo "[OK] загружено: https://github.com/${OWNER}/${REPO} (закрытый)"
echo "[i] токен удалён из .git/config"
