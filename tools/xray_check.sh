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
