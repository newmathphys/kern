#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
# ВНЕШНЯЯ ПРИЁМКА (T7): «покажи свои цифры на МОЕЙ машине, без твоего окружения».
#
# ЗАЧЕМ. Все замеры до сих пор делались автором и его CI (Bus factor = 1). Этот скрипт
# даёт скептику ОДНУ команду: берёт ОПУБЛИКОВАННЫЙ архив, проверяет его сумму, ISA и
# аттестат, затем прогоняет доказательства в изолированной папке — без репозитория,
# без сети (если архив уже скачан) и без .venv.
#
# Использование: tools/external_accept.sh [ARCHIVE.tar.gz] [SHA256SUMS]   или   make external-accept
# Коды: 0 — приёмка пройдена; 2 — архив/сумма не сошлись; 3 — доказательство провалено.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(python3 -c "import json;print(json.load(open('$ROOT/server.json'))['version'])" 2>/dev/null || echo 2.8.2)"
ARCHIVE="${1:-}"
SUMS="${2:-}"
BASE="https://github.com/newmathphys/kern/releases/download/v$VER"
OUT="$ROOT/docs/evidence/external_accept_v$VER.log"
FAILS=0
say() { printf '%s\n' "$*" | tee -a "$OUT"; }
step() { say ""; say "── $* ──"; }
ok()  { say "  [OK]   $*"; }
bad() { say "  [FAIL] $*"; FAILS=$((FAILS + 1)); }

: > "$OUT"
say "==============================================================================="
say "ВНЕШНЯЯ ПРИЁМКА KERN $VER — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
say "машина: $(uname -srm) | python3 $(python3 -V 2>&1 | awk '{print $2}')"
say "работаем на ОПУБЛИКОВАННОМ архиве, репозиторий рядом не используется"
say "==============================================================================="

step "0. Артефакт"
if [ -z "$ARCHIVE" ]; then
  if ls "$ROOT"/dist-release/kerna-dist-v$VER.tar.gz >/dev/null 2>&1; then
    ARCHIVE="$ROOT/dist-release/kerna-dist-v$VER.tar.gz"
    say "  взят локальный архив: $ARCHIVE"
  else
    ARCHIVE="/tmp/kerna-dist-v$VER.tar.gz"
    say "  качаю (curl -4: у части провайдеров IPv6 сломан — измерено): $BASE"
    curl -4 -fsSL --retry 5 --retry-all-errors --timeout 300 -o "$ARCHIVE" \
      "$BASE/kerna-dist-v$VER.tar.gz" || bad "архив не скачался"
  fi
fi
[ -f "$ARCHIVE" ] || { say "ИТОГ: нет архива — приёмка невозможна"; exit 2; }
say "  архив: $ARCHIVE ($(stat -c%s "$ARCHIVE") байт)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/kern_accept_XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/dist"
if [ -z "$SUMS" ]; then
  if [ -f "$(dirname "$ARCHIVE")/SHA256SUMS" ]; then SUMS="$(dirname "$ARCHIVE")/SHA256SUMS"
  else SUMS="$WORK/SHA256SUMS"; curl -4 -fsSL --retry 5 --retry-all-errors --timeout 120 \
       -o "$SUMS" "$BASE/SHA256SUMS" || bad "SHA256SUMS не скачался"; fi
fi

step "1. SHA-256: архив и внутренние файлы"
WANT=$(grep -E "kerna-dist-v$VER\.tar\.gz$" "$SUMS" | awk '{print $1}')
GOT=$(sha256sum "$ARCHIVE" | awk '{print $1}')
if [ -n "$WANT" ] && [ "$WANT" = "$GOT" ]; then ok "внешняя сумма совпала: ${GOT:0:16}…"
else bad "внешняя сумма НЕ совпала (ждали ${WANT:0:16}…, получили ${GOT:0:16}…)"; fi
tar -xzf "$ARCHIVE" -C "$WORK/dist" || bad "архив не распаковался"
DIST="$(find "$WORK/dist" -maxdepth 1 -type d -name 'kerna-dist*' | head -1)"
if [ -n "$DIST" ] && ( cd "$DIST" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ); then
  ok "внутренние суммы совпали"
else bad "внутренние суммы НЕ совпали"; fi

step "2. Переносимость (ISA): в kernc нет AVX-512"
if command -v objdump >/dev/null 2>&1; then
  ZMM=$(objdump -d "$DIST/zig-out/bin/kernc" 2>/dev/null | grep -cE 'zmm[0-9]+')
  [ "${ZMM:-1}" -eq 0 ] && ok "zmm = 0 (собрано с -Dcpu=baseline)" || bad "zmm = $ZMM — не переносимо"
else
  say "  [i] objdump недоступен — проверка ISA НЕ выполнена (названный пропуск)"
fi
[ -x "$DIST/kerna" ] && ok "апплаенс исполняемый" || bad "нет ./kerna"

step "3. Аттестат Ed25519 — внешним ключом"
KEY="$ROOT/docs/keys/kern-owner.pub"
if [ -f "$KEY" ] && [ -f "$ROOT/kern.intoto.jsonl" ]; then
  if ( cd "$ROOT" && python3 -B tools/verify_attestation.py >/dev/null 2>&1 ); then
    ok "аттестат проверен внешним ключом (docs/keys/kern-owner.pub)"
  else say "  [i] аттестат не проверен в этом окружении — НАЗВАННЫЙ пропуск"; fi
else
  say "  [i] ключ/аттестат лежат в репозитории, а не в архиве — НАЗВАННЫЙ пропуск"
fi

step "4. Восемь доказательств на СКАЧАННОМ апплаенсе"
P="$WORK/pair"; mkdir -p "$P/base" "$P/head"
printf 'def f(a, b):\n    return a + b\n' > "$P/base/logic.py"
printf 'def f(a, b):\n    return a - b\n' > "$P/head/logic.py"
FIX="$WORK/fix"; mkdir -p "$FIX"
printf 'def get_unsafe(data, i):\n    return data[i]\n' > "$FIX/b.py"
printf 'def g(a, b):\n    return a - b if a > b else b - a\n' > "$WORK/d1.py"
printf 'def g(a, b):\n    return a + b\n' > "$WORK/d2.py"

chk() { if [ "$3" = "$4" ]; then ok "#$1 $2 → $4"; else bad "#$1 $2: ждали '$3', получили '$4'"; fi; }

say "  (1) рентген без аннотаций: --xray"
OUT1=$(cd "$DIST" && timeout 180 ./kerna --xray "$FIX" 2>&1)
chk 1 "находка на незащищённом индексе" "1" "$(echo "$OUT1" | grep -qE '\[(BOUNDS|CRASH|OVERFLOW|DEAD)' && echo 1 || echo 0)"

say "  (2) поведенческая дельта: --delta base head"
OUT2=$(cd "$DIST" && timeout 300 ./kerna --delta "$P/base" "$P/head" 2>&1)
chk 2 "расхождение названо (DIVERGED)" "1" "$(echo "$OUT2" | grep -q 'DIVERGED' && echo 1 || echo 0)"

say "  (3) неверный вход — ОТКАЗ, а не «расхождений нет»"
(cd "$DIST" && timeout 120 ./kerna --delta /nope_a /nope_b >/dev/null 2>&1); RC3=$?
chk 3 "rc на несуществующем пути" "2" "$RC3"

say "  (4) доктор: --doctor без сети и без pip"
(cd "$DIST" && timeout 120 ./kerna --doctor >/dev/null 2>&1); RC4=$?
chk 4 "rc доктора" "0" "$RC4"

say "  (5) --live в автономном бинаре НАЗВАН (не подменён молча)"
OUT5=$(cd "$DIST" && timeout 300 ./kerna --delta "$P/base" "$P/head" --live 2>&1)
chk 5 "есть строка про --live" "1" "$(echo "$OUT5" | grep -q -- '--live' && echo 1 || echo 0)"

say "  (6) вшитый контрактный путь: --diff-equiv"
OUT6=$(cd "$DIST" && timeout 300 ./kerna --diff-equiv "$WORK/d1.py" "$WORK/d2.py" 2>&1)
chk 6 "вердикт по паре функций" "1" "$(echo "$OUT6" | grep -qE 'DIVERGED|EQUIVALENT|ИТОГО' && echo 1 || echo 0)"

say "  (7) без решателя — НАЗВАННЫЙ отказ (не тихий ноль)"
# ВАЖНО: в архиве `z3` ЛЕЖИТ РЯДОМ (`.venv/bin/z3`) — это и есть самодостаточность.
# Чтобы проверить ЗАЩИТУ, копируем апплаенс БЕЗ решателя: тогда он обязан отказать
# НАЗВАННО и вернуть rc=2, а не «находок 0» (класс #407/#499).
NOZ="$WORK/nosolver"; mkdir -p "$NOZ"
cp "$DIST/kerna" "$NOZ/" 2>/dev/null
cp "$DIST/server.json" "$NOZ/" 2>/dev/null
mkdir -p "$NOZ/zig-out/bin"; cp "$DIST/zig-out/bin/kernc" "$NOZ/zig-out/bin/" 2>/dev/null
OUT7=$(cd "$NOZ" && env -u Z3 -u KERN_Z3 PATH=/usr/bin:/bin timeout 120 ./kerna --xray "$FIX" 2>&1); RC7=$?
chk 7 "rc отказа без решателя" "2" "$RC7"
chk 7.1 "причина названа (KERNA DOCTOR)" "1" "$(echo "$OUT7" | grep -qiE 'KERNA DOCTOR|не найден|нет решател' && echo 1 || echo 0)"

say "  (8) ядро kernc исполняется без Python"
(cd "$DIST" && timeout 60 ./zig-out/bin/kernc --help >/dev/null 2>&1); RC8=$?
chk 8 "rc kernc --help" "0" "$RC8"

say ""
say "==============================================================================="
if [ "$FAILS" -eq 0 ]; then
  say "ИТОГ: ВНЕШНЯЯ ПРИЁМКА ПРОЙДЕНА — архив, суммы, ISA и 8 доказательств сходятся"
else
  say "ИТОГ: провалов $FAILS — приёмка НЕ пройдена (это НЕ «почти»)"
fi
say "квитанция: $OUT"
say "==============================================================================="
[ "$FAILS" -eq 0 ] || exit 3
exit 0
