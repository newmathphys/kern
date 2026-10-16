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
set -u
cd "$(dirname "$0")/.."
fails=0
bad() { echo "  [ПРОВАЛ] $1"; fails=$((fails + 1)); }

v_c=$(./zig-out/bin/kernc --version 2>&1 | head -1 | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+')
b_c=$(./zig-out/bin/kernc 2>&1 | grep -oE 'Engine v[0-9]+\.[0-9]+\.[0-9]+' | head -1 | grep -oE 'v[0-9.]+')
v_x=$(./zig-out/bin/kernx --version 2>&1 | head -1 | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+')
b_x=$(./zig-out/bin/kernx 2>&1 | grep -oE '\(kernx\) v[0-9]+\.[0-9]+\.[0-9]+' | head -1 | grep -oE 'v[0-9.]+')
r=$(grep -oE 'releases/download/v[0-9]+\.[0-9]+\.[0-9]+' README.md | head -1 | grep -oE 'v[0-9.]+')

echo "  kernc --version : ${v_c:-нет}"
echo "  kernc баннер    : ${b_c:-нет}"
echo "  kernx --version : ${v_x:-нет}"
echo "  kernx баннер    : ${b_x:-нет}"
echo "  README объявляет: ${r:-нет}"

[ -n "$v_c" ] || bad "не удалось прочитать версию из kernc --version"
[ "$v_c" = "$b_c" ] || bad "kernc: --version ($v_c) != баннер ($b_c) — версия продублирована и разошлась"
[ "$v_x" = "$b_x" ] || bad "kernx: --version ($v_x) != баннер ($b_x)"
[ "$v_c" = "$v_x" ] || bad "kernc ($v_c) и kernx ($v_x) называют РАЗНЫЕ версии"
[ "$v_c" = "$r" ] || bad "версия бинарника ($v_c) != объявленной в README ($r)"

echo "---"
if [ "$fails" -ne 0 ]; then
  echo "ПРОВАЛОВ: $fails"
  exit 1
fi
echo "ВЕРСИИ СОГЛАСОВАНЫ во всех местах ($v_c)"
