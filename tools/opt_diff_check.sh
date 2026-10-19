#!/usr/bin/env bash
# РАЗДЕЛ 5 ЭНЦИКЛОПЕДИИ: межоптимизационное дифференциальное тестирование.
# Проверяем, что ядро в Debug / ReleaseSafe / ReleaseSmall даёт ОДИН И ТОТ ЖЕ
# вердикт и ОДИН И ТОТ ЖЕ Merkle-корень: оптимизация не меняет семантику.
set -u
ZIG=${ZIG:-zig}
IMG=audits/real_code_corpus.kimg
TOY=toy.kimg
fail=0
mkdir -p /tmp/optdiff

norm() {  # убираем всё, что законно зависит от сборки (пути кэша, тайминги)
  sed -E 's/[0-9]+(\.[0-9]+)? ?(ms|мс|s|мкс|us)//g; s#/\.zig-cache/[^ ]*##g'
}

for opt in Debug ReleaseSafe ReleaseSmall; do
  out=/tmp/optdiff/$opt
  mkdir -p "$out"
  if ! $ZIG build -Doptimize=$opt -p "$out" >/tmp/optdiff/build-$opt.log 2>&1; then
    echo "  [FAIL] сборка $opt"; tail -4 /tmp/optdiff/build-$opt.log; fail=1; continue
  fi
  K="$out/bin/kernc"
  { "$K" check-integrity "$IMG" 2>&1 | grep -E 'Merkle|объектов' | norm
    "$K" verify "$TOY" 2>&1 | grep -E 'UNSAT|SAT|ИТОГ|e=' | norm
    "$K" prove tests/fixtures/abs_contract.smt2 2>&1 | grep -E 'KERN-EQ2|e  *:|ДОВЕРЕННЫХ|PROOF VERIFIED' | norm
  } > "$out/semantics.txt"
  echo "  [OK] $opt: собрано, семантика снята ($(wc -l < "$out/semantics.txt") строк)"
done

base=/tmp/optdiff/Debug/semantics.txt
[ -f "$base" ] || { echo '  [FAIL] базовая сборка не дала семантику'; exit 1; }
for opt in ReleaseSafe ReleaseSmall; do
  f=/tmp/optdiff/$opt/semantics.txt
  [ -f "$f" ] || { fail=1; continue; }
  if diff -q "$base" "$f" >/dev/null; then
    echo "  [OK] $opt == Debug (побитово по семантике)"
  else
    echo "  [FAIL] $opt расходится с Debug:"; diff "$base" "$f" | head -6; fail=1
  fi
done

[ "$fail" -eq 0 ] && { echo '[OK] opt-diff-check: 0 расхождений между уровнями оптимизации'; exit 0; }
echo '[FAIL] opt-diff-check'; exit 1
