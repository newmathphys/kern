#!/usr/bin/env bash
# ЭШЕЛОН 3, ПУНКТ 13: ПРИЁМКА --xray. Требуем НАСТОЯЩИЕ находки на фикстуре
# examples/xray_demo.py: мёртвая ветка, избыточный гард и краш-путь.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT=$(timeout 300 python3 tools/kern_contracts.py --xray examples/xray_demo.py 2>&1) || { echo "[!] --xray упал"; echo "$OUT" | tail -5; exit 1; }
echo "$OUT" | tail -12
fail=0
for pat in 'DEAD BRANCH' 'REDUNDANT GUARD' 'CRASH PATH' '[XRAY SUMMARY]'; do
  if echo "$OUT" | grep -q "$pat"; then echo "  [OK] найдено: $pat"; else echo "  [ПРОВАЛ] нет: $pat"; fail=1; fi
done
if [ "$fail" != 0 ]; then echo "[!] --xray не нашёл ожидаемых находок"; exit 1; fi
echo "[OK] --xray: все три класса находок подтверждены"

# ЭШЕЛОН 4, ПУНКТ 21: ГРАНИЦЫ МАССИВОВ (`arr[i]` -> `0 <= i < len`).
# Ключевое — ОТСУТСТВИЕ ЛОЖНОГО СРАБАТЫВАНИЯ: функция с гардами (`get_safe`)
# НЕ должна обвиняться, а функция без гардов (`get_unsafe`) — должна.
BOUNDS=$(timeout 300 python3 tools/kern_contracts.py --xray examples/array_bounds.py 2>&1) || { echo "[!] xray на array_bounds упал"; exit 1; }
echo "$BOUNDS" | grep -q 'BOUNDS PATH\] get_unsafe' || { echo "[!] get_unsafe НЕ обвинён — детектор границ слеп"; exit 1; }
if echo "$BOUNDS" | grep -q 'BOUNDS PATH\] get_safe'; then echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ get_safe (гарды не учтены)"; exit 1; fi
echo "$BOUNDS" | grep -q 'BOUNDS\] get_unknown_len' || { echo "[!] нет честного 'длина неизвестна'"; exit 1; }
echo "[OK] границы: get_unsafe обвинён, get_safe НЕ обвинён, неизвестная длина честно помечена"

# ДЕФЕКТ #322: ГАРДЫ, КОТОРЫЕ РАНЬШЕ НЕ УЧИТЫВАЛИСЬ. Каждый случай проверяется
# ДВУСТОРОННЕ: ложное обвинение не должно появляться, а честный UNKNOWN обязан
# остаться — это не «тихое подавление», случай НАЗВАН, а не спрятан.
if echo "$BOUNDS" | grep -q 'BOUNDS PATH\] get_ifexp_guard'; then
  echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ get_ifexp_guard (гард в тернарнике не учтён)"; exit 1
fi
if echo "$BOUNDS" | grep -q 'BOUNDS PATH\] get_continue_guard'; then
  echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ get_continue_guard (ранний выход continue не учтён)"; exit 1
fi
if ! echo "$BOUNDS" | grep -q 'BOUNDS UNKNOWN\] get_loop_index'; then
  echo "[!] get_loop_index НЕ помечен UNKNOWN: индекс от переменной цикла обвиняется недостижимым свидетелем"; exit 1
fi
if echo "$BOUNDS" | grep -q 'BOUNDS PATH\] get_range_min_guard'; then
  echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ get_range_min_guard (граница range(start, min(..., len)) не учтена)"; exit 1
fi
echo "[OK] #322: тернарник-гард, continue-гард и граница range(min(..., len)) не обвиняются, индекс от переменной цикла -> честный UNKNOWN"

# ДЕФЕКТ #351: ПРЕДУСЛОВИЕ-ДЕКОРАТОР (`@deal.pre`) — гард на входе. Проверка
# ДВУСТОРОННЯЯ: под предусловием обвинять нельзя, без него — обязательно.
DEAL=$(timeout 300 python3 tools/kern_contracts.py --xray examples/deal_guard_demo.py 2>&1) || {
  echo "[!] xray на deal_guard_demo упал"; exit 1; }
if echo "$DEAL" | grep -q 'CRASH PATH\] div_guarded'; then
  echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ div_guarded (предусловие-декоратор не учтено)"; exit 1
fi
if echo "$DEAL" | grep -q 'CRASH PATH\] div_guarded_nested'; then
  echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ div_guarded_nested (декоратор + ветвление)"; exit 1
fi
echo "$DEAL" | grep -q 'CRASH PATH\] div_unguarded' || {
  echo "[!] div_unguarded НЕ обвинён — детектор ослеп на предусловиях"; exit 1; }
echo "[OK] #351: под @deal.pre находки нет, без него деление на ноль найдено"

# B2: C-СПЕЦИФИЧНЫЕ КЛАССЫ ([BOUNDS PATH] / [OVERFLOW PATH], дефекты #187/#188).
# Требование двустороннее: без гарда — обвиняем, с гардом — МОЛЧИМ.
# Иначе это либо слепой детектор, либо генератор ложных тревог (урок #178).
TMPC=$(mktemp -d)
trap 'rm -rf "$TMPC"' EXIT
cat > "$TMPC/oob.c" <<'CEOF'
int get(int *buf, int i) {
    return buf[i - 1];
}
CEOF
cat > "$TMPC/oob_ok.c" <<'CEOF'
int get_ok(int *buf, int i) {
    if (i < 1) { return 0; }
    return buf[i - 1];
}
CEOF
cat > "$TMPC/ovf.c" <<'CEOF'
char *dup_bad(int len) {
    char *p = malloc(len + 1);
    return p;
}
CEOF
cat > "$TMPC/ovf_ok.c" <<'CEOF'
char *dup_ok(int len) {
    if (len > 1000) { return 0; }
    char *p = malloc(len + 1);
    return p;
}
CEOF
C1=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/oob.c" 2>&1) || true
echo "$C1" | grep -q 'BOUNDS PATH. get:' || { echo "[!] C: buf[i-1] без гарда НЕ обвинён (детектор слеп)"; exit 1; }
C2=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/oob_ok.c" 2>&1) || true
if echo "$C2" | grep -q 'BOUNDS PATH. get_ok'; then echo "[!] C: ЛОЖНОЕ обвинение buf[i-1] под if (i < 1) return"; exit 1; fi
C3=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/ovf.c" 2>&1) || true
echo "$C3" | grep -q 'OVERFLOW PATH. dup_bad' || { echo "[!] C: malloc(len+1) без гарда НЕ обвинён"; exit 1; }
C4=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/ovf_ok.c" 2>&1) || true
if echo "$C4" | grep -q 'OVERFLOW PATH. dup_ok'; then echo "[!] C: ЛОЖНОЕ обвинение malloc под if (len > 1000) return"; exit 1; fi
echo "[OK] C-like B2: BOUNDS/OVERFLOW обвиняют без гарда и МОЛЧАТ с гардом (4/4)"

# ДЕФЕКТ #318: ДЕЛЕНИЕ ПОД ГАРДОМ. Раньше `path_conds` складывал ТОЛЬКО
# `(not cond)` — условие для кода ПОСЛЕ `if`. Делитель же стоит ВНУТРИ блока, и
# запрос получался `(x == 0) AND (x == 0)`: `if (x != 0) { y / x; }` объявлялся
# делением на ноль. Теперь условия вычисляются ПО ПОЗИЦИИ операции.
cat > "$TMPC/div_ok.c" <<'CEOF'
int div_ok(int x, int y)
{
    if (x != 0)
    {
        if (y != 0)
        {
            return y / x;
        }
    }
    return 0;
}
CEOF
C5=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/div_ok.c" 2>&1) || true
if echo "$C5" | grep -q 'CRASH PATH. div_ok'; then
  echo "[!] C: ЛОЖНОЕ обвинение деления под if (x != 0) — дефект #318 вернулся"; exit 1
fi
# ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: без гарда то же деление ОБЯЗАНО обвиняться.
cat > "$TMPC/div_bad.c" <<'CEOF'
int div_bad(int x, int y)
{
    return y / x;
}
CEOF
C6=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/div_bad.c" 2>&1) || true
echo "$C6" | grep -q 'CRASH PATH. div_bad' || { echo "[!] C: деление БЕЗ гарда НЕ обвинён — детектор ослеп"; exit 1; }
echo "[OK] C-like #318: деление ПОД ГАРДОМ молчит, БЕЗ гарда — обвиняется (2/2)"

# ПОЛНОСПЕКТРАЛЬНЫЙ ОБХОД (`--full-scan`): агрегатор + ЧЕСТНЫЙ авто-роутинг.
# Требование: агрегатор обязан (а) собрать xray-находки, (б) прогнать anti-cheat,
# (в) напечатать AUTO-ROUTE как «применимо, НО без контракта НЕ проверено»,
# и (г) не выдавать роутинг за доказательство. Иначе это реклама, а не отчёт.
FS=$(timeout 300 python3 tools/kern_contracts.py --full-scan examples 2>&1) || { echo "[!] --full-scan упал"; exit 1; }
echo "$FS" | grep -q '\[FULL-SCAN SUMMARY\]' || { echo "[!] нет сводки FULL-SCAN"; exit 1; }
echo "$FS" | grep -q '\[anti-cheat\] python-файлов' || { echo "[!] anti-cheat не запускался в full-scan"; exit 1; }
echo "$FS" | grep -q '\[AUTO-ROUTE\]' || { echo "[!] авто-роутинг не сработал"; exit 1; }
echo "$FS" | grep -q 'НЕ проверено' || { echo "[!] роутинг НЕ помечен как 'не проверено' (риск выдать за доказательство)"; exit 1; }
echo "$FS" | grep -q 'без контрактов НЕ доказывались' || { echo "[!] нет честной оговорки в сводке"; exit 1; }
echo "[OK] full-scan: xray + anti-cheat + авто-роутинг, и роутинг честно помечен как НЕ доказанный"

# ДЕФЕКТ #381: ГРАНИЦА ПО РАСШИРЕНИЯМ БЫЛА МОЛЧАЛИВОЙ. Второй список
# «известного» (`_XRAY_EXTS`) разошёлся с первым (`CLIKE_EXT`): парсер C++
# УМЕЛ, а `--xray` выбрасывал `.cpp`/`.cc` молча, и строка «файлов к
# сканированию: N» читалась как «в каталоге N файлов». На официальном
# датасете Meta это скрыло 46% файлов (876 из 1916).
#
# Проверяется ДВУСТОРОННЕ:
#   (а) `.cpp`/`.cc` ОБЯЗАНЫ сканироваться (набор = CLIKE_EXT | {.py});
#   (б) `.cs`/`.java`/`.php` ОБЯЗАНЫ быть НАЗВАНЫ в отчёте о пропуске.
EXT=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_exts 2>&1) || { echo "[!] --xray на фикстуре расширений упал"; exit 1; }
echo "$EXT" | grep -q 'файлов к сканированию: 4' || { echo "[!] #381: .cpp/.cc НЕ сканируются (набор разошёлся с CLIKE_EXT)"; echo "$EXT" | grep -E 'к сканированию|ПРОПУЩЕНО'; exit 1; }
echo "$EXT" | grep -q 'ПРОПУЩЕНО по расширению: 3' || { echo "[!] #381: пропуск по расширению НЕ назван (молчаливая потеря)"; exit 1; }
for e in '.cs:1' '.java:1' '.php:1'; do
  echo "$EXT" | grep -q -- "$e" || { echo "[!] #381: расширение $e не названо в отчёте"; exit 1; }
done
echo "[OK] #381: .cpp/.cc сканируются, .cs/.java/.php НАЗВАНЫ (молчаливой потери нет)"

# ДЕФЕКТ #400: ПРИЧИНЫ ПРОПУСКА C-like ОБЯЗАНЫ ПЕЧАТАТЬСЯ.
# Сводка заявляла «skipped N with explicit reasons», но НИ ОДНОЙ причины не
# выводила: `_xray_clike_file` их не возвращал. Проверка ДВУСТОРОННЯЯ (в гейте):
# счётчик == сумма причин И позитивный контроль `checked >= 1`.
python3 tools/xray_skip_reasons_check.py || { echo "[!] #400: причины пропуска не напечатаны или не сходятся"; exit 1; }
python3 tools/xray_skip_reasons_check.py --selftest || { echo "[!] #400: мета-тест ворот не прошёл"; exit 1; }
echo "[OK] #400: причины пропуска C-like печатаются и сходятся со счётчиком"

# ТАКТ 2.2 (#405/#407.2): ИНВАРИАНТ ВОРОНКИ ПОД КОНТРАКТОМ САМОГО KERN.
# `checked + trivial + skipped == total` и `named <= skipped` записаны как
# `@kern:requires`/`@kern:ensures` в `tools/funnel_accounting.py`, доказаны тем же
# движком, что проверяет чужой код, и запечатаны в `docs/contracts.lock.json`.
# Гейт требует, чтобы ослабленные двойники были ОПРОВЕРГНУТЫ (иначе доказательство
# вакуумно), и возвращает rc=3 вместо зелени, если решателя нет: «инструмент не
# запущен» — это N, а не T (#407).
python3 tools/funnel_contract_check.py --selftest || { echo "[!] такт 2.2: мета-тест ворот воронки не прошёл"; exit 1; }
python3 tools/funnel_contract_check.py || { echo "[!] такт 2.2: инвариант воронки НЕ доказан или двойник не опровергнут"; exit 1; }
echo "[OK] такт 2.2: воронка доказана своим же движком, двойники опровергнуты, контракты запечатаны"

# ДЕФЕКТ #401: ВЗАИМОИСКЛЮЧАЮЩИЕ ВЕТВИ НЕ ДАЮТ ЛОЖНЫЙ [DEAD BRANCH].
# Двусторонне: (а) на ветвях с ранними `return` находок НЕТ;
#              (б) на ДЕЙСТВИТЕЛЬНО мёртвом условии находка ЕСТЬ.
NB=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_nested_branches.c 2>&1) || true
if echo "$NB" | grep -q 'DEAD BRANCH'; then
  echo "[!] #401: ЛОЖНЫЙ [DEAD BRANCH] на взаимоисключающих ветвях"; echo "$NB" | grep 'DEAD BRANCH'; exit 1
fi
TD=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_true_dead.c 2>&1) || true
echo "$TD" | grep -q 'DEAD BRANCH. truly_dead' || { echo "[!] #401: НАСТОЯЩАЯ мёртвая ветвь НЕ найдена (тихое подавление)"; exit 1; }
echo "[OK] #401: ложный DEAD BRANCH на взаимоисключающих ветвях убран, настоящий — найден"

# ШАГ 4 ПЛАНА (класс #178/#183): СВОБОДНАЯ КОНСТАНТА В ПУТИ НЕ ДАЁТ ОБВИНЕНИЯ.
# ИЗМЕРЕНО до правки: корректный `if (n < LIMIT) return n + n;` давал
# `[OVERFLOW PATH] … [КОНТРПРИМЕР] LIMIT_UNDEFINED = -2147483647, n = -2147483648`:
# Z3 подбирал значение НЕИЗВЕСТНОЙ константы, и обвинение было ЛОЖНЫМ.
# Проверка ДВУСТОРОННЯЯ: находки быть не должно И отказ обязан быть НАЗВАН —
# иначе это не отказ, а молчаливый пропуск (урок #178/#183).
FP=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_free_path.c 2>&1) || true
if echo "$FP" | grep -q 'OVERFLOW PATH'; then
  echo "[!] шаг 4: ЛОЖНОЕ обвинение на корректном коде (свободная константа в пути)"
  echo "$FP" | grep 'OVERFLOW PATH'; exit 1
fi
echo "$FP" | grep -q 'путь зависит от неизвестной константы' || { echo "[!] шаг 4: отказ НЕ назван — молчаливый пропуск"; exit 1; }
echo "[OK] шаг 4: свободная константа в пути -> ОТКАЗ с названной причиной, ложного обвинения нет"

# ШАГ 5 ПЛАНА: ТЕРНАРНИК ПЕРЕВОДИТСЯ, А `?.`/`??` — НЕ ТЕРНАРНИКИ.
# ИЗМЕРЕНО до правки (корпус `actions/toolkit`): `obj?.field` и `a ?? b` считались
# тернарниками БЕЗ `:`, поэтому функция уходила в SKIP («тернарный оператор»);
# вложенный тернарник `a ? b ? c : d : e` разбирался неверно и тоже ронял перевод.
# Проверка ТРЁХ сторонняя: (1) причина «тернарный оператор» исчезла; (2) функция
# РАЗОБРАНА; (3) САМ перевод верен — вложенность даёт ДВА `ite`, а `?.`/`??`
# остаются нетронутыми (иначе мы бы «починили» причину, сломав семантику).
TN=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_ternary.ts 2>&1) || true
if echo "$TN" | grep -q 'тернарный оператор'; then
  echo "[!] шаг 5: `?.`/`??`/тернарник снова считаются ошибкой перевода"
  echo "$TN" | grep 'тернарный оператор'; exit 1
fi
echo "$TN" | grep -qE 'buckets: checked 1 \| trivial 0 \| skipped 0' \
  || { echo "[!] шаг 5: функция с тернарником НЕ разобрана"; echo "$TN" | tail -6; exit 1; }
python3 - <<'PY' || { echo "[!] шаг 5: перевод тернарника неверен"; exit 1; }
import sys
sys.path.insert(0, "tools")
import kern_contracts as K
nested = K.convert_ternary("a ? b ? c : d : e")
assert nested.count(" if ") == 2, nested          # ДВА ite: вложенность разобрана
assert K.convert_ternary("x?.a ?? 0") == "x?.a ?? 0"  # НЕ тернарник
assert K.convert_ternary("a > 0 ? a : b") != "a > 0 ? a : b"
PY
echo "[OK] шаг 5: тернарник -> ite (вложенный тоже), опциональная цепочка и nullish - НЕ тернарники"

# ШАГ 6 ПЛАНА: УКАЗАТЕЛЬ = Int, ГДЕ 0 = NULL. ДВУСТОРОННИЙ контроль.
# ИЗМЕРЕНО до правки: ЛЮБОЕ условие со словом `nil/null` отбрасывалось целиком
# (дефект #197), это стоило 49 функций в `cmark-gfm/src` и 3 в `toolkit`; а форма
# `!p` вообще не переписывалась (нет слова `nil`) и уходила в SKIP как «синтаксис».
# Проверяются ТРИ свойства, и каждое ИЗМЕРЕНО:
#   1) противоречие БЕЗ мутации -> [DEAD BRANCH] НАЙДЕНА;
#   2) форма `!p` переведена (ловушка сортов Z3: `not p` над Int недопустим);
#   3) МУТАЦИЯ указателя между проверками -> находок НЕТ (иначе ложное обвинение).
NP=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_null_ptr.c 2>&1) || true
echo "$NP" | grep -q 'DEAD BRANCH] null_twice' \
  || { echo "[!] шаг 6: противоречие БЕЗ мутации НЕ найдено (тихое подавление)"; echo "$NP" | tail -5; exit 1; }
echo "$NP" | grep -q 'DEAD BRANCH] bang_twice' \
  || { echo "[!] шаг 6: форма \`!p\` не переведена (ловушка сортов Z3)"; echo "$NP" | tail -5; exit 1; }
if echo "$NP" | grep -q 'DEAD BRANCH] null_after_mutation'; then
  echo "[!] шаг 6: ЛОЖНАЯ мёртвая ветвь при МУТАЦИИ указателя"
  echo "$NP" | grep 'null_after_mutation'; exit 1
fi
echo "[OK] шаг 6: без мутации DEAD BRANCH найдена, с мутацией находок нет, форма !p переведена"
