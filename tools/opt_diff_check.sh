#!/usr/bin/env bash
# N2: рабочие файлы прогона живут в СВОЁМ каталоге, а не в общем /tmp
# (гонка двух прогонов уже портила вердикты). Каталог снимается по выходу.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/kern_work.XXXXXX")"; export WORK
trap 'rm -rf "$WORK"' EXIT INT TERM
# РАЗДЕЛ 5: межоптимизационное дифференциальное тестирование.
#
# СКОРОСТЬ (ИЗМЕРЕНО): 3 полные сборки kernc занимают ~90 с, из-за чего
# `canfail --only opt-diff-check` упирался в таймаут кейса. Поэтому бинарники
# профилей кэшируются в /dev/shm по sha256 ДЕРЕВА src/: если исходники не
# менялись — гейт отрабатывает за доли секунды.
set -u
ZIG=${ZIG:-zig}
IMG=audits/real_code_corpus.kimg
TOY=toy.kimg
CACHE=/dev/shm/kern_opt_diff_cache
[ -d /dev/shm ] || CACHE=$WORK/kern_opt_diff_cache

SRC_HASH=$(find src -name '*.zig' -type f | sort | xargs cat | sha256sum | cut -d' ' -f1)
DIR="$CACHE/$SRC_HASH"
mkdir -p "$DIR"
fail=0
norm() { sed -E 's/[0-9]+(\.[0-9]+)? ?(ms|мс|s|мкс|us)//g; s#/\.zig-cache/[^ ]*##g'; }

for opt in Debug ReleaseSafe ReleaseSmall; do
  K="$DIR/$opt/bin/kernc"
  if [ -x "$K" ]; then
    echo "  [OK] $opt: из кэша (/dev/shm, sha256 src = ${SRC_HASH:0:12})"
  else
    mkdir -p "$DIR/$opt"
    if ! $ZIG build -Doptimize=$opt -p "$DIR/$opt" >"$DIR/build-$opt.log" 2>&1; then
      echo "  [FAIL] сборка $opt"; tail -4 "$DIR/build-$opt.log"; fail=1; continue
    fi
    echo "  [OK] $opt: собрано (кэш заполнен)"
  fi
  K="$DIR/$opt/bin/kernc"
  { "$K" check-integrity "$IMG" 2>&1 | grep -E 'Merkle|объектов' | norm
    "$K" verify "$TOY" 2>&1 | grep -E 'UNSAT|SAT|ИТОГ|e=' | norm
    "$K" prove tests/fixtures/abs_contract.smt2 2>&1 | grep -E 'KERN-EQ2|e  *:|ДОВЕРЕННЫХ|PROOF VERIFIED' | norm
  } > "$DIR/$opt.txt"
done

base="$DIR/Debug.txt"
[ -f "$base" ] || { echo '  [FAIL] нет базовой семантики'; exit 1; }
for opt in ReleaseSafe ReleaseSmall; do
  f="$DIR/$opt.txt"
  [ -f "$f" ] || { fail=1; continue; }
  diff -q "$base" "$f" >/dev/null && echo "  [OK] $opt == Debug" \
    || { echo "  [FAIL] $opt расходится:"; diff "$base" "$f" | head -6; fail=1; }
done
[ "$fail" -eq 0 ] && { echo '[OK] opt-diff-check: 0 расхождений'; exit 0; }
echo '[FAIL] opt-diff-check'; exit 1
