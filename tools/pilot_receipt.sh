#!/usr/bin/env bash
# Copyright (c) 2026 Vital Kalinousky. SPDX-License-Identifier: AGPL-3.0-or-later. Commercial use requires a separate license — see LICENSE-COMMERCIAL.md
#
# КВИТАНЦИЯ ВНЕШНЕГО ПИЛОТА (T7). Одна команда для ЧЕЛОВЕКА, у которого НЕТ
# ничего, кроме интернета: ни репозитория, ни Zig, ни Python-пакетов.
#
#   tools/pilot_receipt.sh                 # скачает релиз v2.8.2 и проверит
#   tools/pilot_receipt.sh archive.tar.gz  # проверит ЛОКАЛЬНЫЙ архив
#
# ЧТО ЗНАЧИТ «СОВПАЛО». Скрипт печатает строку `EXPECT: …` рядом с каждым
# измерением. Человеку НЕ нужно ничего трактовать: в конце печатается
# `PILOT RECEIPT: PASS (n/n)` либо `FAIL (k/n)` + какие именно строки не сошлись.
# Его задача — прислать вывод целиком: это и есть независимая квитанция.
#
# ЧЕГО СКРИПТ НЕ ДЕЛАЕТ: не обращается к репозиторию KERN, не ставит пакеты,
# не требует root. Всё, что он использует, — `curl`, `sha256sum`, `tar` и сам
# апплаенс (`./kerna`), который несёт внутри свой Python и `z3`.
set -uo pipefail

VER="${KERN_VER:-v2.8.2}"
BASE="${KERN_BASE:-https://github.com/newmathphys/kern/releases/download/$VER}"
WORK="$(mktemp -d /tmp/kern_pilot.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
ok=0; total=0
check() { # $1=имя $2=ожидание $3=факт
  total=$((total + 1))
  if [ "$2" = "$3" ]; then ok=$((ok + 1)); printf '  [OK]   %-38s %s\n' "$1" "$3"
  else printf '  [FAIL] %-38s получили %s, EXPECT: %s\n' "$1" "$3" "$2"; fi
}

echo "=============================================================="
echo "KERN PILOT RECEIPT — $VER"
echo "машина: $(uname -srm) | $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================================="

ARC="${1:-}"
if [ -z "$ARC" ]; then
  echo "── 0. Загрузка релиза ──"
  curl -4 -fsSL --retry 3 --max-time 300 -o "$WORK/SHA256SUMS" "$BASE/SHA256SUMS" \
    || { echo "[!] нет сети до GitHub Releases — это НАЗВАННЫЙ отказ, не «KERN плох»"; exit 2; }
  curl -4 -fsSL --retry 3 --max-time 300 -o "$WORK/kerna-dist-$VER.tar.gz" "$BASE/kerna-dist-$VER.tar.gz" \
    || { echo "[!] архив не скачался"; exit 2; }
  ARC="$WORK/kerna-dist-$VER.tar.gz"
else
  cp "$ARC" "$WORK/kerna-dist-$VER.tar.gz"; ARC="$WORK/kerna-dist-$VER.tar.gz"
  [ -f SHA256SUMS ] && cp SHA256SUMS "$WORK/SHA256SUMS"
fi

echo "── 1. Целостность архива ──"
S=$(sha256sum "$ARC" | cut -d' ' -f1)
echo "  sha256 архива: $S"
if [ -f "$WORK/SHA256SUMS" ]; then
  if grep -q "kerna-dist-$VER.tar.gz" "$WORK/SHA256SUMS" 2>/dev/null; then
    EXP=$(grep "kerna-dist-$VER.tar.gz" "$WORK/SHA256SUMS" | cut -d' ' -f1)
    check "sha256 == опубликованный" "$EXP" "$S"
  else
    echo "  [i] в SHA256SUMS нет строки архива — сверка пропущена (названо)"
  fi
fi

echo "── 2. Распаковка и самодостаточность ──"
mkdir -p "$WORK/dist" && tar -xzf "$ARC" -C "$WORK/dist" --strip-components=1 || { echo "[!] архив не распаковался"; exit 2; }
A="$WORK/dist/kerna"
check "апплаенс запускается" "0" "$("$A" --doctor >/dev/null 2>&1; echo $?)"
"$A" --doctor 2>&1 | grep -q 'зависимости на месте\|dependencies present' \
  && echo "  [OK]   doctor: зависимости на месте" || echo "  [FAIL] doctor не подтвердил зависимости"

echo "── 3. Переносимость (ISA) ──"
if command -v objdump >/dev/null 2>&1; then
  Z=$(objdump -d "$WORK/dist/zig-out/bin/kernc" 2>/dev/null | grep -c zmm)
  check "AVX-512 инструкций (zmm) в kernc" "0" "$Z"
else
  echo "  [i] objdump нет — проверка ISA названа пропуском"
fi

echo "── 4. Находка на контрольном коде (судья — сам KERN) ──"
mkdir -p "$WORK/pair/base" "$WORK/pair/head"
printf 'def f(a):\n    return a + 1\n' > "$WORK/pair/base/m.py"
printf 'def f(a):\n    return 1 // (a - a)\n' > "$WORK/pair/head/m.py"
OUT="$("$A" --delta "$WORK/pair/base" "$WORK/pair/head" --no-semantic --json 2>/dev/null)"; RC=$?
check "rc на ВНЕСЁННОМ баге" "1" "$RC"
N=$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(len(json.load(sys.stdin).get("new_findings",[])))' 2>/dev/null || echo "?")
check "новых находок в ABI" "1" "$N"

echo "── 5. SARIF 2.1.0 (для GitHub Code Scanning) ──"
"$A" --delta "$WORK/pair/base" "$WORK/pair/head" --no-semantic --sarif "$WORK/out.sarif" --json >/dev/null 2>&1
if [ -s "$WORK/out.sarif" ]; then
  VER_S=$(python3 -c 'import json;d=json.load(open("'"$WORK"'/out.sarif"));print(d.get("version"))' 2>/dev/null || echo "?")
  LINE=$(python3 -c 'import json;d=json.load(open("'"$WORK"'/out.sarif"));print(d["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"])' 2>/dev/null || echo "?")
  check "версия SARIF" "2.1.0" "$VER_S"
  check "startLine указывает на строку бага" "2" "$LINE"
else
  echo "  [FAIL] SARIF не создан"
fi

echo "── 6. Отказ не выглядит успехом ──"
"$A" --delta "$WORK/нет-такого" "$WORK/нет-такого" --json >/dev/null 2>&1
check "rc на несуществующем пути" "2" "$?"

echo "=============================================================="
if [ "$ok" -eq "$total" ]; then
  echo "PILOT RECEIPT: PASS ($ok/$total) — пришлите этот вывод целиком"
  exit 0
else
  echo "PILOT RECEIPT: FAIL ($ok/$total) — пришлите вывод: расхождение и есть дефект"
  exit 1
fi
