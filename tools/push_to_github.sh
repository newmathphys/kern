#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
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

# 2) ПРЕДПОЛЁТНАЯ ПРОВЕРКА ПРАВ
#    2a) существует ли репозиторий?
repo_code=$(curl -s -o /dev/null -w '%{http_code}' -H "$AUTH" "$API/repos/$OWNER/$REPO")
if [ "$repo_code" != "200" ]; then
  echo "[i] репозитория $OWNER/$REPO нет — пробую создать (нужно право repository_creation)..."
  code=$(curl -s -o /tmp/gh_create.json -w '%{http_code}' -X POST "$API/user/repos" \
    -H "$AUTH" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$REPO\",\"private\":true,\"description\":\"KERN — ядро проверки истины (Zig + Lean 4 + SMT)\"}")
  echo "[i] создание репозитория: HTTP $code"
  if [ "$code" != "201" ]; then
    echo "[!] Не удалось создать репозиторий (HTTP $code)."
    echo "    Токену нужно право:  Account permissions -> Repository creation -> Read and write"
    echo "    Либо создайте пустой ЗАКРЫТЫЙ репозиторий вручную:"
    echo "      https://github.com/new?name=$REPO&visibility=private"
    echo "    и запустите скрипт снова."
    exit 1
  fi
  echo "[OK] создан закрытый репозиторий $OWNER/$REPO"
else
  echo "[i] репозиторий $OWNER/$REPO уже существует"
fi

#    2b) есть ли право на запись содержимого (contents=write)?
w_code=$(curl -s -o /dev/null -w '%{http_code}' -X PUT \
  -H "$AUTH" -H 'Accept: application/vnd.github+json' \
  "$API/repos/$OWNER/$REPO/contents/.kern-probe" -d '{}')
if [ "$w_code" = "403" ]; then
  echo "[!] Токену НЕ хватает права на запись (contents=write)."
  echo "    Repository permissions -> Contents -> Read and write"
  exit 1
fi
echo "[i] право на запись содержимого: OK (HTTP $w_code)"

# 3) пуш
cd "$(dirname "$0")/.."
git remote remove origin 2>/dev/null || true
git remote add origin "https://${TOKEN}@github.com/${OWNER}/${REPO}.git"
git push -u origin main

# 4) убрать токен из remote (чтобы не утёк в .git/config)
git remote set-url origin "https://github.com/${OWNER}/${REPO}.git"
echo "[OK] загружено: https://github.com/${OWNER}/${REPO} (закрытый)"
echo "[i] токен удалён из .git/config"
