#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
#
# `make_kerna_dist.sh` — сборка РЕЛИЗНОГО архива Zero-Dependency Appliance (#496).
#
# ЧТО ВНУТРИ (62 МБ, измерено):
#   kerna                     9.8 МБ  — onefile-бинарь (frontend, Python внутри)
#   zig-out/bin/kernc          26 МБ  — статический backend (верификатор/пруф-чекер)
#   .venv/bin/z3               27 МБ  — решатель (нужен для контрпримеров)
#   server.json                       — версия (читается НА ИМПОРТЕ, #494)
#   LICENSE, LICENSE-COMMERCIAL.md    — AGPLv3 + условия B2B
#   README-RUN.txt                    — три строки «как запустить» + доктор
#
# ЧЕСТНО. Архив НЕ содержит «установщика»: клиент распаковывает и запускает
# `./kerna --doctor` — доктор сам скажет, чего не хватает (#494). Молчаливого
# «находок 0» без решателя больше нет.
#
# Использование:  tools/make_kerna_dist.sh [OUTDIR]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
OUT="${1:-$ROOT/dist-release}"
VER="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/server.json")"
NAME="kerna-dist-v${VER}"
STAGE="$OUT/$NAME"

cd "$ROOT"

[ -x "dist/kerna" ] || { echo "[!] нет dist/kerna — сначала: make kerna-build" >&2; exit 3; }
[ -x "zig-out/bin/kernc" ] || { echo "[!] нет zig-out/bin/kernc — сначала: zig build" >&2; exit 3; }
[ -x ".venv/bin/z3" ] || { echo "[!] нет .venv/bin/z3 — решатель обязателен" >&2; exit 3; }

rm -rf "$STAGE"
mkdir -p "$STAGE/zig-out/bin" "$STAGE/.venv/bin"

cp dist/kerna "$STAGE/kerna"
cp zig-out/bin/kernc "$STAGE/zig-out/bin/kernc"
cp .venv/bin/z3 "$STAGE/.venv/bin/z3"
cp server.json LICENSE LICENSE-COMMERCIAL.md "$STAGE/"

cat > "$STAGE/README-RUN.txt" <<'EOF'
KERN — Zero-Dependency Appliance
================================
1) Распакуйте архив целиком (структура важна: kernc и z3 лежат РЯДОМ с kerna).
2) Проверьте зависимости:      ./kerna --doctor
3) Аудит любой папки:          ./kerna /путь/к/проекту
   Только рентген (JSON):      ./kerna --xray /путь/к/проекту --xray-json
   Доказать контракты в файле: ./kerna /путь/к/файлу.py

ЧТО ЗНАЧИТ ОТКАЗ
  rc=0 — анализ выполнен (находки могут быть 0 или больше)
  rc=1 — найдены нарушения/регресс (для CI)
  rc=2 — ДИСТРИБУТИВ НЕПОЛОН или нет решателя (это НЕ «код чист»)

ЛИЦЕНЗИЯ: AGPL-3.0-or-later (LICENSE) либо коммерческая (LICENSE-COMMERCIAL.md).
ГРАНИЦЫ: docs/LIMITS.md в репозитории — что доказывается, а что нет.
EOF

( cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )

TAR="$OUT/$NAME.tar.gz"
tar -czf "$TAR" -C "$OUT" "$NAME"
echo "[OK] $TAR ($(du -h "$TAR" | cut -f1))"
echo "     состав:"; ( cd "$STAGE" && du -h kerna zig-out/bin/kernc .venv/bin/z3 | sed 's/^/       /' )
echo "     распаковка: tar -xzf $(basename "$TAR") && cd $NAME && ./kerna --doctor"
