#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
python3 tools/xray_asi_check.py || exit 1  # регрессия: ASI-стиль TS без `;`
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
# #454: неопределённость длины -> ЗАМЕТКА `note: [BOUNDS?]`, а НЕ находка.
echo "$BOUNDS" | grep -q 'note: \[BOUNDS?\] get_unknown_len' || { echo "[!] нет честного 'длина неизвестна' (заметка #454)"; exit 1; }
if echo "$BOUNDS" | grep -qE '^\s*\[BOUNDS\?\] get_unknown_len'; then echo "[!] #454: неопределённость печатается как НАХОДКА"; exit 1; fi
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

# ДЕФЕКТ #468a/#468c: `assert` — ПУТЕВОЙ ГАРД, а не комментарий (и составные
# `try`/`with` его НЕ теряют). Проверка ДВУСТОРОННЯЯ: под `assert` обвинять
# НЕЛЬЗЯ, но `get_unsafe` выше обязан остаться обвинённым — то есть подавления
# «за компанию» нет (иначе гейт доказывал бы лишь то, что детектор ослеп).
for fn in get_assert_guard get_set_assert_guard get_try_assert_guard; do
  if echo "$BOUNDS" | grep -q "BOUNDS PATH\\] $fn"; then
    echo "[!] ЛОЖНОЕ ОБВИНЕНИЕ $fn (#468: assert как гард не учтён / try потерял гард)"; exit 1
  fi
done
echo "[OK] #468: assert как путевой гард (в т.ч. len(set(x)) и внутри try) ложных BOUNDS PATH не даёт"
# АКСИОМА МОЩНОСТИ: `assert len(set(x)) == 1` СТРОГО влечёт `len(x) >= 1`, поэтому
# `x[0]` безопасен. Без аксиомы длина `x` остаётся НЕИЗВЕСТНОЙ (заметка #454), то
# есть проверка НЕ выполнена — это НЕ «зелено». Гейт требует ИМЕННО проверки.
if echo "$BOUNDS" | grep -q 'BOUNDS?\] get_set_assert_guard'; then
  echo "[!] #468a: аксиома |set(x)| <= len(x) НЕ применена (assert len(set(x))==1 не сузил путь)"; exit 1
fi
echo "[OK] #468a: аксиома мощности конечного множества применена (get_set_assert_guard ПРОВЕРЕН, а не отложен)"

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

# ДЕФЕКТ #501b: stdint + C INTEGER PROMOTION + unsigned WRAP.
# Единый предикат пробоя (index_expr < 0 в Int-модели), но ТРИ диагноза:
#   A знаковые (int64_t)      -> «индекс может быть отрицательным»;
#   B узкие беззнаковые в C   -> «ЧЕРЕЗ INTEGER PROMOTION (C11 §6.3.1.1)»;
#   C широкие беззнаковые и все беззнаковые Rust/Zig -> «unsigned underflow/wrap».
# Двусторонность: без гарда `i - 1` ОБВИНЯЕТСЯ, под `if (i < 1)` — МОЛЧИТ.
cat > "$TMPC/st_int64.c" <<'CEOF'
int get_a(int64_t *b, int64_t i)
{
    return (int)b[i - 1];
}
CEOF
cat > "$TMPC/st_u8.c" <<'CEOF'
int get_b(uint8_t *b, uint8_t i)
{
    return b[i - 1];
}
int get_b_ok(uint8_t *b, uint8_t i)
{
    if (i < 1) { return 0; }
    return b[i - 1];
}
CEOF
cat > "$TMPC/st_size.c" <<'CEOF'
int get_c(size_t *b, size_t i)
{
    return (int)b[i - 1];
}
int get_c_ok(size_t *b, size_t i)
{
    if (i < 1) { return 0; }
    return (int)b[i - 1];
}
CEOF
cat > "$TMPC/st_u8.rs" <<'CEOF'
fn get_r(b: &[u8], i: u8) -> u8
{
    b[i - 1]
}
CEOF
S1=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/st_int64.c" 2>&1) || true
echo "$S1" | grep -q 'BOUNDS PATH. get_a' || { echo "[!] #501b A: int64_t b[i-1] без гарда НЕ обвинён (тип снова «НЕИЗВЕСТЕН»)"; exit 1; }
if echo "$S1" | grep -q 'НЕИЗВЕСТЕН'; then echo "[!] #501b A: int64_t всё ещё уходит в скип «тип НЕИЗВЕСТЕН»"; exit 1; fi
S2=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/st_u8.c" 2>&1) || true
echo "$S2" | grep -q 'INTEGER PROMOTION' || { echo "[!] #501b B: uint8_t i-1 не назван INTEGER PROMOTION (C11 §6.3.1.1)"; exit 1; }
if echo "$S2" | grep -q 'BOUNDS PATH. get_b_ok'; then echo "[!] #501b B: ЛОЖНОЕ обвинение uint8_t под if (i < 1) return"; exit 1; fi
S3=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/st_size.c" 2>&1) || true
echo "$S3" | grep -q 'wrap-around' || { echo "[!] #501b C: size_t i-1 не назван unsigned underflow/wrap-around"; exit 1; }
if echo "$S3" | grep -q 'BOUNDS PATH. get_c_ok'; then echo "[!] #501b C: ЛОЖНОЕ обвинение size_t под if (i < 1) return"; exit 1; fi
S4=$(timeout 300 python3 tools/kern_contracts.py --xray "$TMPC/st_u8.rs" 2>&1) || true
if echo "$S4" | grep -q 'INTEGER PROMOTION'; then echo "[!] #501b: u8 в Rust/Zig назван INTEGER PROMOTION — promotion это свойство C, не Rust"; exit 1; fi
echo "[OK] #501b: int64_t -> A, uint8_t -> INTEGER PROMOTION (B), size_t -> wrap-around (C), гард молчит; u8 в Rust — НЕ promotion (7/7)"

# ДЕФЕКТ #667: ранний выход снимает ложное обвинение переполнения, НО переприсваивание
# гард сбрасывает. Три случая, все три обязательны (третий ловит «ослепление» детектора).
cat > "$TMPC/ovf_guard_a.c" <<'CEOF'
int f_a(int w)
{
    if (w < 0) { w = -w; }
    return w;
}
CEOF
cat > "$TMPC/ovf_guard_b.c" <<'CEOF'
int f_b(int w)
{
    if (w < -15) { return -2; }
    if (w < 0) { w = -w; }
    return w;
}
CEOF
cat > "$TMPC/ovf_guard_c.c" <<'CEOF'
int f_c(int w, int y)
{
    if (w < -15) { return -2; }
    w = y;
    if (w < 0) { w = -w; }
    return w;
}
CEOF
G1=$(timeout 240 python3 tools/kern_contracts.py --xray "$TMPC/ovf_guard_a.c" 2>&1) || true
echo "$G1" | grep -q 'OVERFLOW PATH. f_a' || { echo "[!] #667: без гарда -w НЕ обвинён (детектор ослеп)"; exit 1; }
G2=$(timeout 240 python3 tools/kern_contracts.py --xray "$TMPC/ovf_guard_b.c" 2>&1) || true
if echo "$G2" | grep -q 'OVERFLOW PATH. f_b'; then echo "[!] #667: ЛОЖНОЕ обвинение -w после if (w < -15) return"; exit 1; fi
G3=$(timeout 240 python3 tools/kern_contracts.py --xray "$TMPC/ovf_guard_c.c" 2>&1) || true
echo "$G3" | grep -q 'OVERFLOW PATH. f_c' || { echo "[!] #667: переприсваивание w = y НЕ сбросило гард — детектор ослеп"; exit 1; }
printf 'int f_d(int w){\n    if (w < -MAXWB) { return -2; }\n    if (w < 0) { w = -w; }\n    return w;\n}\n' > "$TMPC/ovf_guard_d.c"
G4=$(timeout 240 python3 tools/kern_contracts.py --xray "$TMPC/ovf_guard_d.c" 2>&1) || true
if echo "$G4" | grep -q 'OVERFLOW PATH. f_d'; then echo "[!] #675: гард с МАКРОКОНСТАНТОЙ (-MAXWB) не распознан — ложное обвинение"; exit 1; fi
echo "[OK] #667/#675: ранний выход, сброс гарда и МАКРОКОНСТАНТА (-MAXWB) — 4/4"
# ГРАНИЧНЫЙ СЛУЧАЙ #675 (ревью): `if (w <= INT_MIN) return;` — МЁРТВЫЙ гард, он НЕ
# защищает: при `w = INT_MIN` унарный минус — реальное UB. Такой токен не гасит проверку.
printf 'int f_e(int w){\n    if (w <= INT_MIN) { return -2; }\n    if (w < 0) { w = -w; }\n    return w;\n}\n' > "$TMPC/ovf_guard_e.c"
G5=$(timeout 240 python3 tools/kern_contracts.py --xray "$TMPC/ovf_guard_e.c" 2>&1) || true
echo "$G5" | grep -q 'OVERFLOW PATH. f_e' || { echo "[!] #675: мёртвый гард с INT_MIN погасил проверку -w (ослепление)"; exit 1; }
echo "[OK] #675: INT_MIN-гард не считается защитой (5/5)"

# ДЕФЕКТ #672: срез рейда не должен включать НЕ-БОЕВЫЕ каталоги, НО явно запрошенный
# каталог фикстур обязан сканироваться. Двусторонность: (а) при обходе КОРНЯ
# вложенный `tests/` отсекается, (б) при ЯВНОМ пути внутрь `tests/` файлы читаются.
# Иначе говоря: фильтр режет `dirnames` (детей корня), а не сам `root`.
mkdir -p "$TMPC/hunt_root/tests/deep" "$TMPC/hunt_root/src"
printf 'int g(int *b, int i){\n    return b[i - 1];\n}\n' > "$TMPC/hunt_root/tests/deep/t.c"
printf 'int h(int *b, int j){\n    return b[j - 1];\n}\n' > "$TMPC/hunt_root/src/s.c"
H1=$(timeout 240 python3 tools/kern_contracts.py --xray "$TMPC/hunt_root" 2>&1) || true
echo "$H1" | grep -q 'файлов к сканированию: 1' || { echo "[!] #672: при обходе корня вложенный tests/ НЕ отсечён"; exit 1; }
if echo "$H1" | grep -q 'BOUNDS PATH. g'; then echo "[!] #672: находка из tests/ просочилась в срез рейда"; exit 1; fi
H2=$(timeout 240 python3 tools/kern_contracts.py --xray "$TMPC/hunt_root/tests" 2>&1) || true
echo "$H2" | grep -q 'BOUNDS PATH. g' || { echo "[!] #672: ЯВНЫЙ путь внутрь tests/ не сканируется (ослепление фикстур)"; exit 1; }
echo "[OK] #672: вложенный tests/ отсекается при обходе корня, явный путь — сканируется (2/2)"

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
echo "$EXT" | grep -q 'файлов к сканированию: 5' || { echo "[!] #381/#468b: .cpp/.cc/.hpp НЕ сканируются (набор разошёлся с CLIKE_EXT)"; echo "$EXT" | grep -E 'к сканированию|ПРОПУЩЕНО'; exit 1; }
echo "$EXT" | grep -q 'ПРОПУЩЕНО по расширению: 3' || { echo "[!] #381: пропуск по расширению НЕ назван (молчаливая потеря)"; exit 1; }
# ДЕФЕКТ #468b: `.hpp` — не «бонус», а РЕГРЕССИЯ ЯДРА ИИ-инфраструктуры: ядро
# `deepseek-ai/DeepJIT` (C++20, header-only) — 53 файла `.hpp`, которые `--xray`
# не видел ВООБЩЕ. Проверка ДВУСТОРОННЯЯ: файл обязан быть И посчитан
# («к сканированию»), И РЕАЛЬНО РАЗОБРАН (находка на нём), а не просто учтён.
echo "$EXT" | grep -q 'h\.hpp: \[OVERFLOW PATH\] f_hpp' || { echo "[!] #468b: .hpp посчитан, но НЕ разобран (граница расширений молчалива)"; exit 1; }
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

# ДЕФЕКТ #514: ВТОРОЙ КОНТРОЛЬ #401, НЕЗАВИСИМЫЙ ОТ `#503`.
# ЗАМЕР (canfail в CI): кейс `xray-nested-branch` стал ВАКУУМНЫМ — при снятой
# области ветви обе проверки выше остались ЗЕЛЁНЫМИ. Причина: фикстура
# `xray_nested_branches.c` целиком лежит внутри `switch`, а `#503` НАМЕРЕННО
# гасит вердикт «мёртвая ветвь» внутри `switch` с двумя и более `case`. То есть
# один честный предохранитель заглушил доказательство другого.
# Здесь тот же класс воспроизведён БЕЗ `switch`: при снятой области ветви
# появляется ЛОЖНЫЙ `[DEAD BRANCH] (< v 160)` — проверено, гейт краснеет.
NBIF=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_nested_branches_if.c 2>&1) || true
if echo "$NBIF" | grep -q 'DEAD BRANCH'; then
  echo "[!] #401/#514: ЛОЖНЫЙ [DEAD BRANCH] на взаимоисключающих ветвях ВНЕ switch"
  echo "$NBIF" | grep 'DEAD BRANCH'; exit 1
fi
echo "[OK] #401: ложный DEAD BRANCH на взаимоисключающих ветвях убран, настоящий — найден (в т.ч. вне switch, #514)"

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
# ШАГ 4b (BV): БИТОВЫЕ УСЛОВИЯ — ДВУСТОРОННИЙ КОНТРОЛЬ.
# Int-теория битовых операторов не знает, поэтому битовые условия уходили в SKIP.
# Теперь они переводятся в QF_BV32, и это надо проверять С ДВУХ СТОРОН, иначе
# «починка» превращается в бутафорию:
#   1) ПОЗИТИВНЫЙ: битовая мёртвая ветка обязана быть НАЙДЕНА. В Int-модели она
#      невидима ВООБЩЕ: младшие два бита нулевые => `(x & 3) != 0` недостижимо;
#   2) НЕГАТИВНЫЙ (защита от ЛОЖНОГО обвинения): `x > 0 && x + 1 < 0` в ℤ
#      невыполнимо, и Int-путь объявлял ветку мёртвой. В C при `x = INT_MAX`
#      перенос делает её ЖИВОЙ. Перекрёстная проверка в BV32 обязана снять
#      обвинение И НАЗВАТЬ это заметкой (молчаливое снятие = тихая потеря).
BVD=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_bv_bits.c 2>&1) || true
echo "$BVD" | grep -q 'DEAD BRANCH] bit_dead'   || { echo "[!] шаг 4b: битовая мёртвая ветка НЕ найдена (BV не работает)"; echo "$BVD" | tail -5; exit 1; }
echo "$BVD" | grep -q 'BV32'   || { echo "[!] шаг 4b: находка есть, но НЕ из BV-маршрута"; exit 1; }
BVW=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_bv_wrap.c 2>&1) || true
if echo "$BVW" | grep -q 'DEAD BRANCH'; then
  echo "[!] шаг 4b: ЛОЖНОЕ обвинение на переносе (x = INT_MAX делает ветку живой)"
  echo "$BVW" | grep 'DEAD BRANCH'; exit 1
fi
echo "$BVW" | grep -q 'ветка достижима в BV32'   || { echo "[!] шаг 4b: обвинение снято МОЛЧА (нет названной причины)"; echo "$BVW" | tail -5; exit 1; }
echo "[OK] шаг 4b: битовая мёртвая ветка найдена в BV32, ложное обвинение на переносе снято с причиной"

# ДЕФЕКТ #410: РАЗБОРЩИК ФУНКЦИЙ НЕ ВЫДУМЫВАЕТ ФУНКЦИИ ИЗ ВЫЗОВОВ.
# ИЗМЕРЕНО до правки: в `.ts`-файле группы брались по СУФФИКСУ файла, а не по
# сработавшей регулярке, и запасная `RE_FN_C` ловила ВЫЗОВЫ (`await stat(p)`,
# `throw new Error(...)`) — на 458 «функциях» корпуса `actions/toolkit` 308 были
# вызовами, а тело «функции» нарезалось из середины файла (отсюда ЛОЖНОЕ
# обвинение `io-util.ts: readlink: (= p 0)`).
# Контроль НЕВАКУУМНЫЙ и ИЗМЕРЕН на обе стороны: на коммите до правки (`20adf31`)
# та же фикстура даёт `Σ 3 == total 3` (две выдуманные функции), после — `Σ 1`.
TS_CALLS=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_ts_calls.ts 2>&1) || true
echo "$TS_CALLS" | grep -qE 'buckets: checked 1 \| trivial 0 \| skipped 0 \| Σ 1 == total 1' \
  || { echo "[!] #410: вызовы снова считаются функциями (total != 1)"; echo "$TS_CALLS" | tail -6; exit 1; }
if echo "$TS_CALLS" | grep -q 'DEAD BRANCH'; then
  echo "[!] #410: ЛОЖНАЯ мёртвая ветвь на вызовах внутри async-функции"
  echo "$TS_CALLS" | grep 'DEAD BRANCH'; exit 1
fi
echo "[OK] #410: await/throw new — ВЫЗОВЫ, а не функции (Σ 1 == total 1), ложной мёртвой ветви нет"


# ДЕФЕКТ #454: НЕОПРЕДЕЛЁННОСТЬ НЕ ЯВЛЯЕТСЯ НАХОДКОЙ.
# Маркер `[BOUNDS]` (индекс в список НЕИЗВЕСТНОЙ длины) шёл в находки, хотя его
# собственный текст — «границы НЕ проверены», то есть Белнап N, а не вердикт.
# ИЗМЕРЕНО на QuixBugs (`correct_python_programs`, SHA 4257f44b): 81 «находка»
# против 80 на багованном корпусе — сигнала НЕТ, а чистый код обвиняется.
# Теперь это ЗАМЕТКА (`note: [BOUNDS?]`), находкой остаётся только `[BOUNDS PATH]`.
# Контроль двусторонний: заметка ОБЯЗАНА быть, находок ОБЯЗАНО не быть.
BOUNDS_UNK=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_bounds_unknown.py 2>&1) || true
echo "$BOUNDS_UNK" | grep -q 'BOUNDS?' \
  || { echo "[!] #454: неопределённость длины вообще не названа"; echo "$BOUNDS_UNK" | tail -5; exit 1; }
echo "$BOUNDS_UNK" | grep -qE 'findings 0' \
  || { echo "[!] #454: неопределённость снова считается НАХОДКОЙ"; echo "$BOUNDS_UNK" | tail -5; exit 1; }
echo "$BOUNDS_UNK" | grep -qE 'note: \[BOUNDS\?\]' \
  || { echo "[!] #454: маркер не переведён в класс ЗАМЕТКИ (note:)"; echo "$BOUNDS_UNK" | tail -5; exit 1; }
# ДЕФЕКТ #469b: заметкой обязана быть и неопределённость ВНУТРИ ТЕЛА `while`.
# ИЗМЕРЕНО на `deepseek-ai/DeepJIT` (`tests/test_ascend.py:162`): рекурсивный
# обход ТЕЛА `while` не передавал `notes`, падал в `found` — и `findings`
# считал статус Белнапа N за находку F. Проверка НЕВАКУУМНА: требует, чтобы
# заметка пришла ИМЕННО из тела цикла (`drain`), а не только из тела функции.
echo "$BOUNDS_UNK" | grep -q 'note: \[BOUNDS?\] drain' \
  || { echo "[!] #469b: неопределённость ВНУТРИ while не названа заметкой (тело цикла теряет notes)"; echo "$BOUNDS_UNK" | tail -5; exit 1; }
echo "$BOUNDS_UNK" | grep -qE '\[BOUNDS\?\] drain' \
  || { echo "[!] #469b: случай `drain` (while) вообще не достигнут — гейт пуст"; echo "$BOUNDS_UNK" | tail -5; exit 1; }
echo "[OK] #454: неопределённость длины = ЗАМЕТКА (N), а не находка (findings 0), в т.ч. в теле while (#469b)"


# ДЕФЕКТЫ #471a/#471b/#471c и #472: ГАРДЫ И ВЕЩЕСТВЕННЫЕ ТИПЫ.
# Три ложных класса, измеренных на TheAlgorithms/Rust и QuixBugs:
#   #471a — Python: скан ветви THEN шёл по ВСЕМУ `ast.If`, поэтому `orelse`
#           получал ПРЯМОЙ гард вместо `(not cond)`;
#   #471b — C-like: тело `while` анализировалось БЕЗ условия цикла (Евклид);
#   #471c — C-like: `else`-ветвь не получала `(not cond)` вообще;
#   #472  — `f32`/`f64` молча уносились в `i64`, и `debt / equity` объявлялось
#           паникой, хотя IEEE-754 даёт inf/NaN.
# Гейт ДВУСТОРОННИЙ: 4 «молчащие» функции обязаны исчезнуть из находок, а
# 3 настоящие ошибки — ОСТАТЬСЯ (иначе «починка» была бы глушением).
GUARDS=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_crash_guards 2>&1) || true
# Сводка печатает по-русски: `| находок N | нечитаемых`. Анкер ДОЛЖЕН совпадать
# с фактическим форматом — иначе гейт краснел бы «на пустом месте» (проверено).
echo "$GUARDS" | grep -qE 'находок 3 \|' \
  || { echo "[!] #471/#472/#473: ожидали РОВНО 3 находки (TP-контроли)"; echo "$GUARDS" | grep -E 'REPO SUMMARY|\[\w' | tail -8; exit 1; }
echo "$GUARDS" | grep -qE '\[CRASH PATH\] gcd_unguarded' \
  || { echo "[!] #471a: TP-контроль мёртв — незащищённое деление больше НЕ ловится"; exit 1; }
echo "$GUARDS" | grep -qE '\[BOUNDS PATH\] arr_unguarded' \
  || { echo "[!] #473: TP-контроль мёртв — выход за границы больше НЕ ловится"; exit 1; }
echo "$GUARDS" | grep -qE '\[CRASH PATH\] ratio_i64' \
  || { echo "[!] #472: TP-контроль мёртв — целочисленное деление на ноль больше НЕ ловится"; exit 1; }
if echo "$GUARDS" | grep -qE '\[CRASH PATH\] (gcd_guarded|gcd_no_else|gcd_while_rust|gcd_else_rust|ratio_f64)'; then
  echo "[!] #471/#472: ВЕРНУЛОСЬ ложное обвинение защищённого кода"
  echo "$GUARDS" | grep -E '\[CRASH PATH\] (gcd_guarded|gcd_no_else|gcd_while_rust|gcd_else_rust|ratio_f64)'
  exit 1
fi
echo "$GUARDS" | grep -qE 'skip: вещественная арифметика.*QF_FP' \
  || { echo "[!] #472: вещественная функция не помечена НАЗВАННЫМ пропуском"; echo "$GUARDS" | tail -5; exit 1; }
echo "$GUARDS" | grep -qE 'note: \[BOUNDS\?\] index_after_loop' \
  || { echo "[!] #473: индекс после цикла не назван заметкой (N)"; echo "$GUARDS" | tail -6; exit 1; }
if echo "$GUARDS" | grep -qE '\[(BOUNDS PATH|BOUNDS UNKNOWN|CRASH PATH)\] index_after_loop'; then
  echo "[!] #473: N СНОВА считается находкой"
  exit 1
fi
echo "[OK] #471a/b/c: гарды else/while учитываются; #472: f64 -> названный SKIP; #473: N = заметка (findings 3 = 3 TP)"


# #491: НА СВОЁМ ЯДРЕ НЕ ДОЛЖНО БЫТЬ «ВНУТРЕННИХ ОШИБОК» В ОТЧЁТЕ.
# Измерено: 321 строка `[!] BV-форма условия: внутренняя ошибка при живом replay`
# (279 Call, 27 SyntaxError, 8 Subscript, 7 Attribute) выглядела как авария
# инструмента там, где анализатор честно не взялся. Теперь это ОДНА заметка.
echo "[#491] внутренние ошибки при аудите собственного ядра:"
_SELF_ERR=$(
  cd "$ROOT" && ( ulimit -v 6291456; timeout 900 python3 tools/kern_contracts.py --xray src 2>&1 >/dev/null ) \
    | grep -c 'внутренняя ошибка' || true
)
if [ "${_SELF_ERR:-0}" -eq 0 ]; then
  echo "  [OK] #491: 0 строк «внутренняя ошибка» на kern/src (штатные отказы — в заметке)"
else
  echo "  [!] #491: ${_SELF_ERR} строк «внутренняя ошибка» на kern/src — штатный выход за подмножество снова выдан за аварию"
  FAIL=$((FAIL + 1))
fi

# РЕГРЕССИЯ #699 (нашёл `tools/run_time_machine.py` на РЕАЛЬНОМ коде more-itertools):
# `ast.unparse` среза даёт `":n"` — не выражение, и `ast.parse(mode="eval")` падал
# SyntaxError на ЛЮБОМ срезе, то есть --xray обрывался вместо анализа. Проверяем
# двусторонне: (1) падения НЕТ, (2) обе функции просканированы, (3) деление на ноль
# в функции со срезом ЛОВИТСЯ (иначе «починка» просто заглушила бы детектор).
SLZ=$(timeout 300 python3 tools/kern_contracts.py --xray tests/fixtures/xray_slice_zero.py 2>&1) || true
if echo "$SLZ" | grep -q 'SyntaxError'; then
  echo "[!] #699: --xray ВСЁ ЕЩЁ падает на срезе (SyntaxError)"; exit 1
fi
echo "$SLZ" | grep -q 'checked 2 / 2 functions' || { echo "[!] #699: срезы не просканированы (checked != 2/2)"; exit 1; }
echo "$SLZ" | grep -q 'CRASH PATH\] head_ratio' || { echo "[!] #699: деление на ноль за срезом НЕ поймано"; exit 1; }
echo "$SLZ" | grep -q 'CRASH PATH\] tail_ratio' || { echo "[!] #699: срез с двумя границами не проанализирован"; exit 1; }
echo "[OK] #699: срезы анализируются (2/2 функции), деление на ноль поймано в обеих"
