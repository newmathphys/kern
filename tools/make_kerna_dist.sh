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
# ДЕФЕКТ #497: клиент получал ИНСТРУМЕНТ БЕЗ КОНТРАКТА О ГРАНИЦАХ. Архив без
# `LIMITS` — это обещание без мелкого шрифта, поэтому теперь это ОТКАЗ сборки.
for f in docs/LIMITS.md docs/LIMITS.ru.md; do
  [ -f "$f" ] || { echo "[!] нет $f — архив без границ применимости запрещён (#497)" >&2; exit 3; }
done

rm -rf "$STAGE"
mkdir -p "$STAGE/zig-out/bin" "$STAGE/.venv/bin"

cp dist/kerna "$STAGE/kerna"
cp zig-out/bin/kernc "$STAGE/zig-out/bin/kernc"
cp .venv/bin/z3 "$STAGE/.venv/bin/z3"
cp server.json LICENSE LICENSE-COMMERCIAL.md "$STAGE/"
# #497: ГРАНИЦЫ ЕДУТ ВМЕСТЕ С БИНАРНИКОМ (что доказывается, а что НЕТ).
cp docs/LIMITS.md "$STAGE/LIMITS.md"
cp docs/LIMITS.ru.md "$STAGE/LIMITS.ru.md"

cat > "$STAGE/README-RUN.txt" <<'EOF'
KERN — Zero-Dependency Appliance
================================
1) Распакуйте архив целиком (структура важна: kernc и z3 лежат РЯДОМ с kerna).
2) Проверьте зависимости:      ./kerna --doctor
3) Аудит любой папки:          ./kerna /путь/к/проекту
   Только рентген (JSON):      ./kerna --xray /путь/к/проекту --xray-json
   Доказать контракты в файле: ./kerna /путь/к/файлу.py

ЧТО ЗНАЧИТ КОД ВОЗВРАТА (ИЗМЕРЕНО НА ЭТОМ АРХИВЕ, не «по документации»)
  rc=0   — анализ ВЫПОЛНЕН. Это НЕ «находок 0» и НЕ «код чист»: паспорт
           печатается всегда, находки перечислены в отчёте. ИЗМЕРЕНО:
           папка с 5 находками -> rc=0 (поэтому rc этого бинаря НЕЛЬЗЯ
           использовать как «гейт чистоты»: он всегда 0 при успешном анализе);
  rc=1   — в контрактном пути (файл с `@kern:`): нарушение контракта;
  rc=2   — ДИСТРИБУТИВ НЕПОЛОН или нет решателя (`--doctor`): это НЕ «код чист»;
  rc=3   — неверный вызов/нет такого пути.
  ГОТОВЫЙ ГЕЙТ ДЛЯ CI: `examples/ci/kern-gate.yml` + `action.yml` (в репозитории) —
  GitHub Action блокирует PR ТОЛЬКО на находках, внесённых этим изменением
  (`audit-delta`), и различает «нет находок» / «есть находки» / «дистрибутив
  неполон» кодами 0 / 1 / 2.

ЛИЦЕНЗИЯ: AGPL-3.0-or-later (LICENSE) либо коммерческая (LICENSE-COMMERCIAL.md).
ГРАНИЦЫ: LIMITS.ru.md / LIMITS.md РЯДОМ (в этом же архиве) — что доказывается,
        а что НЕТ. Прочтите до первого аудита.
EOF

( cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )

TAR="$OUT/$NAME.tar.gz"
tar -czf "$TAR" -C "$OUT" "$NAME"
# УРОВЕНЬ РЕЛИЗА (Шаг 2): сумма САМОГО архива — то, что GitHub Action сверяет
# ДО распаковки. Без неё «проверка целостности» была бы только ВНУТРИ архива,
# то есть уже после того, как недоверенные байты распакованы.
( cd "$OUT" && sha256sum "$NAME.tar.gz" > SHA256SUMS )

echo "[OK] $TAR ($(du -h "$TAR" | cut -f1))"
echo "     состав:"; ( cd "$STAGE" && du -h kerna zig-out/bin/kernc .venv/bin/z3 | sed 's/^/       /' )
echo "     распаковка: tar -xzf $(basename "$TAR") && cd $NAME && ./kerna --doctor"
