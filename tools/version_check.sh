#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# KERN: согласованность ВЕРСИИ во всех местах, где она печатается.
#
# ДЕФЕКТ #97: строка версии была ПРОДУБЛИРОВАНА в `--version` и в баннере
# `usage`, и баннер отстал (печатал v1.3 при версии v2.3.0). Пользователь,
# запустивший `kernc` без аргументов, видел другую версию, чем `kernc --version`.
#
# ПРОВЕРКА (падает при любом расхождении):
#   1. `kernc --version` и баннер `kernc` называют ОДНУ версию;
#   2. `kernx --version` и баннер `kernx` называют ОДНУ версию;
#   3. версия `kernc` == версия `kernx` (один проект — одна версия);
#   4. версия совпадает с объявленной в README (releases/download/vX.Y.Z).
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
bad() { echo "  [ПРОВАЛ] $1"; fails=$((fails + 1)); }

v_c=$(./zig-out/bin/kernc --version 2>&1 | head -1 | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+')
b_c=$(./zig-out/bin/kernc 2>&1 | grep -oE 'Engine v[0-9]+\.[0-9]+\.[0-9]+' | head -1 | grep -oE 'v[0-9.]+')
v_x=$(./zig-out/bin/kernx --version 2>&1 | head -1 | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+')
b_x=$(./zig-out/bin/kernx 2>&1 | grep -oE '\(kernx\) v[0-9]+\.[0-9]+\.[0-9]+' | head -1 | grep -oE 'v[0-9.]+')
r=$(grep -oE 'releases/download/v[0-9]+\.[0-9]+\.[0-9]+' README.md | head -1 | grep -oE 'v[0-9.]+')

# ИСХОДНИКИ, а не только бинарники: дефект #239 — `kernx` печатал v2.4.0
# при теге v2.5.0, а `kernc` уже v2.5.0. Гейт существовал, но не был в CI.
v_src=$(grep -oE 'KERN_VERSION = "v[0-9]+\.[0-9]+\.[0-9]+"' src/main.zig | head -1 | grep -oE 'v[0-9.]+')
v_next=$(grep -oE 'KERN_VERSION = "v[0-9]+\.[0-9]+\.[0-9]+"' src/next/main.zig | head -1 | grep -oE 'v[0-9.]+')
v_capi=$(grep -oE 'KERN v[0-9]+\.[0-9]+\.[0-9]+ \(C-ABI\)' src/capi.zig | head -1 | grep -oE 'v[0-9.]+')
v_srv=$(grep -oE '"version": "[0-9]+\.[0-9]+\.[0-9]+"' server.json | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
v_act=$(grep -oE "default: 'v[0-9]+\.[0-9]+\.[0-9]+'" action.yml | head -1 | grep -oE 'v[0-9.]+')
# 13-я поверхность (дефект #356): `smithery.yaml` (каталог Smithery) несёт свою
# копию версии и НЕ входил в этот гейт — к релизу v2.7.2 он остался на 2.7.1,
# хотя `gen_mcp_manifests.py --write` его не перезаписывает (только читает).
# Ровно класс #97/#292/#343: поверхность версии вне единого источника.
v_smith=$(grep -oE 'version: "[0-9]+\.[0-9]+\.[0-9]+"' smithery.yaml | head -1 | grep -oE '[0-9.]+')
# 14-я поверхность (дефект #641): `examples/ci/kern-gate.yml` — ОБРАЗЕЦ для чужих
# репозиториев, который пиннит `newmathphys/kern@vX.Y.Z`. Он дрейфовал незаметно:
# к v2.8.24 он стоял на v2.8.3, и падал не гейт версий, а `action-check` — то есть
# следствие, а не причина. Теперь пиннинг образца входит в ЕДИНЫЙ гейт версий.
v_pin=$(grep -oE 'newmathphys/kern@v[0-9]+\.[0-9]+\.[0-9]+' examples/ci/kern-gate.yml \
  | head -1 | grep -oE 'v[0-9.]+')
# 15-я поверхность (дефект #654): ФАЙЛ ЗАМЕТОК РЕЛИЗА. `release.yml` шаг 11 падает
# ровно на его отсутствии (`if [ ! -f "$NOTES" ]`) — но падает уже ПОСЛЕ нарезки
# тега, в CI, где починить нечем. Так и вышло на v2.8.25 (91291977): тег нарезан,
# релиз не опубликован. Проверяем здесь, в офлайн-гейте версий, до пуша.
v_notes=""
if [ -n "$r" ]; then
  _n="docs/RELEASE_NOTES_${r}.md"
  if [ -s "$_n" ]; then v_notes="$r"; else v_notes="НЕТ ($_n)"; fi
fi


echo "  kernc --version : ${v_c:-нет}"
echo "  kernc баннер    : ${b_c:-нет}"
echo "  kernx --version : ${v_x:-нет}"
echo "  kernx баннер    : ${b_x:-нет}"
echo "  README объявляет: ${r:-нет}"
echo "  src/main.zig    : ${v_src:-нет}"
echo "  src/next/main   : ${v_next:-нет}"
echo "  src/capi.zig    : ${v_capi:-нет}"
echo "  server.json     : v${v_srv:-нет}"
echo "  action.yml      : ${v_act:-нет} (тег, с которого Action качает бинарь)"
echo "  smithery.yaml   : v${v_smith:-нет} (13-я поверхность, дефект #356)"
echo "  kern-gate.yml   : ${v_pin:-нет} (14-я поверхность, дефект #641 — пиннинг образца)"
echo "  заметки релиза  : ${v_notes:-нет} (15-я поверхность, дефект #654 — без них Release падает)"

[ -n "$v_c" ] || bad "не удалось прочитать версию из kernc --version"
[ "$v_c" = "$b_c" ] || bad "kernc: --version ($v_c) != баннер ($b_c) — версия продублирована и разошлась"
[ "$v_x" = "$b_x" ] || bad "kernx: --version ($v_x) != баннер ($b_x)"
[ "$v_c" = "$v_x" ] || bad "kernc ($v_c) и kernx ($v_x) называют РАЗНЫЕ версии"
[ "$v_c" = "$r" ] || bad "версия бинарника ($v_c) != объявленной в README ($r)"
[ -n "$v_src" ] || bad "не удалось прочитать KERN_VERSION из src/main.zig"
[ "$v_src" = "$v_c" ] || bad "src/main.zig ($v_src) != бинарник ($v_c)"
[ "$v_next" = "$v_c" ] || bad "src/next/main.zig ($v_next) != kernc ($v_c)"
[ "$v_capi" = "$v_c" ] || bad "src/capi.zig ($v_capi) != kernc ($v_c)"
[ "v$v_srv" = "$v_c" ] || bad "server.json (v$v_srv) != kernc ($v_c)"
[ -n "$v_act" ] || bad "не удалось прочитать default-тег из action.yml"
[ "$v_act" = "$v_c" ] || bad "action.yml ($v_act) != kernc ($v_c) — Action скачает другой релиз"
[ -n "$v_smith" ] || bad "не удалось прочитать version из smithery.yaml"
[ "v$v_smith" = "$v_c" ] || bad "smithery.yaml (v$v_smith) != kernc ($v_c) — каталог Smithery объявит другую версию"
[ -n "$v_pin" ] || bad "не удалось прочитать пиннинг newmathphys/kern@vX.Y.Z из examples/ci/kern-gate.yml"
[ -n "$v_notes" ] || bad "не удалось определить файл заметок релиза для ${r}"
case "$v_notes" in
  НЕТ*) bad "нет docs/RELEASE_NOTES_${r}.md (или он пуст): релиз упадёт на шаге 11 ПОСЛЕ нарезки тега (#654)" ;;
esac

[ "$v_pin" = "$v_c" ] || bad "examples/ci/kern-gate.yml ($v_pin) != kernc ($v_c) — чужой репозиторий по образцу возьмёт другой релиз (#641)"

# 12-я поверхность (дефект #343): версия внутри JSON-отчёта. Она была зашита
# литералом `2.4.0` и разошлась с бинарником; внешний исследователь заметил это,
# скачав релиз. Читаем ФАКТИЧЕСКИЙ вывод генератора, а не исходник: иначе
# проверяли бы текст, а не поведение.
_v_rep=$("${PYTHON:-python3}" tools/kern_contracts.py --json /dev/stdout \
           examples/contracts_demo.py 2>/dev/null \
         | grep -oE '"version": "[0-9]+\.[0-9]+\.[0-9]+"' | head -1 \
         | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
echo "  JSON-отчёт      : v${_v_rep:-нет}"
[ -n "$_v_rep" ] || bad "не удалось прочитать version из JSON-отчёта (--json)"
[ "v$_v_rep" = "$v_c" ] || bad "JSON-отчёт (v$_v_rep) != kernc ($v_c) — отчёт врёт о происхождении"

echo "---"
if [ "$fails" -ne 0 ]; then
  echo "ПРОВАЛОВ: $fails"
  exit 1
fi
echo "ВЕРСИИ СОГЛАСОВАНЫ во всех местах ($v_c)"
