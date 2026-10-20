#!/usr/bin/env bash
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

echo "---"
if [ "$fails" -ne 0 ]; then
  echo "ПРОВАЛОВ: $fails"
  exit 1
fi
echo "ВЕРСИИ СОГЛАСОВАНЫ во всех местах ($v_c)"
