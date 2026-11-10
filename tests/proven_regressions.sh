#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later.
# РЕГРЕССИИ «PROVEN»: двусторонний контроль для случаев, которые ЛОМАЛИСЬ.
#   #593/#596 — длина: len(x) >= 0 и ОДИН символ длины
#   #604       — len(x) в теле против len(x) в контракте
# Требуется ВСЕ ЧЕТЫРЕ исхода; иначе приёмка вакуумна и дефект вернётся.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
P="python3 tools/kern_contracts.py"
F=tests/fixtures/proven
fail=0
chk() { # $1=вывод $2=ожидаемая строка $3=человеческое имя
  if ! printf '%s' "$1" | grep -q "$2"; then
    echo "[FAIL] $3: ожидалось «$2»"; fail=1
  else
    echo "[OK]   $3"
  fi
}
chk "$(timeout 200 $P --loops $F/loops_len_ok.py 2>&1)" \
    '\[PASS\] scan: PROVEN' 'цикл с len(x) доказан'
chk "$(timeout 200 $P --loops $F/loops_len_bad.py 2>&1)" \
    '\[FAIL\] bump: LOOP INVARIANT VIOLATED' 'нарушение инварианта поймано'
chk "$(timeout 200 $P --state-inv $F/state_len_ok.py 2>&1)" \
    '\[PASS\] clamp_index: PROVEN' 'постусловие с len(x) доказано'
chk "$(timeout 200 $P --state-inv $F/state_len_bad.py 2>&1)" \
    '\[FAIL\] grow: STATE INVARIANT VIOLATED' 'нарушение постусловия поймано'
for f in loops_len_ok state_len_ok; do
  case $f in
    loops_len_ok) out=$(timeout 200 $P --loops $F/$f.py 2>&1);;
    *)            out=$(timeout 200 $P --state-inv $F/$f.py 2>&1);;
  esac
  if printf '%s' "$out" | grep -q '\[UNKNOWN\]'; then
    echo "[FAIL] $f: есть UNKNOWN — доказательство неполно"; fail=1
  fi
done

# --- #603: --gen-tests обязан ловить НАСТОЯЩУЮ недостижимость и НЕ выдумывать её
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
timeout 200 $P --gen-tests $F/gen_dead.py "$TMP/dead.py" >/dev/null 2>&1
if grep -q 'НЕДОСТИЖИМА' "$TMP/dead.py"; then
  echo "[OK]   настоящая недостижимость (UNSAT) помечена"
else
  echo "[FAIL] настоящая недостижимость НЕ помечена — гейт слеп"; fail=1
fi
timeout 200 $P --gen-tests $F/gen_live.py "$TMP/live.py" >/dev/null 2>&1
if grep -q 'НЕДОСТИЖИМА' "$TMP/live.py"; then
  echo "[FAIL] ЖИВАЯ ветвь объявлена недостижимой (#603 вернулся)"; fail=1
else
  echo "[OK]   живая ветвь НЕ объявлена недостижимой"
fi

# --- #599/#600: --heal обязан лечить с raise и НЕ трогать файл без крашей
cp $F/heal_div.py "$TMP/div.py"
out=$(KERN_HEAL_GUARD=raise timeout 200 $P --heal "$TMP/div.py" 2>&1)
if printf '%s' "$out" | grep -q 'после патча: 0' && grep -q 'raise ValueError' "$TMP/div.py"; then
  echo "[OK]   heal: краш закрыт, гард громкий (raise)"
else
  echo "[FAIL] heal: патч не закрыл краш или гард не raise"; fail=1
fi
cp $F/heal_none.py "$TMP/none.py"
out=$(timeout 200 $P --heal "$TMP/none.py" 2>&1)
if printf '%s' "$out" | grep -q 'крашей не найдено' && cmp -s $F/heal_none.py "$TMP/none.py"; then
  echo "[OK]   heal: без крашей файл не меняется"
else
  echo "[FAIL] heal: тронул файл без крашей (ложное лечение)"; fail=1
fi
# --- --diff-equiv: эквивалентный рефакторинг ДОКАЗЫВАЕТСЯ, расхождение ЛОВИТСЯ
out=$(timeout 200 $P --diff-equiv $F/eq_old.py $F/eq_new.py 2>&1)
if printf '%s' "$out" | grep -q '\[EQUIVALENT\] clamp'; then
  echo "[OK]   diff-equiv: эквивалентный рефакторинг доказан"
else
  echo "[FAIL] diff-equiv: эквивалентность НЕ доказана"; fail=1
fi
out=$(timeout 200 $P --diff-equiv $F/eq_old.py $F/eq_bad.py 2>&1)
if printf '%s' "$out" | grep -q 'разошедшихся 1'; then
  echo "[OK]   diff-equiv: расхождение поймано с контрпримером"
else
  echo "[FAIL] diff-equiv: расхождение НЕ поймано"; fail=1
fi

# --- #207: --diff-equiv обязан доказать эквивалентность ЦИКЛОВ (LOCKSTEP)
out=$(timeout 250 $P --diff-equiv $F/loop_eq_old.py $F/loop_eq_ok.py 2>&1)
if printf '%s' "$out" | grep -q 'EQUIVALENT.*LOCKSTEP'; then
  echo "[OK]   diff-equiv: эквивалентные ЦИКЛЫ доказаны (lockstep)"
else
  echo "[FAIL] diff-equiv: эквивалентные циклы НЕ доказаны (#207 вернулся)"; fail=1
fi
out=$(timeout 250 $P --diff-equiv $F/loop_eq_old.py $F/loop_eq_bad.py 2>&1)
if printf '%s' "$out" | grep -q 'DIVERGED'; then
  echo "[OK]   diff-equiv: расходящиеся циклы пойманы"
else
  echo "[FAIL] diff-equiv: расхождение ЦИКЛОВ не поймано"; fail=1
fi

[ $fail -eq 0 ] && echo "[OK] регрессии PROVEN: 12 двусторонних контролей (loops, state-inv, gen-tests, heal, diff-equiv, lockstep-циклы), 0 unknown"
exit $fail
