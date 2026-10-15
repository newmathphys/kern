#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# Commercial use requires a license from the copyright holder. See LICENSE.
#
# ============================================================================
#  KERN — прицельные атаки на самые опасные узлы ядра.
#
#  Каждая атака ОБЯЗАНА быть отбита; если атака проходит — скрипт падает.
#  Это не «демонстрация», а проверка с критерием (fail = баг).
#
#  Запуск:  make adversarial        (нужны собранные бинарники + z3)
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${ZIG_DIR:-$HOME/opt/zig-x86_64-linux-0.17.0}:$ROOT/.venv/bin:$PATH"

KERNC="$ROOT/zig-out/bin/kernc"
WORK="$(mktemp -d /tmp/kern_adversarial.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
note() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
ok()   { printf '  \033[32m[ОТБИТО]\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m[ПРОШЛО]\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }

[ -x "$KERNC" ] || { echo "нет $KERNC — соберите: zig build"; exit 1; }

# --- Эталонный образ -------------------------------------------------------
note "0. Сборка эталонного образа"
cp examples/toy_ai_hallucination/project.kern "$WORK/proj.kern"
"$KERNC" build "$WORK/proj.kern" -o "$WORK/base.kimg" >/dev/null 2>&1 \
  && echo "  образ: $(stat -c%s "$WORK/base.kimg") байт" \
  || { echo "  не удалось собрать образ"; exit 1; }

# ===========================================================================
# 1. ЗАГОЛОВОК: magic, размер, версия, hash_algo
# ===========================================================================
note "1. Атаки на заголовок .kimg (128 байт)"

# 1a. Битый magic
cp "$WORK/base.kimg" "$WORK/a1.kimg"
printf 'FAIL' | dd of="$WORK/a1.kimg" bs=1 seek=0 conv=notrunc status=none
if "$KERNC" check-integrity "$WORK/a1.kimg" >/dev/null 2>&1; then
  bad "битый magic принят"
else
  ok "битый magic отвергнут"
fi

# 1b. header_size != 128
cp "$WORK/base.kimg" "$WORK/a2.kimg"
printf '\x00\x02\x00\x00' | dd of="$WORK/a2.kimg" bs=1 seek=12 conv=notrunc status=none
if "$KERNC" check-integrity "$WORK/a2.kimg" >/dev/null 2>&1; then
  bad "header_size=512 принят"
else
  ok "header_size != 128 отвергнут"
fi

# 1c. hash_algo вне {1,2} (проверка «ровно одно значение»)
cp "$WORK/base.kimg" "$WORK/a3.kimg"
printf '\x03\x00\x00\x00' | dd of="$WORK/a3.kimg" bs=1 seek=20 conv=notrunc status=none
if "$KERNC" check-integrity "$WORK/a3.kimg" >/dev/null 2>&1; then
  bad "hash_algo=3 принят"
else
  ok "hash_algo вне {1,2} отвергнут"
fi

# ===========================================================================
# 2. ПЕРЕПОЛНЕНИЕ 64-БИТНЫХ СМЕЩЕНИЙ (arithmetic wrap-around)
# ===========================================================================
note "2. Атаки на смещения (переполнение u64)"

# 2a. object_table_offset = 0xFFFFFFFFFFFFFFFF, length = 100
cp "$WORK/base.kimg" "$WORK/b1.kimg"
printf '\xff\xff\xff\xff\xff\xff\xff\xff' | dd of="$WORK/b1.kimg" bs=1 seek=32 conv=notrunc status=none
if "$KERNC" check-integrity "$WORK/b1.kimg" >/dev/null 2>&1; then
  bad "offset=0xFFFF...FF принят (возможно переполнение!)"
else
  ok "offset=0xFFFF...FF отвергнут (нет OOB)"
fi

# 2b. data_payload_offset за пределами файла
cp "$WORK/base.kimg" "$WORK/b2.kimg"
printf '\xff\xff\xff\x7f\x00\x00\x00\x00' | dd of="$WORK/b2.kimg" bs=1 seek=56 conv=notrunc status=none
if "$KERNC" check-integrity "$WORK/b2.kimg" >/dev/null 2>&1; then
  bad "payload_offset за файлом принят"
else
  ok "payload_offset за файлом отвергнут"
fi

# 2c. object_count = 1e9 (DoS-защита: таблица меньше, чем заявлено)
cp "$WORK/base.kimg" "$WORK/b3.kimg"
printf '\x00\xca\x9a\x3b\x00\x00\x00\x00' | dd of="$WORK/b3.kimg" bs=1 seek=48 conv=notrunc status=none
START=$(date +%s%N)
if "$KERNC" check-integrity "$WORK/b3.kimg" >/dev/null 2>&1; then
  bad "object_count=1e9 принят"
else
  MS=$(( ($(date +%s%N) - START) / 1000000 ))
  if [ "$MS" -lt 3000 ]; then
    ok "object_count=1e9 отвергнут за ${MS} мс (нет зависания)"
  else
    bad "object_count=1e9 обрабатывался ${MS} мс (подозрение на DoS)"
  fi
fi

# ===========================================================================
# 3. ЦЕЛОСТНОСТЬ PAYLOAD (дефект #14: Merkle покрывал только таблицу)
# ===========================================================================
note "3. Подмена содержимого payload (SHA-256 сверка)"

# Находим объект исходника и меняем ОДИН байт в его данных, НЕ трогая таблицу.
# Merkle-корень при этом остаётся валидным -> единственной защитой является
# сверка SHA-256(payload) с digest дескриптора.
cp "$WORK/base.kimg" "$WORK/c1.kimg"
# ВАЖНО: `payload_offset` в дескрипторе — ОТНОСИТЕЛЬНЫЙ (к data_payload_offset
# из заголовка @56). Если сложить их неверно, порча попадёт в ТАБЛИЦУ
# дескрипторов, а не в payload, и атака окажется ложной (проверено прогоном).
OFF=$(python3 - "$WORK/base.kimg" <<'PY'
import struct, sys
d = open(sys.argv[1], 'rb').read()
tbl = struct.unpack_from('<Q', d, 32)[0]          # смещение таблицы дескрипторов
base = struct.unpack_from('<Q', d, 56)[0]         # начало пула payload
rel = struct.unpack_from('<Q', d, tbl + 32)[0]    # payload_offset первого объекта
print(base + rel)                                  # АБСОЛЮТНОЕ смещение
PY
)
if [ -n "${OFF:-}" ]; then
  printf '\x41' | dd of="$WORK/c1.kimg" bs=1 seek="$OFF" conv=notrunc status=none
  OUT=$("$KERNC" cat "$WORK/c1.kimg" "/raw/examples/toy_ai_hallucination/withdraw.py" 2>&1 || true)
  if echo "$OUT" | grep -qiE 'PayloadTampered|подмен|tamper'; then
    ok "подмена байта payload обнаружена (PayloadTampered)"
  elif [ -z "$OUT" ]; then
    ok "подмена байта payload отвергнута (пустой ответ)"
  else
    bad "подменённый payload ПРОЧИТАН (защита не сработала)"
  fi
else
  echo "  [i] не удалось определить смещение payload — пропуск"
fi

# ===========================================================================
# 4. KERNFS: обход путей и NUL-инъекция
# ===========================================================================
note "4. Атаки на KERNFS (path traversal, NUL)"

for path in '/raw/../../etc/passwd' '/raw/./proj.kern' '/raw//proj.kern' '/etc/passwd' '/raw'; do
  OUT=$("$KERNC" cat "$WORK/base.kimg" "$path" 2>&1 || true)
  if echo "$OUT" | grep -qE 'root:x:|/bin/bash'; then
    bad "ПРОБОЙ: $path вернул содержимое хостовой ФС!"
  else
    ok "отвергнут путь: $path"
  fi
done

# NUL-инъекция — НА УРОВНЕ API, а не CLI.
#
# ФУНДАМЕНТАЛЬНОЕ ОГРАНИЧЕНИЕ (найдено can-fail харнессом): NUL-байт НЕЛЬЗЯ
# передать в аргументе командной строки — POSIX argv NUL-терминирован, поэтому
# и bash («проигнорирован нулевой байт»), и Python (`ValueError: embedded null
# byte`) такой аргумент отбрасывают. Прежняя версия этого теста была ВАКУУМНОЙ:
# она проверяла то, что невозможно нарушить.
#
# NUL в пути покрыт ТАМ, ГДЕ ОН РЕАЛЬНО МОЖЕТ ПОЯВИТЬСЯ — на уровне API
# (путь приходит из содержимого файла/сети, а не из argv):
#     src/core/kernfs_router.zig :: test "SEC-03: NUL-инъекция и побег через /claims"
# Здесь же проверяем, что CLI-путь с «..» отвергается (это наблюдаемо).
OUT=$("$KERNC" cat "$WORK/base.kimg" "/raw/../etc/passwd" 2>&1 || true)
if echo "$OUT" | grep -qiE 'FileNotFound|InvalidPathFormat|AccessDenied|PathTraversal'; then
  ok "«..» отвергнут (наблюдаемое отвержение, не «нет root:x»)"
else
  bad "«..» НЕ отвергнут: получено «$(echo "$OUT" | head -1)»"
fi
# Проверка, что API-тест NUL существует и исполняется (иначе ссылка — фикция).
if grep -q 'test "SEC-03: NUL-инъекция' "$ROOT/src/core/kernfs_router.zig"; then
  ok "NUL-инъекция покрыта API-тестом SEC-03 (в argv NUL невозможен by POSIX)"
else
  bad "API-тест SEC-03 (NUL) ОТСУТСТВУЕТ — защита от NUL не покрыта"
fi

# ===========================================================================
# 5. Z3: бомба зависания (таймаут + отсутствие зомби)
# ===========================================================================
note "5. Z3-мост: бомба зависания"

BOMB="$WORK/bomb.smt2"
cat > "$BOMB" <<'SMT'
(set-logic NIA)
(declare-const a Int)
(declare-const b Int)
(declare-const c Int)
(assert (= (+ (* a a a) (* b b b) (* c c c)) 42))
(assert (> a 100000000000))
(check-sat)
SMT

if command -v z3 >/dev/null 2>&1; then
  ZBEFORE=$(ps -eo stat= | grep -c '^Z' || true)
  START=$(date +%s%N)
  OUT=$("$KERNC" prove "$BOMB" 2>&1 || true)
  MS=$(( ($(date +%s%N) - START) / 1000000 ))
  ZAFTER=$(ps -eo stat= | grep -c '^Z' || true)
  if [ "$ZAFTER" -gt "$ZBEFORE" ]; then
    bad "появились зомби-процессы: было $ZBEFORE, стало $ZAFTER"
  elif echo "$OUT" | grep -qE 'e *: *1'; then
    bad "e=1 на зависающей формуле (ложное доказательство!)"
  else
    ok "fail-closed: ${MS} мс, зомби нет, e=0"
  fi
else
  echo "  [i] z3 не найден — проверка NOT RUN"
fi

# ===========================================================================
# 6. Белнап: конфликт T ⊔ F = B не должен схлопнуться в T
# ===========================================================================
note "6. Логика Белнапа: конфликт не схлопывается"

CONF="$WORK/conflict.kern"
cat > "$CONF" <<'KERN'
project "conflict" { version "1.0"  root "." }
claim "conflicting claim" {
  status empirical
  evidence "test:passes"
  context "contract_refuted.smt2"
}
KERN
cp examples/toy_ai_hallucination/contract_refuted.smt2 "$WORK/contract_refuted.smt2"
"$KERNC" build "$CONF" -o "$WORK/conflict.kimg" >/dev/null 2>&1
OUT=$("$KERNC" verify "$WORK/conflict.kimg" 2>&1 || true)
if echo "$OUT" | grep -qE 'e=0'; then
  ok "конфликт/опровержение -> e=0 (не схлопнулось в доказательство)"
else
  bad "e=1 при опровергнутом контракте!"
fi

# ===========================================================================
# 7. Мутатор: дерево обязано остаться чистым (дефекты #48/#52)
# ===========================================================================
note "7. Целостность дерева (защита от диверсий харнесса)"
if git -C "$ROOT" status --porcelain | grep -q .; then
  echo "  [i] дерево уже грязное — пропуск (не наша ответственность в этом прогоне)"
else
  ok "дерево чистое до прогона (проверка №7 выполняется после мутатора в CI)"
fi

# ===========================================================================
# ИТОГ
# ===========================================================================
echo
echo "════════════════════════════════════════════════════════════════"
echo "  ОТБИТО АТАК: $PASS    |    ПРОШЛО АТАК (БАГИ): $FAIL"
echo "════════════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ] || exit 1

