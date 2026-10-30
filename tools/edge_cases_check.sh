#!/usr/bin/env bash
# KERN: КРАЙНИЕ СЛУЧАИ ЭКСТРАКТОРА КОНТРАКТОВ (цель `make edge-cases`).
#
# ЗАЧЕМ. Крайние случаи синтаксиса были найдены РУЧНОЙ проверкой и дважды
# вскрыли реальные дефекты парсера (`if (c) return X; else return Y;` и
# умножение на локальную константу). Здесь они закреплены как ПРОВЕРКА:
# цель падает, если хоть один ожидаемый вердикт исчез.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
cd "$ROOT" || exit 1

out="$("$PY" tools/kern_contracts.py examples/edge_cases.zig \
        examples/edge_cases.py 2>&1)"
fail=0

chk() { # $1 = ожидаемая подстрока, $2 = что проверяем
  if printf '%s' "$out" | grep -qF "$1"; then
    echo "  [OK]   $2"
  else
    echo "  [FAIL] $2 — нет ожидаемого «$1»"
    fail=1
  fi
}

echo "KERN: крайние случаи экстрактора контрактов"
echo "───────────────────────────────────────────────────────────────────────"
chk "[PASS] absOf"                 "Zig: else-ветвь отдельным оператором"
chk "[PASS] doubleViaConst"        "Zig: умножение на ЛОКАЛЬНУЮ константу"
chk "[PASS] pure_ok"               "Python: чистая функция доказывается"
chk "ПЕРЕПОЛНЕНИЕ типа \`u32\`"     "Zig: u32 underflow ловится"
chk "[IMPURE] impure_random"       "детектор чистоты: модуль random"
chk "[IMPURE] impure_global"       "детектор чистоты: global"
chk "zig-выражение вне подмножества" "Zig: встроенная @mod -> понятная причина SKIP (дефект #117)"
chk "вычисленное значение -1 вне диапазона" "Zig: u32 underflow подтверждён конкретным вычислителем (№14)"
chk "[BV] bitAlignedAgrees"        "Zig: битовые операции (& ~) -> теория QF_BV, доказано (№15)"

# --- ПУНКТ 5 ПЛАНА v2.5: МИНИМИЗАЦИЯ КОНТРПРИМЕРА ---------------------------
# Проверяем ГРАНИЦУ ЗВУЧИМОСТИ, а не «красоту» вывода: суженный SMT обязан
# содержать ВСЕ исходные `(assert ...)` ПЛЮС ровно одно ограничение окна.
# Если сужение потеряет исходные условия, «уменьшенный контрпример» перестанет
# быть контрпримером — и проверка обязана покраснеть.
mini="$("$PY" - <<'PYX'
import importlib.util
spec = importlib.util.spec_from_file_location('kc', 'tools/kern_contracts.py')
kc = importlib.util.module_from_spec(spec); spec.loader.exec_module(kc)
smt = ('(set-logic ALL)\n(declare-const x Int)\n(assert (>= x 1000000))\n'
       '(assert (not (<= x 500)))\n(check-sat)\n')
b = kc._bound_smt(smt, ['x'])
o = [l for l in smt.splitlines() if l.startswith('(assert')]
n = [l for l in b.splitlines() if l.startswith('(assert')]
print('MINIMIZE_OK' if (all(l in n for l in o) and len(n) == len(o) + 1)
      else 'MINIMIZE_BROKEN')
PYX
)"
if printf '%s' "$mini" | grep -qF "MINIMIZE_OK"; then
  echo "  [OK]   минимизация контрпримера: сужение ТОЛЬКО добавляет ограничения (№5)"
else
  echo "  [FAIL] минимизация потеряла исходные ограничения (нарушена звучимость)"
  fail=1
fi
# --- ДЕФЕКТЫ #202/#203 + полевые адаптеры (контрактный аудит 595 функций) -----
# #202: `requires` БЕЗ `ensures` — доказывать нечего; раньше печатался ЛОЖНЫЙ
#       «КОНТРАКТ НАРУШЕН» с бессмысленным контрпримером.
# #203: цепочка `0 <= a < b` (идиома Python/werkzeug) — раньше SKIP.
# raise: `if bad: raise ...` — гард, а не «вне подмножества».
TMP=$(mktemp -d)
cat > "$TMP/a202.py" <<'PYX'
# @kern:requires num != 0
def f202(value: int, num: int) -> int:
    return value % num
PYX
cat > "$TMP/b203.py" <<'PYX'
# @kern:requires length >= 0 and start >= 0
# @kern:ensures result == 0 or (start < stop and stop <= length)
def f203(start: int, stop: int, length: int) -> bool:
    if start >= stop:
        return False
    return 0 <= start < length
PYX
cat > "$TMP/c_raise.py" <<'PYX'
# @kern:requires amount > 0
# @kern:ensures result >= 0
def f_raise(balance: int, amount: int) -> int:
    if amount <= 0:
        raise ValueError(f"bad amount {amount}")
    return balance - amount
PYX
o202=$("$PY" tools/kern_contracts.py "$TMP/a202.py" 2>&1)
o203=$("$PY" tools/kern_contracts.py "$TMP/b203.py" 2>&1)
oras=$("$PY" tools/kern_contracts.py "$TMP/c_raise.py" 2>&1)
if printf '%s' "$o202" | grep -qF "нет @kern:ensures" && \
   ! printf '%s' "$o202" | grep -qF "КОНТРАКТ НАРУШЕН"; then
  echo "  [OK]   #202: requires без ensures -> SKIP (ложного FAIL нет)"
else
  echo "  [FAIL] #202: requires без ensures всё ещё даёт FAIL"; fail=1
fi
if printf '%s' "$o203" | grep -qF "length = 1" && \
   ! printf '%s' "$o203" | grep -qF "цепочка сравнений"; then
  echo "  [OK]   #203: цепочка 0 <= a < b разобрана, контрпример выдан"
else
  echo "  [FAIL] #203: цепочка сравнений снова отбрасывается"; fail=1
fi
if printf '%s' "$oras" | grep -qF "result = -1"; then
  echo "  [OK]   raise-гард: ветка raise отброшена, обязательство доказано/опровергнуто"
else
  echo "  [FAIL] raise-гард: функция с raise не проанализирована"; fail=1
fi
# ДЕФЕКТ #206: havoc-абстракция не имеет права давать DIVERGED.
cat > "$TMP/hv_old.py" <<'PY'
def f(x: int) -> int:
    if x > 0:
        return helper(x)
    return 0
PY
cat > "$TMP/hv_new.py" <<'PY'
def f(x: int) -> int:
    if x > 0:
        return helper(x + 1)
    return 0
PY
ohv=$("$PY" tools/kern_contracts.py --diff-equiv "$TMP/hv_old.py" "$TMP/hv_new.py" 2>&1); rhv=$?
if printf '%s' "$ohv" | grep -qF "[UNKNOWN]" && ! printf '%s' "$ohv" | grep -qF "[DIVERGED]" && [ "$rhv" = 2 ]; then
  echo "  [OK]   #206: вызов (havoc) -> UNKNOWN rc=2, ложного DIVERGED нет"
else
  echo "  [FAIL] #206: havoc снова объявлен расхождением (ложное обвинение)"; fail=1
fi
# ДЕФЕКТ #207: РАЗВЁРТКА НЕ ИМЕЕТ ПРАВА ДАВАТЬ PROVEN.
cat > "$TMP/unb.py" <<'PY'
# @kern:requires i >= 0
# @kern:ensures result >= 0
def loop_many(i: int) -> int:
    while i < 10:
        i += 1
    return i
PY
ounb=$("$PY" tools/kern_contracts.py "$TMP/unb.py" 2>&1)
if printf '%s' "$ounb" | grep -qF "[UNBOUNDED]" && ! printf '%s' "$ounb" | grep -qF "[PASS]"; then
  echo "  [OK]   #207: цикл после развёртки -> UNBOUNDED SKIP (ложного PASS нет)"
else
  echo "  [FAIL] #207: развёрнутый цикл объявлен ДОКАЗАННЫМ"; fail=1
fi
cat > "$TMP/idx.py" <<'PY'
# @kern:requires len(arr) >= 1
# @kern:ensures True
def first0(arr):
    return arr[0]


# @kern:requires len(arr) >= 1
# @kern:ensures True
def firsti(arr, i):
    return arr[i]


# @kern:requires True
# @kern:ensures True
def lit_big():
    a = [1, 2, 3, 4]
    return a[3]
PY
oidx=$("$PY" tools/kern_contracts.py "$TMP/idx.py" 2>&1)
if printf '%s' "$oidx" | grep -qF "[PASS] first0" \
   && printf '%s' "$oidx" | grep -qF "[SKIP] firsti" \
   && printf '%s' "$oidx" | grep -qF "[SKIP] lit_big"; then
  echo "  [OK]   #217: arr[0] доказан; неизвестный индекс и литерал вне окна -> UNBOUNDED (ложного PASS нет)"
else
  echo "  [FAIL] #217: окно списка выдаёт доказательство при неточном индексе"; fail=1
fi
rm -rf "$TMP"

# ── Стражи чисел обязаны УМЕТЬ падать (дефект #230: два из них были фиктивными) ──
# Без этой проверки «зелёный страж» ничего не значит: правило может просто
# не совпадать с текстом, и тогда устаревшее число проживёт сколько угодно.
BK="$(mktemp -d)"
cp docs/TEST_CATALOG.md "$BK/tc.md"
cp README.md "$BK/readme.md"
# ДЕФЕКТ #316: подсадка была прибита ЛИТЕРАЛАМИ (425 и 137). Числа выросли до
# 465 и 143, sed перестал находить строку, подсадка молча ПУСТЕЛА — и падал сам
# тест, а не страж. Теперь значения берутся из docs/facts.json.
CAT="$("$PY" -c "import json;print(json.load(open('docs/facts.json'))['catalog'])")"
LEAN="$("$PY" -c "import json;print(json.load(open('docs/facts.json'))['lean_theorems'])")"
sed -i "s/\*\*Всего объявлений тестов:\*\* ${CAT}/**Всего объявлений тестов:** $((CAT - 1))/" docs/TEST_CATALOG.md
sed -i "0,/${LEAN} theorems/s//$((LEAN - 1)) theorems/" README.md
"$PY" tools/check_metrics_consistency.py >/dev/null 2>&1
rc_m=$?
"$PY" tools/check_lean_counter.py >/dev/null 2>&1
rc_l=$?
cp "$BK/tc.md" docs/TEST_CATALOG.md
cp "$BK/readme.md" README.md
rm -rf "$BK"
"$PY" tools/check_metrics_consistency.py >/dev/null 2>&1 && rc_ok_m=0 || rc_ok_m=1
"$PY" tools/check_lean_counter.py >/dev/null 2>&1 && rc_ok_l=0 || rc_ok_l=1
if [ "$rc_m" != 0 ] && [ "$rc_l" != 0 ] && [ "$rc_ok_m" = 0 ] && [ "$rc_ok_l" = 0 ]; then
  echo "  [OK]   #230: оба стража чисел падают на подсадке и снова зелены после отката"
else
  echo "  [FAIL] #230: страж чисел не заметил подсадку (metrics rc=$rc_m, lean rc=$rc_l)"
  fail=1
fi

# ── Диапазон реестра (#1–#N) обязан сверяться с журналом (дефект #231) ──
# Трижды подряд (#178, #221, #231) витрина обещала устаревший диапазон, потому
# что это число никто не сверял с фактическим максимумом журнала.
# ПОДСАДКА ДИНАМИЧЕСКАЯ: подставляем «максимум − 1» от ФАКТА, а не литерал.
# Дефект #233 (найден этим же тестом): подсадка была прибита к «#231»; после
# роста журнала до #232 `sed` не находил строку и подсадка молча ПУСТЕЛА, а
# тест рапортовал «страж не проверяет» — то есть падал сам тест, не страж.
BR="$(mktemp -d)"
cp README.ru.md "$BR/readme.md"
REAL_MAX="$(grep -oE '^\| \*\*[0-9]+\*\* \|' docs/CAPABILITY_STATUS.md | grep -oE '[0-9]+' | sort -n | tail -1)"
FAKE_MAX=$((REAL_MAX - 1))
# ДЕФЕКТ #316: `make sync` ставит ЯКОРЬ между `#` и числом
# (`#1–#<!-- fact:max_defect -->316`), поэтому прежний grep числа не видел
# вовсе — подсадка была невозможна. Скобка якоря необязательна.
if grep -qE "#1–#(<!--[^>]*-->)?${REAL_MAX}" README.ru.md; then
  sed -i "0,/#1–#\(<!--[^>]*-->\)\?${REAL_MAX}/s//#1–#${FAKE_MAX}/" README.ru.md
  "$PY" tools/check_metrics_consistency.py >/dev/null 2>&1
  rc_r=$?
  cp "$BR/readme.md" README.ru.md
  "$PY" tools/check_metrics_consistency.py >/dev/null 2>&1 && rc_ok_r=0 || rc_ok_r=1
  if [ "$rc_r" != 0 ] && [ "$rc_ok_r" = 0 ]; then
    echo "  [OK]   #231: диапазон реестра на витрине сверяется с журналом (подсадка #1–#${FAKE_MAX} при факте #${REAL_MAX} поймана)"
  else
    echo "  [FAIL] #231: диапазон реестра не проверяется (injected rc=$rc_r, restored rc=$rc_ok_r)"
    fail=1
  fi
else
  echo "  [FAIL] #231: на витрине нет диапазона #1–#${REAL_MAX} — подсадка невозможна"
  fail=1
fi
rm -rf "$BR"

# БАРЬЕРЫ 2+3 ТАКТА 2.2: ТАБЛИЧНЫЙ МИКРО-ТЕСТ ПЕРЕВОДА + IR-СЛЕПОК КОРПУСОВ.
# ЗАЧЕМ (оплачено практикой): 17 дефектов такта (#400-#417) жили в C-like-
# переводчике, и НИ ОДИН тест их не поймал, потому что проверялся КОНЕЧНЫЙ
# ВЕРДИКТ файла, а не сам перевод: `_saturate_rewrite` возвращал вход без
# изменений (#413), а `!f(c)` давало ЛОЖНУЮ модель `(= f _havoc_1)` (#414) —
# и снаружи всё выглядело тихо. Таблица из 19 пар «сырое условие -> точный
# SMT или SKIP» идёт за доли секунды БЕЗ Z3; мета-тест обязан покраснеть на
# подсаженном ожидании, иначе гейт вакуумен.
"$PY" tools/clike_ir_check.py || {
  echo "  [FAIL] табличный IR-гейт: перевод условия ИЗМЕНИЛСЯ"; fail=1; }
"$PY" tools/clike_ir_check.py --selftest || {
  echo "  [FAIL] мета-тест IR-гейта не прошёл (вакуумная проверка)"; fail=1; }
"$PY" tools/clike_ir_check.py --check-baselines || {
  echo "  [FAIL] IR-слепок корпуса разошёлся с базой (изменился РАЗБОР)"; fail=1; }

# ДЕФЕКТ #413: ХРАПОВИК ПРОТИВ УПРАВЛЯЮЩИХ БАЙТ В СТРОКОВЫХ КОНСТАНТАХ.
# ИЗМЕРЕНО: в `tools/kern_contracts.py` ШЕСТЬ раз вместо границы слова стоял
# литеральный backspace (0x08) — в raw-строке это не escape, поэтому такие
# регулярки не совпадали НИКОГДА: мёртвые дубликаты правил C/D и точная перепись
# насыщения `+|`/`-|`, не выполнявшаяся ни разу. Храповик обязан КРАСНЕТЬ на
# подсаженном байте (мета-тест ниже), иначе он вакуумен.
"$PY" tools/source_hygiene_check.py || {
  echo "  [FAIL] #413: управляющий байт 0x08 в строковой константе tools/*.py"; fail=1; }
"$PY" tools/source_hygiene_check.py --selftest || {
  echo "  [FAIL] #413: мета-тест храповика не прошёл (вакуумная проверка)"; fail=1; }

echo "───────────────────────────────────────────────────────────────────────"
if [ "$fail" = 0 ]; then
  echo "[OK] все крайние случаи воспроизведены"
else
  echo "[!] КРАЙНИЕ СЛУЧАИ СЛОМАНЫ — парсер потерял поддержку формы"
fi
exit $fail
