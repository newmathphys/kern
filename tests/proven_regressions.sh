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

# --- ЗВУЧНОСТЬ: Коллатц — ОТКРЫТАЯ проблема; PROVEN здесь был бы ЛОЖЬЮ
out=$(timeout 250 $P --loops $F/collatz_open.py 2>&1)
if printf '%s' "$out" | grep -q '\[PASS\] collatz_len'; then
  echo "[FAIL] КРИТИЧНО: Коллатц объявлен ДОКАЗАННЫМ (ложное доказательство)"; fail=1
elif printf '%s' "$out" | grep -q 'NON-TERMINATING'; then
  echo "[OK]   звучимость: остановка Коллатца НЕ объявлена доказанной"
else
  echo "[FAIL] Коллатц: ни доказан, ни опровергнут — исход неясен"; fail=1
fi
# --- #605: `//=` и `%=` в теле цикла (реальный sum_of_digits)
out=$(timeout 250 $P --loops $F/digits_ok.py 2>&1)
if printf '%s' "$out" | grep -q '\[PASS\] sum_of_digits: PROVEN'; then
  echo "[OK]   //= и %= поддержаны (sum_of_digits доказан)"
else
  echo "[FAIL] //= / %= не поддержаны (#605 вернулся)"; fail=1
fi

# --- #607: `>>=`/`<<=` поддержаны (реальный binary_exponentiation)
out=$(timeout 250 $P --loops $F/binexp_ok.py 2>&1)
if printf '%s' "$out" | grep -q '\[PASS\] bin_pow: PROVEN'; then
  echo "[OK]   >>= поддержан (binary_exponentiation доказан)"
else
  echo "[FAIL] >>= не поддержан (#607 вернулся)"; fail=1
fi
# --- #608: `break` в теле -> честный SKIP с ПРИЧИНОЙ, а не ложное NON-TERMINATING
out=$(timeout 250 $P --loops $F/break_named.py 2>&1)
if printf '%s' "$out" | grep -q 'SKIP.*break'; then
  echo "[OK]   break: честный SKIP с названной причиной"
elif printf '%s' "$out" | grep -q 'NON-TERMINATING'; then
  echo "[FAIL] break: ЛОЖНОЕ незавершение (#608 вернулся)"; fail=1
else
  echo "[FAIL] break: исход неясен"; fail=1
fi

# --- #608 (расширение): ранний `return` в теле -> SKIP, а не ложное незавершение
out=$(timeout 250 $P --loops $F/return_in_body.py 2>&1)
if printf '%s' "$out" | grep -q 'SKIP.*return'; then
  echo "[OK]   return в теле: честный SKIP с названной причиной"
elif printf '%s' "$out" | grep -q 'NON-TERMINATING'; then
  echo "[FAIL] return в теле: ЛОЖНОЕ незавершение"; fail=1
else
  echo "[FAIL] return в теле: исход неясен"; fail=1
fi
# --- #609: SKIP обязан называть ПРИЧИНУ, а не «вне подмножества»
cp $F/../proven/../proven/break_named.py /dev/null 2>/dev/null || true
out=$(timeout 250 $P --loops $F/return_in_body.py 2>&1)
if printf '%s' "$out" | grep -q 'не моделируется'; then
  echo "[OK]   отказ называет причину (#609)"
else
  echo "[FAIL] отказ без причины"; fail=1
fi

# --- #610: НЕЛИНЕЙНАЯ арифметика (QF_NIA): условие с произведением
out=$(timeout 250 $P --loops $F/nia_guard_ok.py 2>&1)
if printf '%s' "$out" | grep -q '\[PASS\] count_steps: PROVEN'; then
  echo "[OK]   NIA: цикл с фактор-произведением доказан"
else
  echo "[FAIL] NIA: нелинейное условие не доказано (#610 вернулся)"; fail=1
fi
# --- #610: инвариант С ПРОИЗВЕДЕНИЕМ (настоящая QF_NIA-задача)
out=$(timeout 250 $P --loops $F/nia_sqrt_ok.py 2>&1)
if printf '%s' "$out" | grep -q '\[PASS\] sqrt_steps: PROVEN'; then
  echo "[OK]   NIA: инвариант с квадратом доказан"
else
  echo "[FAIL] NIA: инвариант с произведением не доказан"; fail=1
fi
# --- NIA-ОТРИЦАТЕЛЬНЫЙ: шаг +2 обязан ломать инвариант
out=$(timeout 250 $P --loops $F/nia_bad.py 2>&1)
if printf '%s' "$out" | grep -q 'LOOP INVARIANT VIOLATED'; then
  echo "[OK]   NIA: нарушение инварианта с произведением поймано"
else
  echo "[FAIL] NIA: нарушение НЕ поймано — доказательство незвучно"; fail=1
fi

# --- #611: простое распаковывание (реальная функция проекта пользователя)
out=$(timeout 250 $P --loops $F/tuple_unpack_ok.py 2>&1)
if printf '%s' "$out" | grep -q 'line_repair_search: PROVEN'; then
  echo "[OK]   tuple-unpack: line_repair_search доказан"
else
  echo "[FAIL] tuple-unpack: реальная функция НЕ доказана (#611 вернулся)"; fail=1
fi
# --- swap (`x, y = y, x % y`) обязан остаться ИМЕНОВАННЫМ отказом
out=$(timeout 250 $P --loops $F/swap_named.py 2>&1)
if printf '%s' "$out" | grep -q 'SKIP.*swap'; then
  echo "[OK]   swap: именованный отказ (не выдумываем путь)"
elif printf '%s' "$out" | grep -q 'PROVEN'; then
  echo "[FAIL] swap: доказан БЕЗ модели одновременности — незвучно"; fail=1
else
  echo "[FAIL] swap: исход неясен"; fail=1
fi

[ $fail -eq 0 ] && echo "[OK] регрессии PROVEN: 23 двусторонних контроля (loops, state-inv, gen-tests, heal, diff-equiv, lockstep-циклы), 0 unknown"
exit $fail
