#!/usr/bin/env bash
# ЭШЕЛОН 8, ПУНКТ 40В: kernc grep по запечатанному .kimg.
# ТРИ исхода, каждый обязателен: найдено (rc=0) / не найдено (rc=1) /
# повреждённый образ (rc=2, поиск ЗАБЛОКИРОВАН проверкой Merkle).
set -u
KERNC=${KERNC:-./zig-out/bin/kernc}
IMG=audits/real_code_corpus.kimg
fail=0
[ -x "$KERNC" ] || { echo "[!] нет $KERNC"; exit 2; }
[ -f "$IMG" ] || { echo "[!] нет $IMG"; exit 2; }

out=$("$KERNC" grep divCeil "$IMG" 2>&1); rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q 'divCeil'; then
  echo "  [OK] найденный шаблон -> rc=0, совпадения есть"
else
  echo "  [FAIL] найденный шаблон: rc=$rc"; fail=1
fi

"$KERNC" grep ZZZ_NOT_THERE "$IMG" >/dev/null 2>&1; rc=$?
if [ "$rc" -eq 1 ]; then
  echo "  [OK] отсутствующий шаблон -> rc=1"
else
  echo "  [FAIL] отсутствующий шаблон: rc=$rc (ждали 1)"; fail=1
fi

tmp=$(mktemp /tmp/kimg_torn.XXXXXX)
cp "$IMG" "$tmp"
printf '\xff' | dd of="$tmp" bs=1 seek=200 count=1 conv=notrunc 2>/dev/null
"$KERNC" grep divCeil "$tmp" >/dev/null 2>&1; rc=$?
rm -f "$tmp"
if [ "$rc" -eq 2 ]; then
  echo "  [OK] повреждённый образ -> rc=2 (поиск заблокирован)"
else
  echo "  [FAIL] повреждённый образ: rc=$rc (ждали 2)"; fail=1
fi

if [ "$fail" -eq 0 ]; then echo '[OK] kimg-grep: все 3 исхода верны'; exit 0; fi
echo '[FAIL] kimg-grep'; exit 1
