#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# 33-Я СТАДИЯ: НАТИВНАЯ БИРЕШЁТКА B4 (`kernc belnap`) ПРОТИВ НЕЗАВИСИМОЙ МОДЕЛИ.
#
# ЧТО ДОКАЗЫВАЕТСЯ:
#   * CLI выводит НАТИВНУЮ функцию ядра (`src/core/eq2.zig`) — в обвязке нет таблиц;
#   * ожидания считает НЕЗАВИСИМАЯ модель пар свидетельств (pos, neg), написанная
#     здесь с нуля: ни одна клетка из Zig НЕ скопирована;
#   * покрытие полное: 4 бинарные операции x 16 пар + 4 унарных `not` = 68 клеток;
#   * `--bits` отдаёт код `p|(n<<1)` и сами биты (знание, а не строка символа);
#   * `--table` совпадает с моделью построчно;
#   * мусорный вход (операция/литерал/регистр/арность/флаг) — rc != 0 И текст в stderr
#     (молчаливый успех на неверном входе — класс #498).
#
# ЧЕСТНАЯ ГРАНИЦА: скрипт проверяет CLI-ПОВЕРХНОСТЬ и совпадение с моделью.
# Законы решётки (коммутативность, ассоциативность, идемпотентность, поглощение,
# инволюция, неподвижные N/B) доказываются Zig-тестами `zig build test`
# (файл `src/core/eq2.zig`) — скрипт не имеет полномочий заявлять «доказано» о законах.
#
# НЕВАКУУМНОСТЬ (двусторонняя):
#   1) KERN_CANFAIL_MUTATE=1 портит ОДНУ ожидаемую клетку -> гейт ОБЯЗАН упасть;
#   2) `--selftest` запускает гейт дважды (норма -> 0, мутация -> != 0) и краснеет,
#      если мутация НЕ ломает проверку (иначе гейт вакуумен);
#   3) кейс `belnap-check` в `tools/canfail.py` ломает САМО ЯДРО (`andT`) и требует
#      красного — это уже про чувствительность к реальному дефекту, не к модели.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
KERNC=${KERNC:-zig-out/bin/kernc}
MUTATE=${KERN_CANFAIL_MUTATE:-0}

if [ "${1:-}" = "--selftest" ]; then
  bash "$0" >/dev/null 2>&1; ok_rc=$?
  KERN_CANFAIL_MUTATE=1 bash "$0" >/dev/null 2>&1; mut_rc=$?
  if [ "$ok_rc" -eq 0 ] && [ "$mut_rc" -ne 0 ]; then
    echo "[OK] belnap-check --selftest: чистая модель -> rc=0, испорченная клетка -> rc=$mut_rc"
    exit 0
  fi
  echo "[FAIL] belnap-check --selftest: ok_rc=$ok_rc mut_rc=$mut_rc"
  echo "       испорченная клетка НЕ ломает гейт => проверка вакуумна"
  exit 1
fi

[ -x "$KERNC" ] || { echo "[!] нет $KERNC — сначала zig build"; exit 2; }

# --- НЕЗАВИСИМАЯ МОДЕЛЬ: пары свидетельств (pos, neg), не таблица ---
EXPECTED=$(python3 - <<'PY'
B = {"N": (0, 0), "T": (1, 0), "F": (0, 1), "B": (1, 1)}
R = {(0, 0): "N", (1, 0): "T", (0, 1): "F", (1, 1): "B"}
VALS = "NTFB"

def apply(name, a, b=None):
    p1, n1 = B[a]
    if name == "not":
        return R[(n1, p1)]
    p2, n2 = B[b]
    return R[{
        "join_k": (p1 | p2, n1 | n2),
        "meet_k": (p1 & p2, n1 & n2),
        "and_t": (p1 & p2, n1 | n2),
        "or_t": (p1 | p2, n1 & n2),
    }[name]]

for op in ("join_k", "meet_k", "and_t", "or_t"):
    for a in VALS:
        for b in VALS:
            print("%s|%s|%s|%s" % (op, a, b, apply(op, a, b)))
for a in VALS:
    print("not|%s||%s" % (a, apply("not", a)))

print("__BITS__")
for a in VALS:
    p, n = B[a]
    print("%s %d %d %d" % (a, p | (n << 1), p, n))
PY
)
BITS_OF=$(printf '%s\n' "$EXPECTED" | sed -n '/^__BITS__$/,$p' | tail -n +2)
EXPECTED=$(printf '%s\n' "$EXPECTED" | sed '/^__BITS__$/,$d')
declare -A BITS_MAP=()
while read -r sym code p n; do
  [ -n "${sym:-}" ] || continue
  BITS_MAP[$sym]="$sym $code $p $n"
done <<< "$BITS_OF"

fails=0
total=0
while IFS='|' read -r op a b want; do
  [ -n "${op:-}" ] || continue
  total=$((total + 1))
  if [ "$MUTATE" = "1" ] && [ "$op" = "join_k" ] && [ "$a" = "T" ] && [ "$b" = "F" ]; then
    want="T"   # ИСПОРЧЕННАЯ клетка: нативная модель даёт B
  fi
  if [ -n "$b" ]; then
    got=$("$KERNC" belnap "$op" "$a" "$b" 2>/dev/null) || got="<rc!=0>"
  else
    got=$("$KERNC" belnap "$op" "$a" 2>/dev/null) || got="<rc!=0>"
  fi
  if [ "$got" != "$want" ]; then
    echo "[FAIL] $op($a${b:+,$b}) = '$got', модель пар свидетельств даёт '$want'"
    fails=$((fails + 1))
  fi
  # --bits: символ, код p|(n<<1), p, n — сверяем с ТОЙ ЖЕ парой
  if [ -n "$b" ]; then
    bits_out=$("$KERNC" belnap --bits "$op" "$a" "$b" 2>/dev/null) || bits_out=""
  else
    bits_out=$("$KERNC" belnap --bits "$op" "$a" 2>/dev/null) || bits_out=""
  fi
  want_bits=${BITS_MAP[$want]}
  if [ "$bits_out" != "$want_bits" ]; then
    echo "[FAIL] --bits $op($a${b:+,$b}) = '$bits_out', модель даёт '$want_bits'"
    fails=$((fails + 1))
  fi
done <<< "$EXPECTED"

if [ "$total" -ne 68 ]; then
  echo "[FAIL] покрытие: сверено клеток $total, ожидалось 68 (4 x 16 + 4)"
  fails=$((fails + 1))
fi

# --- --table: построчное совпадение с той же моделью ---
table=$("$KERNC" belnap --table 2>/dev/null)
table_rows=$(printf '%s\n' "$table" | grep -c . || true)
if [ "$table_rows" -ne 68 ]; then
  echo "[FAIL] --table: строк $table_rows, ожидалось 68"
  fails=$((fails + 1))
fi
if [ "$MUTATE" != "1" ]; then
  while IFS='|' read -r op a b want; do
    [ -n "${op:-}" ] || continue
    if [ -n "$b" ]; then
      expect_line="$op|$a|$b|$want"
    else
      expect_line="$op|$a|$want"
    fi
    printf '%s\n' "$table" | grep -qxF "$expect_line" || {
      echo "[FAIL] --table: нет строки '$expect_line' из модели"
      fails=$((fails + 1))
    }
  done <<< "$EXPECTED"
fi

# --- МУСОРНЫЙ ВХОД: rc != 0 И непустой stderr ---
garbage() {
  desc=$1; shift
  errf=$(mktemp)
  "$KERNC" belnap "$@" >/dev/null 2>"$errf"; rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "[FAIL] мусор ($desc): rc=0 — молчаливый успех на неверном входе"
    fails=$((fails + 1))
  elif [ ! -s "$errf" ]; then
    echo "[FAIL] мусор ($desc): rc=$rc, но stderr пуст (отказ без объяснения)"
    fails=$((fails + 1))
  fi
  rm -f "$errf"
}
garbage "неизвестная операция" bogus T T
garbage "литерал вне NTFB" join_k A T
garbage "нижний регистр литерала" join_k t T
garbage "нехватка операнда" join_k T
garbage "лишний операнд" not T T
garbage "неизвестный флаг" --nope join_k T T

if [ "$fails" -ne 0 ]; then
  echo "[FAIL] belnap-check: провалов $fails (клеток сверено $total)"
  exit 1
fi
echo "[OK] belnap-check: нативная B4 ядра == независимая модель пар свидетельств (68 клеток + --bits + --table + 6 отказов)"
exit 0
