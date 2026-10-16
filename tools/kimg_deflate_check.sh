#!/usr/bin/env bash
# KERN: проверка СЖАТИЯ объектов (кодек deflate 0x02) в CLI.
#
# ЧТО ПРОВЕРЯЕТСЯ (цель `make kimg-deflate`):
#   1. `kernc build --deflate` реально сжимает объекты (образ меньше, чем raw);
#   2. `kernc check-integrity` проходит на сжатом образе;
#   3. `kernc cat` ПРОЗРАЧНО распаковывает и отдаёт содержимое ПОБАЙТОВО
#      идентичное исходному файлу;
#   4. порча одного байта ВНУТРИ сжатого потока обнаруживается (rc != 0).
#
# ЭТО ПРОВЕРКА, А НЕ ДЕМО: при любом расхождении скрипт падает (exit != 0).
# Поэтому у цели есть can-fail кейс (`kimg-deflate` в tools/canfail.py).
set -u
cd "$(dirname "$0")/.."
KERNC=./zig-out/bin/kernc
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0
note() { echo "  $1"; }
bad() { echo "  [ПРОВАЛ] $1"; fails=$((fails + 1)); }

[ -x "$KERNC" ] || { echo "[!] нет $KERNC (соберите: zig build)"; exit 2; }

# .kern с РЕАЛЬНЫМИ файлами репозитория (текст хорошо сжимается).
python3 - "$TMP/src.kern" <<'PY'
import glob, pathlib, sys
files = sorted(glob.glob("src/core/*.zig"))[:10]
out = ['project "deflate-check" {\n  version "1.0"\n  mode "truth"\n  root "."\n}\n']
for f in files:
    out.append(f'artifact "{f}" {{\n  kind "source.file"\n  hash "sha256:pending"\n}}\n')
pathlib.Path(sys.argv[1]).write_text("\n".join(out), encoding="utf-8")
print(f"  объекты: {len(files)}")
PY

"$KERNC" build "$TMP/src.kern" -o "$TMP/raw.kimg"   >/dev/null 2>&1
"$KERNC" build "$TMP/src.kern" -o "$TMP/def.kimg" --deflate >/dev/null 2>&1
raw=$(stat -c%s "$TMP/raw.kimg"); def=$(stat -c%s "$TMP/def.kimg")
note "размер: raw=$raw deflate=$def"
[ "$def" -lt "$raw" ] || bad "сжатие НЕ уменьшило образ (--deflate не работает?)"

"$KERNC" check-integrity "$TMP/def.kimg" >/dev/null 2>&1 \
  && note "check-integrity: OK" || bad "check-integrity не прошёл на сжатом образе"

# Побайтовая сверка содержимого после прозрачной распаковки.
ok=0; badn=0
for f in src/core/*.zig; do
  [ -f "$f" ] || continue
  if "$KERNC" cat "$TMP/def.kimg" "/raw/$f" 2>/dev/null | cmp -s - "$f"; then
    ok=$((ok + 1))
  else
    badn=$((badn + 1)); echo "  [ПРОВАЛ] cat не совпал: $f"
  fi
done
note "cat побайтово совпал: $ok, различий: $badn"
[ "$badn" -eq 0 ] || fails=$((fails + 1))

# Порча байта ВНУТРИ сжатого потока объекта 0 -> обязана быть обнаружена.
OBJ=$(python3 - "$TMP/def.kimg" "$TMP/tamper.kimg" <<'PY'
import struct, sys, pathlib
d = bytearray(pathlib.Path(sys.argv[1]).read_bytes())
dpo = struct.unpack_from('<Q', d, 56)[0]
poff = struct.unpack_from('<Q', d, 128 + 32)[0]
lpo = struct.unpack_from('<I', d, 128 + 64)[0]
name = d[dpo + lpo:d.index(b'\x00', dpo + lpo)].decode()
d[dpo + poff + 5] ^= 0xFF          # +5 — внутри потока, а не в заголовке блока
pathlib.Path(sys.argv[2]).write_bytes(bytes(d))
print(name)
PY
)
"$KERNC" cat "$TMP/tamper.kimg" "/raw/$OBJ" >/dev/null 2>&1
rc=$?
[ "$rc" -ne 0 ] && note "порча сжатого потока обнаружена (rc=$rc)" \
                || bad "порча сжатого потока НЕ обнаружена (rc=0) — объект выдан как валидный"

echo "---"
if [ "$fails" -ne 0 ]; then
  echo "ПРОВАЛОВ: $fails"
  exit 1
fi
echo "СЖАТИЕ 0x02: сборка/целостность/распаковка/порча — ВСЁ ПРОВЕРЕНО"
